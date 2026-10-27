"""READ-ONLY MCP server for code_aster MED results.

It never launches runs or modifies the .med files. It only writes new outputs
(PNG, CSV, VTU, figures) in <output folder>/<med name>/ (see viewer.output_root).
Texts for the model are in English; the viewer opened by med_view, in the user's language.
"""
from __future__ import annotations

import functools
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import numpy as np
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .derived import Axis, derived_names, evaluate, flatten, label, needs_axis, stats
from .i18n import CHOICES, canonical
from .medfile import MedError, open_med
from .viewer import free_port, out_dir

INSTRUCTIONS = """\
Tools to READ code_aster MED results (they never run simulations or modify files).
Typical flow: med_info(path) first (fields, components, time steps, groups); then
med_stats / med_history / med_line / med_extract for numbers, med_render for an image,
med_figure for a journal figure, med_view to open the interactive viewer for the user,
med_to_vtu to export for ParaView.
- Fields by short name (DEPL, SIEF_ELGA) or full name (RESU____DEPL).
- Time step: time=<value> (the nearest) or step=<index> (-1 = last, the default).
- Derived components: NORM, DR/DT/DA (cylindrical displacement), <P>RR/<P>TT/<P>AA/<P>RT/<P>RA/<P>TA
  (e.g. SIRR = sigma_r), VMIS, TRACE. Cylindrical components use an axis: by default the long side of
  the bounding box through its centre; change it with axis_point / axis_dir. The radial direction is
  taken from the UNDEFORMED geometry.
- Fields with a profile (model restricted with GROUP_MA): outside the profile the value is NaN, never 0.
- ELGA fields: statistics use the Gauss points. Images and cuts paint ONE value per element
  (cell_reduce = mean | min | max | absmax of its Gauss points; the default mean hides peaks):
  for numbers to report, use med_stats / med_extract.
- ELNO fields (one value per node of each element) are treated like ELGA ones, at the element nodes.
- 2D models (D_PLAN, C_PLAN, AXIS): coordinates x, y; in AXIS, SIXX = σr, SIYY = σz, SIZZ = σθ.
  VMIS and TRACE are available; cylindrical components are not offered in 2D.
- Files with several meshes: med_info lists them; each field is read on its own mesh. If a short
  field name exists on two meshes, pass the full name (e.g. r2d_____DEPL) or mesh=<name>.
- Units are those of the model (MED files do not store them).
"""

mcp = MCPServer("aster-med", instructions=INSTRUCTIONS, log_level="WARNING")
_viewers = {}
# synchronous tools run in threads: VTK/OpenGL one at a time
_VTK = threading.Lock()


def tool(fn):
    """Registers the tool; expected errors (MedError) come back as a
    message for the user, without traceback."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except MedError as e:
            raise ToolError(str(e)) from None
    return mcp.tool()(wrapper)


def _fmt(x):
    return "NaN" if x is None or not np.isfinite(x) else f"{x:.6g}"


def _axis(res, axis_point, axis_dir):
    return Axis.make(res.mesh, axis_point, axis_dir)


def _open(path, field=None, mesh=None):
    """The file seen from one mesh: the requested one, the field's, or the first with fields.
    With several meshes, a repeated short name (DEPL on both) needs the full name or mesh=."""
    res = open_med(path)
    if mesh:
        res = res.view(mesh)
    if field:
        return res.view(res.field(field).mesh)
    return res if mesh else res.view(res.mesh_name)


def _plot(x, ys, xlabel, ylabel, path):
    """Plot in the style of the journal figures (one column, DejaVu Sans 9/10 pt):
    writes path (PNG 600 dpi) and the same as .pdf; returns a preview. The file and the
    time step go in the text of the answer, not in the figure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .figure import PAPER_RC
    with matplotlib.rc_context(PAPER_RC):
        fig, ax = plt.subplots(figsize=(3.46, 2.4))
        for lab, y in ys:
            ax.plot(x, y, marker="o" if len(x) <= 30 else None, ms=3, label=lab)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.3, lw=0.5)
        if len(ys) > 1:
            ax.legend()
        fig.savefig(path, dpi=600)
        fig.savefig(path[:-4] + ".pdf")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150)
        plt.close(fig)
    return Image(data=buf.getvalue(), format="png")


@tool
def med_info(path: str) -> str:
    """Summary of a .med file: mesh (nodes, cells per type, bounding box), groups, and fields
    with their support (NODE/ELGA/ELEM), components, number of time steps, time range and
    whether they have a profile. Detects truncated files."""
    base = open_med(path)
    many = len(base.mesh_names) > 1
    out = [f"# {os.path.basename(base.path)}  ({base.size / 1e6:.1f} MB)"]
    if many:
        out += [f"{len(base.mesh_names)} meshes; each field lives on one of them. Tools take the full field "
                "name or mesh=<name> when a short name is repeated.", ""]
    for mname in base.mesh_names:
        res = base.view(mname)
        m = res.mesh
        lo, hi = m.bbox()
        out += [f"## Mesh '{m.name}' ({m.space_dim}D): {m.n_nodes} nodes; cells: " +
                ", ".join(f"{t}={b.ne}" for t, b in m.blocks.items()),
                f"Box: min ({', '.join(_fmt(v) for v in lo)})  max ({', '.join(_fmt(v) for v in hi)})"]
        if m.space_dim == 3:
            out.append(f"Default axis for cylindrical components: {Axis.auto(m).describe()}")
        out += ["", "| field | full name | support | components | steps | first → last time | profile |",
                "|---|---|---|---|---|---|---|"]
        for f in res.fields.values():
            comps = " ".join(f.components)
            der = derived_names(f.components, m.space_dim)
            if der:
                comps += f" (+ derived: {' '.join(der)})"
            t0, t1 = (f.steps[0].time, f.steps[-1].time) if f.steps else (np.nan, np.nan)
            out.append(f"| {f.short} | {f.name} | {f.support} | {comps} | {len(f.steps)} | {_fmt(t0)} → {_fmt(t1)} | "
                       f"{'yes' if f.profiled else 'no'} |")
        if not res.fields:
            out.append("| (no fields) | | | | | | |")
        cg = sorted(m.cell_groups.items(), key=lambda kv: (-m.group_dim(kv[0]), kv[0]))
        out += ["", "Cell groups (dim: cells): " +
                (", ".join(f"{g} ({m.group_dim(g)}D: {sum(len(i) for i in d.values())})" for g, d in cg) or "(none)"),
                "Node groups: " + (", ".join(f"{g} ({len(i)})" for g, i in sorted(m.node_groups.items())) or "(none)"),
                ""]
    return "\n".join(out).rstrip()


@tool
def med_steps(path: str, field: str, mesh: str | None = None) -> str:
    """Time steps of a field: index, NUME_ORDRE (ndt), time."""
    res = _open(path, field, mesh)
    info = res.field(field)
    rows = [f"| {i} | {s.ndt} | {_fmt(s.time)} |" for i, s in enumerate(info.steps)]
    return "\n".join([f"{info.name}: {len(info.steps)} time steps", "| index | ndt | time |", "|---|---|---|"] + rows)


@tool
def med_stats(path: str, field: str, component: str, group: str | None = None,
              time: float | None = None, step: int | None = None,
              axis_point: list[float] | None = None, axis_dir: list[float] | None = None,
              mesh: str | None = None) -> str:
    """Statistics of a component at one time step, over the whole model or a group:
    minimum and maximum with their location (node, or cell + Gauss point, and coordinates),
    mean, standard deviation and percentiles 5/50/95. Counts how many points have a value (profile)."""
    res = _open(path, field, mesh)
    fs = res.read(field, step=step, time=time)
    ax = _axis(res, axis_point, axis_dir)
    vals = evaluate(res, fs, component, ax)
    v, xyz, labs = flatten(res, fs, vals, group)
    s = stats(v)
    head = (f"{fs.info.short} {component} | t = {_fmt(fs.step.time)} (step {fs.index}) | "
            f"{'group ' + group if group else 'whole model'} | support {fs.info.support}")
    if needs_axis(component):
        head += f"\n{ax.describe()}"
    if not s.get("definidos"):
        return head + f"\nNo defined values ({s['n']} points, all NaN: outside the profile?)"
    loc = lambda i: f"{label(labs, i)} at ({', '.join(_fmt(c) for c in xyz[i])})"
    return "\n".join([
        head,
        f"points with a value: {s['definidos']} of {s['n']}",
        f"min  {_fmt(s['min'])}   [{loc(s['imin'])}]",
        f"max  {_fmt(s['max'])}   [{loc(s['imax'])}]",
        f"mean {_fmt(s['media'])}   std {_fmt(s['desvio'])}",
        f"p05 {_fmt(s['p05'])}   p50 {_fmt(s['p50'])}   p95 {_fmt(s['p95'])}",
    ])


def _nearest(xyz, point):
    d = np.linalg.norm(xyz - np.asarray(point, float), axis=1)
    i = int(np.nanargmin(d))
    return i, float(d[i])


@tool
def med_history(path: str, field: str, component: str, group: str | None = None,
                node: int | None = None, point: list[float] | None = None, reduce: str = "mean",
                axis_point: list[float] | None = None, axis_dir: list[float] | None = None,
                plot: bool = True, xlabel: str | None = None, ylabel: str | None = None,
                mesh: str | None = None):
    """Time history of a component over ALL the time steps of the field.
    Choose ONE: group (+ reduce = mean|min|max|p05|p50|p95), node (1-based node number,
    nodal fields) or point [x,y,z] (the node or Gauss point nearest to that undeformed point).
    With none of them, reduces over the whole model. Returns a table and (plot=True) a plot in
    journal style (PNG 600 dpi + PDF, one column); xlabel / ylabel accept mathtext."""
    res = _open(path, field, mesh)
    info = res.field(field)
    ax = _axis(res, axis_point, axis_dir)
    times, ys, where = [], [], ""
    pick = None
    for i in range(len(info.steps)):
        fs = res.read(info.name, step=i)
        vals = evaluate(res, fs, component, ax)
        if node is not None:
            if fs.node is None:
                raise MedError("node= only works for nodal fields; use point= or group=")
            y = float(vals[int(node) - 1])
            where = f"node N{node}"
        else:
            v, xyz, labs = flatten(res, fs, vals, group)
            if point is not None:
                if pick is None:
                    pick, dist = _nearest(xyz, point)
                    where = f"{label(labs, pick)} ({dist:.3g} from the requested point)"
                y = float(v[pick])
            else:
                s = stats(v)
                y = s.get({"mean": "media"}.get(reduce, reduce), np.nan) if s.get("definidos") else np.nan
                where = f"{reduce} over {'group ' + group if group else 'the whole model'}"
        times.append(fs.step.time)
        ys.append(y)
    rows = [f"| {_fmt(t)} | {_fmt(y)} |" for t, y in zip(times, ys)]
    txt = "\n".join([f"{info.short} {component} — {where}", "| time | value |", "|---|---|"] + rows)
    if not plot:
        return txt
    od = out_dir(res.path)
    png = os.path.join(od, f"history_{info.short}_{component}_{time.strftime('%H%M%S')}.png")
    img = _plot(times, [(component, ys)], xlabel or "time", ylabel or f"{info.short} {component}", png)
    return [txt + f"\n\nPlot: {png} (+ .pdf)", img]


@tool
def med_line(path: str, field: str, component: str, p0: list[float], p1: list[float],
             n: int = 200, time: float | None = None, step: int | None = None,
             groups: list[str] | None = None, axis_point: list[float] | None = None,
             axis_dir: list[float] | None = None, plot: bool = True, xlabel: str | None = None,
             ylabel: str | None = None, mesh: str | None = None):
    """Profile of a component along the segment p0 -> p1 (undeformed geometry), interpolated
    in the mesh (ELGA fields: the cell mean, piecewise constant). groups restricts the cells
    used (e.g. one part only, so the line does not cross into another one).
    Writes a CSV and (plot=True) a plot in journal style (PNG 600 dpi + PDF, one column);
    xlabel / ylabel accept mathtext ('$\\sigma_{xx}$ (MPa)')."""
    res = _open(path, field, mesh)
    with _VTK:
        return _med_line(res, field, component, p0, p1, n, time, step, groups, axis_point, axis_dir, plot,
                         xlabel, ylabel)


def _med_line(res, field, component, p0, p1, n, time, step, groups, axis_point, axis_dir, plot,
              xlabel=None, ylabel=None):
    from .scene import Scene, probe_grid
    sc = Scene(res)
    try:
        sc.field, sc.comp = res.field(field).name, component
        sc.step = res.field(field).step_index(step, time)
        sc.groups = groups or []
        sc.axis = _axis(res, axis_point, axis_dir)
        info = sc.update()
        grid = sc.src.GetOutputDataObject(0)
        a, b = np.asarray(p0, float), np.asarray(p1, float)
        pts = a + np.linspace(0.0, 1.0, max(int(n), 2))[:, None] * (b - a)
        # also the points on a boundary face (e.g. a ligament on a symmetry plane)
        val, mask = probe_grid(grid, pts, 5e-5 * float(np.linalg.norm(np.subtract(*res.mesh.bbox()))))
    finally:
        sc.rw.Finalize()
    val[~mask] = np.nan
    s = np.linalg.norm(pts - pts[0], axis=1)
    od = out_dir(res.path)
    stamp = time_tag()
    csv = os.path.join(od, f"line_{res.field(field).short}_{component}_{stamp}.csv")
    np.savetxt(csv, np.column_stack([s, pts, val]), delimiter=",", header="s,x,y,z,value", comments="")
    k = max(1, len(s) // 25)
    rows = [f"| {_fmt(a)} | {_fmt(b)} |" for a, b in zip(s[::k], val[::k])]
    txt = "\n".join([f"{res.field(field).short} {component} along the line, t = {_fmt(info.get('tiempo'))} "
                     f"({int(mask.sum())}/{len(mask)} points inside the mesh). Full CSV: {csv}",
                     "| s | value |", "|---|---|"] + rows)
    if not plot:
        return txt
    png = csv[:-4] + ".png"
    img = _plot(s, [(component, val)], xlabel or "distance from p0", ylabel or component, png)
    return [txt + f"\nPlot: {png} (+ .pdf)", img]


def time_tag():
    return time.strftime("%H%M%S")


@tool
def med_extract(path: str, field: str, components: list[str], group: str,
                time: float | None = None, step: int | None = None,
                axis_point: list[float] | None = None, axis_dir: list[float] | None = None,
                mesh: str | None = None) -> str:
    """Raw values of one or more components over a group, with coordinates and label
    (node; cell + Gauss point; or, for ELNO fields, cell + node). Writes a CSV and shows the first rows."""
    res = _open(path, field, mesh)
    fs = res.read(field, step=step, time=time)
    ax = _axis(res, axis_point, axis_dir)
    cols, xyz, labs = [], None, None
    for c in components:
        v, xyz, labs = flatten(res, fs, evaluate(res, fs, c, ax), group)
        cols.append(v)
    kind, ids, gps = labs
    od = out_dir(res.path)
    csv = os.path.join(od, f"extract_{fs.info.short}_{group}_t{fs.step.time:g}_{time_tag()}.csv")
    head = ({"nodo": ["node"], "elno": ["cell", "node"]}.get(kind, ["cell", "gauss_point"])
            + ["x", "y", "z"] + list(components))
    table = [ids[:, None]] if kind == "nodo" else [ids[:, None], gps[:, None]]
    data = np.hstack(table + [xyz] + [c[:, None] for c in cols])
    np.savetxt(csv, data, delimiter=",", header=",".join(head), comments="", fmt="%.10g")
    lines = [f"{fs.info.short} t = {_fmt(fs.step.time)} on {group}: {len(data)} rows → {csv}",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in data[:15]:
        lines.append("| " + " | ".join(_fmt(x) for x in r) + " |")
    if len(data) > 15:
        lines.append(f"... ({len(data) - 15} more rows in the CSV)")
    return "\n".join(lines)


def _keys(kind):
    return " | ".join(k for k in CHOICES[kind] if k not in ("none", "custom"))


RENDER_DOC = f"""
    Scene (same controls as the viewer): groups = visible cell groups (default: the volumes);
    window = [a, b] window on the coordinate along the axis (zoom on a region);
    warp_scale = deformed shape DEPL × scale; threshold = [a, b] only cells with a value in range;
    hide_nan = hide cells without a value.
    Cut: clip_mode = {_keys("clip_mode")}, with clip_origin [x,y,z] and clip_normal [nx,ny,nz]
    (or the shortcut clip_axis 'x'|'y'|'z' + clip_value); clip_flip = keep the other side.
    View: view = iso, +x, -x, +y, -y, +z, -z; zoom; parallel = parallel projection.
    Colors: cmap (ParaView presets: Cool to Warm, Jet, Turbo, Viridis, Rainbow Uniform, Blue Orange
    (divergent), Inferno, Black-Body, Grayscale...), invert, log, bands, vmin/vmax, symmetric.
    representation = {_keys("representation")}; shading; opacity;
    edge_color / edge_width (px); show_nodes + node_color / node_size (px);
    cell_reduce (ELGA fields) = {_keys("cell_reduce")} of the Gauss points of each element;
    background = {_keys("background")} | '#rrggbb'.
    bar_position = right | left | top | bottom (top and bottom are horizontal).
    Option values also accept their Spanish/French labels.
    view_json: a view saved from the viewer (<output>/<med>/vistas/*.json) or a figure recipe:
    reproduces exactly that scene and camera (the other scene parameters are ignored)."""


def _configure(sc, res, field=None, component=None, time=None, step=None, groups=None, window=None,
               warp_scale=0.0, clip_mode=None, clip_origin=None, clip_normal=None, clip_axis=None,
               clip_value=None, clip_flip=False, threshold=None, view="iso", zoom=1.0, parallel=False,
               cmap="Cool to Warm", invert=False, log=False, vmin=None, vmax=None, symmetric=False, bands=0,
               representation="surface", edges=False, shading=True, opacity=1.0, background="light_gradient",
               hide_nan=False, axis_point=None, axis_dir=None, view_json=None, edge_color="#38383f",
               edge_width=1.0, show_nodes=False, node_color="#202024", node_size=5.0, cell_reduce="mean",
               bar_position="right"):
    if view_json:
        with open(os.path.expanduser(view_json)) as f:
            d = json.load(f)
        return sc.apply_settings(d)
    if field:
        info = res.field(field)
        sc.field = info.name
        sc.comp = component or info.components[0]
        sc.step = info.step_index(step, time)
    sc.groups = groups or []
    sc.axis = _axis(res, axis_point, axis_dir)
    sc.window = tuple(window) if window else None
    sc.warp_scale = float(warp_scale or 0)
    sc.threshold = tuple(threshold) if threshold else None
    clip_mode = canonical("clip_mode", clip_mode)
    if clip_axis and clip_mode in (None, "none"):
        clip_mode = "clip"
    if clip_mode and clip_mode != "none":
        lo, hi = res.mesh.bbox()
        o = np.asarray(clip_origin, float) if clip_origin is not None else (lo + hi) / 2
        if clip_axis:
            k = "xyz".index(clip_axis.lower())
            n = np.zeros(3)
            n[k] = 1.0
            if clip_value is not None:
                o[k] = float(clip_value)
        else:
            n = np.asarray(clip_normal if clip_normal is not None else [1, 0, 0], float)
        sc.clip_mode, sc.clip_origin, sc.clip_normal, sc.clip_invert = clip_mode, o, n, bool(clip_flip)
    sc.cmap, sc.invert, sc.log, sc.bands, sc.symmetric = cmap, invert, log, bands, symmetric
    if vmin is not None and vmax is not None:
        sc.range = (float(vmin), float(vmax))
    sc.representation = representation
    if edges and sc.representation == "surface":
        sc.representation = "surface_edges"
    sc.shading, sc.opacity, sc.background, sc.hide_nan = shading, opacity, background, hide_nan
    sc.edge_color, sc.edge_width, sc.show_nodes = edge_color, float(edge_width), bool(show_nodes)
    sc.node_color, sc.node_size = node_color, float(node_size)
    sc.cell_reduce = cell_reduce
    sc.bar_pos = bar_position
    info_d = sc.update()
    sc.ren.GetActiveCamera().SetParallelProjection(1 if parallel else 0)
    sc.set_view(view, zoom)
    return info_d


@tool
def med_render(path: str, field: str | None = None, component: str | None = None,
               time: float | None = None, step: int | None = None,
               groups: list[str] | None = None, window: list[float] | None = None,
               warp_scale: float = 0.0, clip_mode: str | None = None, clip_origin: list[float] | None = None,
               clip_normal: list[float] | None = None, clip_axis: str | None = None, clip_value: float | None = None,
               clip_flip: bool = False, threshold: list[float] | None = None, view: str = "iso", zoom: float = 1.0,
               parallel: bool = False, cmap: str = "Cool to Warm", invert: bool = False, log: bool = False,
               vmin: float | None = None, vmax: float | None = None, symmetric: bool = False, bands: int = 0,
               representation: str = "surface", edges: bool = False, shading: bool = True,
               opacity: float = 1.0, background: str = "light_gradient", hide_nan: bool = False,
               axis_point: list[float] | None = None, axis_dir: list[float] | None = None,
               view_json: str | None = None, edge_color: str = "#38383f", edge_width: float = 1.0,
               show_nodes: bool = False, node_color: str = "#202024", node_size: float = 5.0,
               cell_reduce: str = "mean", bar_position: str = "right", width: int = 1400, height: int = 800,
               mesh: str | None = None):
    """PNG image of the field on the mesh (same scene as the interactive viewer). Without field: the mesh only.
    mesh: for files with several meshes (default: the field's mesh, or the first one with fields)."""
    if view_json:
        with open(os.path.expanduser(view_json)) as f:
            mesh = json.load(f).get("mesh") or mesh
    res = _open(path, field if not view_json else None, mesh)
    kw = {k: v for k, v in locals().items() if k not in ("path", "res", "width", "height", "mesh", "f")}
    with _VTK:
        from .scene import Scene
        sc = Scene(res, size=(int(width), int(height)))
        try:
            info_d = _configure(sc, res, **kw)
            od = out_dir(res.path)
            tag = f"{res.field(sc.field).short}_{sc.comp}_t{info_d.get('tiempo'):g}" if sc.field else "mesh"
            png = os.path.join(od, f"{tag}_{time_tag()}.png")
            sc.screenshot(png)
        finally:
            sc.rw.Finalize()
    with open(png, "rb") as f:
        data = f.read()
    txt = f"Image: {png}"
    if sc.field:
        txt += (f"\n{res.field(sc.field).short} {sc.comp} t = {_fmt(info_d.get('tiempo'))}: "
                f"min {_fmt(info_d.get('min'))}, max {_fmt(info_d.get('max'))} "
                f"(as painted{'; ' + info_d['reduccion'] + ' per element' if 'reduccion' in info_d else ''}); "
                f"color scale {_fmt(sc.last_range[0])} … {_fmt(sc.last_range[1])}")
        if "reduccion" in info_d:
            where = "element nodes" if info_d.get("soporte") == "ELNO" else "Gauss points"
            txt += f"\nAt the {where}: min {_fmt(info_d['pg_min'])}, max {_fmt(info_d['pg_max'])}"
        if info_d.get("celdas_ocultas"):
            txt += f"\n{info_d['celdas_ocultas']} cells hidden (no value, no displacement or outside the threshold)"
    return [txt, Image(data=data, format="png")]


med_render.__doc__ += RENDER_DOC


@tool
def med_figure(path: str | None = None, recipe: str | None = None, field: str | None = None,
               component: str | None = None, time: float | None = None, step: int | None = None,
               groups: list[str] | None = None, window: list[float] | None = None, warp_scale: float = 0.0,
               clip_mode: str | None = None, clip_origin: list[float] | None = None,
               clip_normal: list[float] | None = None, threshold: list[float] | None = None,
               view: str = "iso", zoom: float = 1.0, parallel: bool = True, cmap: str = "Cool to Warm",
               invert: bool = False, vmin: float | None = None, vmax: float | None = None,
               symmetric: bool = False, bands: int = 0, edges: bool = False, hide_nan: bool = False,
               axis_point: list[float] | None = None, axis_dir: list[float] | None = None,
               edge_color: str = "#38383f", edge_width: float = 1.0, show_nodes: bool = False,
               node_color: str = "#202024", node_size: float = 5.0, cell_reduce: str = "mean",
               view_aspect: float = 0.5, width: str | None = None, bar: str | None = None,
               label: str | None = None, factor: float | None = None, nticks: int | None = None,
               shading: bool | None = None, scalebar: bool | None = None, sb_factor: float | None = None,
               sb_unit: str | None = None, name: str | None = None, receta: str | None = None,
               mesh: str | None = None):
    """Journal figure: VTK draws only the geometry (white background, no shading, so the colors
    are exactly those of the color bar) and matplotlib adds the color bar and text (DejaVu Sans
    9/10 pt). Writes PDF + 600 dpi PNG + a .json recipe in <output>/<med>/figuras/ and suggests the
    \\includegraphics width that keeps the font size of other one-column figures (243 pt column).
    recipe: .json of a previous figure or of a view saved in the viewer -> regenerates it exactly
    (figure parameters passed here override it; `receta` is the old name). width: 1col (3.46 in),
    1.5col (5.2 in), 2col (7.1 in) or inches. bar: horizontal | vertical | none.
    label accepts mathtext ('$\\sigma_r$ (MPa)'); factor multiplies the bar values (1000: m→mm).
    scalebar (only with parallel=True): length bar; sb_factor = label units per model unit.
    view_aspect = height/width of the view (without recipe)."""
    from .figure import LINEWIDTH_PT, make_figure, width_inches
    from .scene import Scene
    recipe = recipe or receta
    # each figure option: the one passed explicitly; otherwise the recipe's; otherwise the default
    given = dict(bar=bar, label=label, factor=factor, nticks=nticks, shading=shading, scalebar=scalebar,
                 sb_factor=sb_factor, sb_unit=sb_unit)
    defaults = dict(bar="horizontal", label=None, factor=1.0, nticks=5, shading=False, scalebar=False,
                    sb_factor=1000.0, sb_unit="mm")
    prev, d = {}, None
    if recipe:
        with open(os.path.expanduser(recipe)) as f:
            d = json.load(f)
        path = path or d["med"]
        prev = d.get("figura", {})
        size = d.get("size", [1400, 700])
    elif not path:
        raise MedError("Missing path (or recipe)")
    else:
        size = [1400, int(1400 * float(view_aspect))]
    fig_kw = {k: (given[k] if given[k] is not None else prev.get(k, defaults[k])) for k in given}
    width_in = width_inches(width) if width else prev.get("width_in", 3.46)
    name = name or prev.get("name")
    res = _open(path, None if recipe else field, (d or {}).get("mesh") or mesh)
    with _VTK:
        sc = Scene(res, size=tuple(size))
        try:
            if recipe:
                sc.apply_settings(d)
            else:
                _configure(sc, res, field=field, component=component, time=time, step=step, groups=groups,
                           window=window, warp_scale=warp_scale, clip_mode=clip_mode, clip_origin=clip_origin,
                           clip_normal=clip_normal, threshold=threshold, view=view, zoom=zoom, parallel=parallel,
                           cmap=cmap, invert=invert, vmin=vmin, vmax=vmax, symmetric=symmetric, bands=bands,
                           edges=edges, hide_nan=hide_nan, axis_point=axis_point, axis_dir=axis_dir,
                           background="white", edge_color=edge_color, edge_width=edge_width,
                           show_nodes=show_nodes, node_color=node_color, node_size=node_size,
                           cell_reduce=cell_reduce)
            if not name:
                info = res.field(sc.field) if sc.field else None
                name = f"fig_{info.short}_{sc.comp}_{time_tag()}" if info else f"fig_mesh_{time_tag()}"
            r = make_figure(sc, out_dir(res.path, "figuras"), name, width_in=width_in, **fig_kw)
        finally:
            sc.rw.Finalize()
    with open(r["preview"], "rb") as f:
        data = f.read()
    txt = (f"PDF: {r['pdf']}\nPNG (600 dpi): {r['png']}\nRecipe: {r['receta']}\n"
           f"PDF width: {r['ancho_pt']:.0f} pt (column = {LINEWIDTH_PT:.0f} pt) -> {r['latex']}")
    if r["sin_proyeccion_paralela"]:
        txt += "\nNo scale bar: it needs parallel=True."
    return [txt, Image(data=data, format="png")]


def _port_open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


@tool
def med_view(path: str, field: str | None = None, component: str | None = None,
             open_browser: bool = True, lang: str | None = None, mesh: str | None = None) -> str:
    """Opens the interactive viewer (Aster View) for the user in the browser: field,
    component and time step, groups, deformed shape, cuts, axial window, colors, screenshots,
    paper figures. lang = es | en | fr (default: the language last chosen in the viewer).
    Returns the URL. If a viewer is already open for that file, reuses it."""
    res = open_med(path)  # check the file before launching anything
    old = _viewers.get(res.path)
    if old and old[0].poll() is None:
        if open_browser:
            webbrowser.open(old[1])
        return f"Viewer already open: {old[1]}"
    port = free_port()
    cmd = [sys.executable, "-m", "aster_view.viewer", res.path, "--port", str(port)]
    if field:
        cmd += ["--field", field]
    if component:
        cmd += ["--comp", component]
    if lang:
        cmd += ["--lang", lang]
    if mesh:
        cmd += ["--mesh", mesh]
    if not open_browser:
        cmd.append("--no-browser")
    log = open(os.path.join(out_dir(res.path), "viewer.log"), "w")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://localhost:{port}/"
    t0 = time.time()
    while time.time() - t0 < 90:
        if proc.poll() is not None:
            raise MedError(f"The viewer exited with an error; see {log.name}")
        if _port_open(port):
            _viewers[res.path] = (proc, url)
            return (f"Viewer open: {url}\n(it closes by itself 10 min after its tab is closed; "
                    f"log: {log.name})")
        time.sleep(0.4)
    return f"The viewer is slow to start; try {url} in a moment (log: {log.name})"


@tool
def med_to_vtu(path: str, fields: list[str] | None = None, steps: str = "last",
               out: str | None = None, max_gb: float = 3.0, mesh: str | None = None) -> str:
    """Converts to a .pvd + .vtu series that ParaView opens directly (useful when ParaView has
    no MED reader). fields: fields to export (default: all); steps: 'last', 'all' or
    comma-separated indices ('0,10,-1'). ELGA fields are exported as the cell mean.
    Refuses if the estimated output exceeds max_gb. With several meshes, one series per call (mesh=)."""
    import vtk
    from vtkmodules.util import numpy_support as ns
    from .scene import Scene
    res = _open(path, fields[0] if fields else None, mesh)
    infos = [res.field(f) for f in fields] if fields else list(res.fields.values())
    ref = max(infos, key=lambda f: len(f.steps))
    if steps == "all":
        times = [s.time for s in ref.steps]
    elif steps == "last":
        times = [ref.steps[-1].time]
    else:
        times = [ref.steps[int(i)].time for i in steps.split(",")]
    with _VTK:
        sc = Scene(res)
        sc.update()
        ug, cell_map, used, conns = sc._grid()
        sc.rw.Finalize()
    per_step = sum(res.mesh.n_nodes * len(f.components) * 8 if f.support == "NODE"
                   else ug.GetNumberOfCells() * len(f.components) * 8 for f in infos)
    est = (per_step + res.mesh.n_nodes * 24 + conn_bytes(conns)) * len(times) / 1e9
    if est > max_gb:
        raise MedError(f"Estimated output {est:.1f} GB > max_gb={max_gb}. Choose fewer time steps or fields.")
    od = out or os.path.join(out_dir(res.path), "vtu")
    os.makedirs(od, exist_ok=True)
    stem = os.path.splitext(os.path.basename(res.path))[0]
    if len(res.mesh_names) > 1:                 # one series per mesh, so that they do not overwrite each other
        stem += f"_{res.mesh_name}"
    entries = []
    for k, t in enumerate(times):
        g = vtk.vtkUnstructuredGrid()
        g.DeepCopy(ug)
        for d in (g.GetPointData(), g.GetCellData()):
            while d.GetNumberOfArrays():
                d.RemoveArray(0)
        for f in infos:
            fs = res.read(f.name, time=t)
            if fs.node is not None:
                arr = fs.node
                target = g.GetPointData()
            else:
                parts = [np.mean(fs.cells[ty][idx], axis=1) if ty in fs.cells
                         else np.full((len(idx), len(f.components)), np.nan) for ty, idx in cell_map]
                arr = np.concatenate(parts)
                target = g.GetCellData()
            va = ns.numpy_to_vtk(np.ascontiguousarray(arr, dtype=float), deep=True)
            va.SetName(f.short)
            for j, c in enumerate(f.components):
                va.SetComponentName(j, c)
            target.AddArray(va)
        fn = f"{stem}_{k:04d}.vtu"
        w = vtk.vtkXMLUnstructuredGridWriter()
        w.SetFileName(os.path.join(od, fn))
        w.SetInputData(g)
        w.SetDataModeToAppended()
        w.SetCompressorTypeToZLib()
        w.Write()
        entries.append(f'    <DataSet timestep="{t:.10g}" file="{fn}"/>')
    pvd = os.path.join(od, f"{stem}.pvd")
    with open(pvd, "w") as fh:
        fh.write('<?xml version="1.0"?>\n<VTKFile type="Collection" version="0.1">\n  <Collection>\n'
                 + "\n".join(entries) + "\n  </Collection>\n</VTKFile>\n")
    return (f"ParaView series: {pvd} ({len(times)} time steps, fields {[f.short for f in infos]}).\n"
            f"Open with: paraview {pvd}")


def conn_bytes(conns):
    return sum(c.size * 8 for c in conns)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
