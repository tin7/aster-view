"""Aster View: interactive viewer of MED results in the browser (trame).

Rendering is done on the server with VTK and only images reach the browser,
so it also works inside VSCode (Simple Browser) even if the
webview has no WebGL.

Mouse: drag = rotate; wheel = zoom towards the cursor; Shift+drag = pan;
Ctrl+drag = roll; right button drag = zoom.
Texts in Spanish, English or French (i18n.py); the language is chosen in the top bar.

Usage:  aster-view file.med [--field DEPL] [--comp DY] [--port N] [--no-browser] [--lang es|en|fr] [--mesh M]
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import socket
import sys
import time

import numpy as np

from .figure import BARS, WIDTHS, default_label, make_figure, preview_data_url, width_inches
from .i18n import LANGS, items, load_config, resolve_lang, save_config, tr, ui_table
from .medfile import MedError, open_med
from .scene import BACKGROUNDS, CELL_REDUCE, CLIP_MODES, COLORMAPS, REPRESENTATIONS, Scene


def output_root():
    """Output folder: $ASTER_VIEW_OUT, or "output_dir" in ~/.config/aster-view/config.json,
    or ~/aster_view_output. The .med files are never touched."""
    d = (os.environ.get("ASTER_VIEW_OUT") or os.environ.get("ASTER_MCP_OUT")
         or load_config().get("output_dir") or "~/aster_view_output")
    return os.path.expanduser(d)


def out_dir(med_path, sub=None):
    d = os.path.join(output_root(), os.path.splitext(os.path.basename(med_path))[0])
    if sub:
        d = os.path.join(d, sub)
    os.makedirs(d, exist_ok=True)
    return d


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _num(v, default):
    try:
        x = float(str(v).replace(",", "."))
        return x if np.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _vec(txt, default):
    try:
        v = [float(x) for x in str(txt).replace(";", ",").split(",")]
        return np.array(v, float) if len(v) == 3 else default
    except ValueError:
        return default


def _fmt3(v):
    return ", ".join(f"{x:.6g}" for x in np.asarray(v, float))


def build_app(med_path, field=None, comp=None, server=None, lang=None, mesh=None):
    from trame.app import get_server
    from trame.ui.vuetify3 import VAppLayout
    from trame.widgets import client, html
    from trame.widgets import vtk as vtkw
    from trame.widgets import vuetify3 as v3

    base = open_med(med_path)            # the whole file (it can hold several meshes)
    mesh_name = mesh or (base.field(field).mesh if field else base.mesh_name)
    res = base.view(mesh_name)           # the view from the mesh being shown
    field = res.label(res.field(field)) if field else None
    scene = Scene(res, offscreen=True)
    mesh = res.mesh
    ax = scene.axis
    lo, hi = mesh.bbox()
    s_lo, s_hi = float(lo @ ax.direction), float(hi @ ax.direction)

    server = server or get_server(client_type="vue3")
    state, ctrl = server.state, server.controller
    fields = scene.field_choices()
    f0 = field or scene.default_field()
    views_dir = out_dir(res.path, "vistas")

    def saved_views():
        return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(views_dir, "*.json")))

    lang = resolve_lang(lang)

    def mesh_rows():
        """Information tab: the mesh (the labels are keys of state.t)."""
        rows = [{"k": "info_file", "v": f"{os.path.basename(res.path)}  ({res.size / 1e6:.1f} MB)"},
                {"k": "mesh_lbl", "v": f"{res.mesh_name}  ({res.mesh.space_dim}D)"},
                {"k": "info_nodes", "v": f"{res.mesh.n_nodes:,}".replace(",", " ")}]
        rows += [{"k": "info_cells", "v": ", ".join(f"{t} {b.ne:,}".replace(",", " ") for t, b in res.mesh.blocks.items())}]
        a0, a1 = res.mesh.bbox()
        rows += [{"k": "info_bounds", "v": "  ".join(f"{c} [{a:.4g}, {b:.4g}]" for c, a, b in zip("xyz", a0, a1))}]
        return rows

    def field_rows():
        out = []
        for f in base.all_fields.values():
            t0, t1 = (f.steps[0].time, f.steps[-1].time) if f.steps else (np.nan, np.nan)
            out.append({"name": base.label(f), "sup": f.support, "nc": len(f.components), "ns": len(f.steps),
                        "t": f"{t0:g} – {t1:g}", "mesh": f.mesh})
        return out

    def mesh_items():
        """Meshes of the file (the selector only appears if there is more than one)."""
        if len(base.mesh_names) < 2:
            return []
        out = []
        for m in base.mesh_names:
            mm = base.mesh_of(m)
            nf = sum(f.mesh == m for f in base.all_fields.values())
            out.append({"title": f"{m}  ({mm.space_dim}D, {mm.n_nodes} N, {nf} f.)", "value": m})
        return out

    def choice_lists(lg):
        """Option lists with the label in language lg (the value is the fixed key)."""
        return {"t": ui_table(lg), "reduces": items(lg, "cell_reduce", CELL_REDUCE),
                "reps": items(lg, "representation", REPRESENTATIONS),
                "backgrounds": items(lg, "background", list(BACKGROUNDS) + ["custom"]),
                "clip_modes": items(lg, "clip_mode", list(CLIP_MODES)),
                "fig_widths": items(lg, "fig_width", list(WIDTHS)), "fig_bars": items(lg, "fig_bar", BARS),
                "bar_poss": items(lg, "bar_pos")}

    state.update({
        "lang": lang, "langs": [{"title": v, "value": k} for k, v in LANGS.items()], **choice_lists(lang),
        "fields": fields, "field": f0, "comps": [], "comp": comp,
        "nsteps": 1, "step": 0, "step_txt": "", "playing": False,
        "cell_reduce": "mean", "is_elga": False, "pg_txt": "",
        "side": True, "sel": "source", "tab": "props", "dark": load_config().get("theme") == "dark",
        "has_depl": scene.has_depl(), "time_txt": "", "pick_rows": [],
        "meshes": mesh_items(), "mesh_name": res.mesh_name,
        "mesh_rows": mesh_rows(), "field_rows": field_rows(),
        "click_mode": "rotar", "parallel": False,
        "auto_range": True, "rmin": "0", "rmax": "1", "symmetric": False,
        "cmaps": list(COLORMAPS), "cmap": "Cool to Warm", "invert": False, "bands": 0, "log": False,
        "show_bar": True, "bar_title": "", "bar_pos": "right",
        "group_items": scene.cell_group_choices(), "groups": [],
        "representation": "surface", "opacity": 1.0, "shading": True,
        "edge_color": scene.edge_color, "edge_width": scene.edge_width, "show_nodes": False,
        "node_color": scene.node_color, "node_size": scene.node_size,
        "hide_nan": False, "warp": False, "warp_scale": "1",
        "win_on": False, "win": [s_lo, s_hi], "s_lo": s_lo, "s_hi": s_hi, "s_step": (s_hi - s_lo) / 500 or 1e-6,
        "thr_on": False, "thr_min": "", "thr_max": "",
        "background": "dark_gradient" if load_config().get("theme") == "dark" else "light_gradient",
        "bg_custom": "#FFFFFF", "show_text": False, "show_triad": True,
        "clip_on": False, "clip_mode": "clip", "clip_invert": False,
        "context": True, "show_plane": False, "clip_o": _fmt3(scene.clip_origin), "clip_n": _fmt3(scene.clip_normal),
        "clip_s": 0.0, "clip_smin": 0.0, "clip_smax": 1.0, "clip_sstep": 0.001, "long_theta": 0,
        "picks_txt": [],
        "axis_pt": _fmt3(ax.point), "axis_dir": _fmt3(ax.direction),
        "fig_width": "1col", "fig_bar": "horizontal",
        "fig_label": "", "fig_factor": "1", "fig_nticks": 5, "fig_shading": False, "fig_scalebar": False,
        "fig_sb_factor": "1000", "fig_sb_unit": "mm", "fig_name": "", "fig_preview": "", "fig_msg": "",
        "views": saved_views(), "view_sel": None, "view_name": "",
        "info_txt": "", "msg": "", "error": "", "busy": False,
        "title": os.path.basename(res.path),
    })
    guard = {"sync": False}

    def sync(**kw):
        """Changes the page state without triggering the handlers again."""
        guard["sync"] = True
        try:
            with state:
                state.update(kw)
        finally:
            guard["sync"] = False

    def plane_sync():
        smin, smax, s = scene.plane_offset_range()
        sync(clip_o=_fmt3(scene.clip_origin), clip_n=_fmt3(scene.clip_normal),
             clip_smin=smin, clip_smax=smax, clip_s=s, clip_sstep=(smax - smin) / 1000 or 1e-6)

    def picks_sync():
        sync(pick_rows=[{"i": i + 1, "v": f"{p.get('valor', float('nan')):.6g}", "n": f"N{p.get('nodo', '?')}",
                         "x": _fmt3(p["x0"])} for i, p in enumerate(scene.picks)])

    def refresh_field_lists():
        if not state.field:
            return
        info = res.field(state.field)
        comps = scene.comp_choices(state.field)
        c = state.comp if state.comp in comps else comps[0]
        t_cur = scene.last_info.get("tiempo")
        st = info.step_index(time=t_cur) if t_cur is not None else len(info.steps) - 1
        sync(comps=comps, comp=c, nsteps=len(info.steps), step=st)

    def texts_sync():
        """Page lines from the last update(), in the current language."""
        info, lg = scene.last_info, state.lang
        if not state.field or "min" not in info:
            return
        st = res.field(state.field).steps[scene.step]
        elga = "reduccion" in info
        elno = info.get("soporte") == "ELNO"
        que = (tr(lg, "shown_elno" if elno else "shown_elga", r=items(lg, "cell_reduce", [info["reduccion"]])[0]["title"])
               if elga else tr(lg, "shown_nodal"))
        txt = tr(lg, "info", que=que, lo=f"{info['min']:.5g}", hi=f"{info['max']:.5g}", d=info["definidos"],
                 n=info["n"], s=info["soporte"])
        if info.get("celdas_ocultas"):
            txt += tr(lg, "hidden_cells", k=info["celdas_ocultas"])
        pg = (tr(lg, "elno_nodes" if elno else "gauss", lo=f"{info['pg_min']:.5g}", hi=f"{info['pg_max']:.5g}")
              if elga else "")
        sync(step_txt=tr(lg, "step_txt", i=int(state.step) + 1, n=state.nsteps, t=f"{st.time:g}"),
             info_txt=txt, is_elga=elga, pg_txt=pg, time_txt=f"{st.time:g}")

    @state.change("lang")
    def on_lang(lang, **_):
        if guard["sync"] or lang not in LANGS:
            return
        save_config(language=lang)          # the next viewer opens in this language
        sync(**choice_lists(lang))
        texts_sync()

    def switch_mesh(name):
        """Another mesh of the same file: fields, groups, axis and window start over."""
        nonlocal res, mesh, lo, hi, s_lo, s_hi
        res = base.view(name)
        scene.set_result(res)
        mesh = res.mesh
        lo, hi = mesh.bbox()
        d = scene.axis.direction
        s_lo, s_hi = float(lo @ d), float(hi @ d)
        fl = scene.field_choices()
        sync(mesh_name=name, fields=fl, field=scene.default_field(), comp=None,
             has_depl=scene.has_depl(), group_items=scene.cell_group_choices(), groups=[], warp=False, thr_on=False,
             clip_on=False, win_on=False, win=[s_lo, s_hi], s_lo=s_lo, s_hi=s_hi, s_step=(s_hi - s_lo) / 500 or 1e-6,
             axis_pt=_fmt3(scene.axis.point), axis_dir=_fmt3(d), mesh_rows=mesh_rows(), pick_rows=[],
             info_txt="", pg_txt="", is_elga=False)
        refresh_field_lists()
        apply()
        sync(parallel=mesh.space_dim == 2)
        scene.set_parallel(mesh.space_dim == 2)
        scene.set_view("iso")
        plane_sync()

    @state.change("mesh_name")
    def on_mesh(mesh_name, **_):
        if not guard["sync"] and mesh_name and mesh_name != res.mesh_name:
            switch_mesh(mesh_name)

    @state.change("dark")
    def on_dark(dark, **_):
        if guard["sync"]:
            return
        save_config(theme="dark" if dark else "light")
        # the view background follows the theme if it is still the default of the other theme
        if dark and state.background == "light_gradient":
            state.background = "dark_gradient"
        elif not dark and state.background == "dark_gradient":
            state.background = "light_gradient"

    def apply():
        try:
            scene.field = state.field
            scene.comp = state.comp
            scene.step = int(state.step)
            scene.groups = list(state.groups or [])
            scene.hide_nan = bool(state.hide_nan)
            scene.representation = state.representation
            scene.cell_reduce = state.cell_reduce
            scene.edge_color, scene.edge_width = state.edge_color, _num(state.edge_width, 1.0)
            scene.show_nodes, scene.node_color = bool(state.show_nodes), state.node_color
            scene.node_size = _num(state.node_size, 5.0)
            scene.opacity = float(state.opacity)
            scene.shading = bool(state.shading)
            scene.cmap, scene.invert, scene.log = state.cmap, bool(state.invert), bool(state.log)
            scene.bands = int(state.bands or 0)
            scene.symmetric = bool(state.symmetric)
            scene.range = None if state.auto_range else (_num(state.rmin, 0.0), _num(state.rmax, 1.0))
            scene.show_bar, scene.bar_title = bool(state.show_bar), (state.bar_title or None)
            scene.bar_pos = state.bar_pos
            scene.show_text, scene.show_triad = bool(state.show_text), bool(state.show_triad)
            scene.background = state.bg_custom if state.background == "custom" else state.background
            scene.warp_scale = _num(state.warp_scale, 1.0) if state.warp else 0.0
            scene.axis.point = _vec(state.axis_pt, scene.axis.point)
            d = _vec(state.axis_dir, scene.axis.direction)
            if np.linalg.norm(d) > 0:
                scene.axis.direction = d / np.linalg.norm(d)
            scene.window = tuple(float(x) for x in state.win) if state.win_on else None
            scene.threshold = ((_num(state.thr_min, -np.inf), _num(state.thr_max, np.inf))
                               if state.thr_on else None)
            scene.clip_mode = state.clip_mode if state.clip_on else None
            scene.clip_invert, scene.context = bool(state.clip_invert), bool(state.context)
            scene.show_plane = bool(state.show_plane)
            scene.update()
            if state.field:
                texts_sync()
                if state.auto_range:
                    sync(rmin=f"{scene.last_range[0]:.6g}", rmax=f"{scene.last_range[1]:.6g}")
                picks_sync()
            sync(error="")
        except MedError as e:
            sync(error=str(e))
        except Exception as e:  # so that an error does not bring the viewer down
            sync(error=f"{type(e).__name__}: {e}")
        ctrl.view_update()

    @state.change("field")
    def on_field(**_):
        if guard["sync"]:
            return
        refresh_field_lists()
        apply()

    @state.change("comp", "step", "groups", "hide_nan", "representation", "opacity", "shading", "cmap",
                  "invert", "log", "bands", "symmetric", "auto_range", "rmin", "rmax", "show_bar", "bar_title",
                  "background", "bg_custom", "show_text", "show_triad", "warp", "warp_scale", "axis_pt",
                  "axis_dir", "win_on", "win", "thr_on", "thr_min", "thr_max", "clip_on", "clip_mode", "clip_invert",
                  "context", "show_plane", "edge_color", "edge_width", "show_nodes", "node_color", "node_size",
                  "cell_reduce", "bar_pos")
    def on_change(**_):
        if not guard["sync"]:
            apply()

    @state.change("click_mode")
    def on_click_mode(click_mode, **_):
        scene.click_mode = click_mode

    @state.change("clip_s")
    def on_clip_s(clip_s, **_):
        if guard["sync"]:
            return
        scene.set_plane_offset(clip_s)
        sync(clip_o=_fmt3(scene.clip_origin))
        apply()

    @state.change("clip_o", "clip_n")
    def on_clip_txt(clip_o, clip_n, **_):
        if guard["sync"]:
            return
        scene.clip_origin = _vec(clip_o, scene.clip_origin)
        n = _vec(clip_n, scene.clip_normal)
        if np.linalg.norm(n) > 0:
            scene.clip_normal = n / np.linalg.norm(n)
        plane_sync()
        apply()

    def plane_preset(kind):
        val = None
        if kind == "transversal":
            # keep the axial coordinate of the current origin (with a z axis: its z)
            val = float(np.asarray(scene.clip_origin, float) @ scene.axis.direction)
        elif kind == "longitudinal":
            val = state.long_theta
        scene.plane_preset(kind, val)
        plane_sync()
        if not state.clip_on:
            sync(clip_on=True, clip_mode="slice" if kind == "transversal" else "clip")
        apply()

    # --- callbacks from the scene (click on the view, dragged plane)
    def on_scene_click(mode, hit):
        if mode == "valor":
            picks_sync()
        elif mode == "plano":
            plane_sync()
            if not state.clip_on:
                sync(clip_on=True, clip_mode="clip")
                apply()
        ctrl.view_update()

    def on_scene_plane(o, n):
        plane_sync()
        ctrl.view_update()

    def on_scene_bar():
        sync(bar_pos="custom")          # it was dragged with the mouse
        ctrl.view_update()

    scene.on_click = on_scene_click
    scene.on_plane = on_scene_plane
    scene.on_bar = on_scene_bar

    # --- camera
    def set_view(v):
        scene.set_view(v)
        ctrl.view_update()

    def zoom(f):
        scene.zoom(float(f))
        ctrl.view_update()

    # magnifier (zoom to box): the box is drawn in the browser (client-only
    # state) and on release it is sent to the server in page pixels
    state.update({"zb": [0, 0, 0, 0], "zb_on": False})
    state.client_only("zb", "zb_on")

    @server.trigger("zoom_box")
    def zoom_box(box, cw, ch):
        W, H = scene.rw.GetSize()
        sx, sy = W / max(float(cw), 1.0), H / max(float(ch), 1.0)
        x0, y0, x1, y1 = (float(v) for v in box)
        scene.zoom_box(x0 * sx, H - y0 * sy, x1 * sx, H - y1 * sy)
        sync(click_mode="rotar")        # as in ParaView: the magnifier is single-use
        scene.click_mode = "rotar"
        ctrl.view_update()

    def fit():
        scene.fit()
        ctrl.view_update()

    @state.change("parallel")
    def on_parallel(parallel, **_):
        scene.set_parallel(bool(parallel))
        ctrl.view_update()

    def clear_picks():
        scene.clear_picks()
        picks_sync()
        ctrl.view_update()

    def full_range():
        try:
            a, b = scene.range_all_steps()
            sync(auto_range=False, rmin=f"{a:.6g}", rmax=f"{b:.6g}", msg=tr(state.lang, "all_steps_done"))
            apply()
        except Exception as e:
            sync(error=str(e))

    # --- time steps
    def go(delta=None, to=None):
        n = state.nsteps
        state.step = int(to if to is not None else min(max(int(state.step) + delta, 0), n - 1))

    async def play_loop():
        while state.playing:
            await asyncio.sleep(0.6)
            with state:
                if int(state.step) >= state.nsteps - 1:
                    state.playing = False
                else:
                    state.step = int(state.step) + 1

    def toggle_play():
        state.playing = not state.playing
        if state.playing:
            if int(state.step) >= state.nsteps - 1:
                state.step = 0
            asyncio.ensure_future(play_loop())

    # --- screenshots, figures and saved views
    def tag():
        info = res.field(state.field) if state.field else None
        return f"{info.short}_{state.comp}_t{info.steps[int(state.step)].time:g}" if info else "malla"

    def save_png():
        path = os.path.join(out_dir(res.path), f"{tag()}_{time.strftime('%H%M%S')}.png")
        w, h = scene.rw.GetSize()
        scene.screenshot(path, (max(w, 1600), max(h, 1000)))
        scene.rw.SetSize(w, h)
        ctrl.view_update()
        sync(msg=tr(state.lang, "png_saved", p=path))

    def make_paper_figure():
        lg = state.lang
        sync(busy=True, fig_msg=tr(lg, "generating"))
        try:
            name = (state.fig_name or f"fig_{tag()}").strip().replace(" ", "_")
            r = make_figure(scene, out_dir(res.path, "figuras"), name, width_in=width_inches(state.fig_width),
                            bar=state.fig_bar, label=(state.fig_label if state.fig_label else None),
                            factor=_num(state.fig_factor, 1.0), nticks=int(state.fig_nticks or 5),
                            shading=bool(state.fig_shading), scalebar=bool(state.fig_scalebar),
                            sb_factor=_num(state.fig_sb_factor, 1000.0), sb_unit=state.fig_sb_unit or "")
            msg = tr(lg, "fig_done", pdf=r["pdf"], png=r["png"], rec=r["receta"], tex=r["latex"])
            if r["sin_proyeccion_paralela"]:
                msg += "\n" + tr(lg, "fig_no_sb")
            sync(fig_preview=preview_data_url(r["preview"]), fig_msg=msg)
        except Exception as e:
            sync(fig_msg=tr(lg, "error", e=f"{type(e).__name__}: {e}"))
        finally:
            sync(busy=False)
            ctrl.view_update()

    def save_view():
        name = (state.view_name or f"vista_{time.strftime('%H%M%S')}").strip().replace(" ", "_")
        with open(os.path.join(views_dir, name + ".json"), "w") as f:
            json.dump(scene.get_settings(), f, indent=1, ensure_ascii=False)
        sync(views=saved_views(), view_sel=name, msg=tr(state.lang, "view_saved", p=os.path.join(views_dir, name + ".json")))

    def load_view():
        if not state.view_sel:
            return
        with open(os.path.join(views_dir, state.view_sel + ".json")) as f:
            d = json.load(f)
        if d.get("mesh") in base.mesh_names and d["mesh"] != res.mesh_name:
            switch_mesh(d["mesh"])
        scene.apply_settings(d)
        bg = scene.background
        sync(field=res.label(res.field(scene.field)) if scene.field else None)
        refresh_field_lists()
        sync(comp=scene.comp, step=scene.step, groups=list(scene.groups), hide_nan=scene.hide_nan,
             representation=scene.representation, opacity=scene.opacity, shading=scene.shading,
             edge_color=scene.edge_color, edge_width=scene.edge_width, show_nodes=scene.show_nodes,
             node_color=scene.node_color, node_size=scene.node_size, cell_reduce=scene.cell_reduce,
             cmap=scene.cmap, invert=scene.invert, log=scene.log, bands=scene.bands, symmetric=scene.symmetric,
             auto_range=scene.range is None, show_bar=scene.show_bar, bar_title=scene.bar_title or "",
             bar_pos=scene.bar_pos,
             background=bg if bg in BACKGROUNDS else "custom", bg_custom=bg if bg not in BACKGROUNDS else "#FFFFFF",
             show_text=scene.show_text, show_triad=scene.show_triad,
             warp=bool(scene.warp_scale), warp_scale=f"{scene.warp_scale or 1:g}",
             win_on=scene.window is not None, win=list(scene.window) if scene.window else [s_lo, s_hi],
             thr_on=scene.threshold is not None,
             clip_on=scene.clip_mode is not None, clip_mode=scene.clip_mode or "clip",
             clip_invert=scene.clip_invert, context=scene.context,
             parallel=bool(d.get("camera", {}).get("parallel")),
             axis_pt=_fmt3(scene.axis.point), axis_dir=_fmt3(scene.axis.direction))
        if scene.range is not None:
            sync(rmin=f"{scene.range[0]:.6g}", rmax=f"{scene.range[1]:.6g}")
        plane_sync()
        apply()
        scene.camera_set(d["camera"])
        ctrl.view_update()
        sync(msg=tr(state.lang, "view_loaded", p=state.view_sel))

    for k, fn in dict(set_view=set_view, zoom=zoom, fit=fit, go=go, toggle_play=toggle_play, save_png=save_png,
                      clear_picks=clear_picks, full_range=full_range, plane_preset=plane_preset,
                      make_paper_figure=make_paper_figure, save_view=save_view, load_view=load_view).items():
        setattr(ctrl, k, fn)
    ctrl.view_update = lambda: None      # the real view is registered when the page is built

    refresh_field_lists()
    apply()
    if mesh.space_dim == 2:                 # flat model: front view, no perspective
        sync(parallel=True)
        scene.set_parallel(True)
    scene.set_view("iso")
    plane_sync()
    if state.comp:
        sync(fig_label=default_label(state.comp))
    state.trame__title = f"Aster View · {os.path.basename(res.path)}"

    @state.change("comp")
    def on_comp_label(comp, **_):
        sync(fig_label=default_label(comp))

    # ======================================================== page
    # ParaView-like layout: toolbars on top, pipeline + properties on the
    # left, view and status bar. The texts come from state.t (i18n.ui_table): when the
    # language changes they change by themselves. Colors come from the Vuetify theme (light/dark).
    dense = dict(density="compact", hide_details=True)
    fld = dict(variant="outlined", **dense)
    chk = dict(color="primary", **dense)

    def T(key):
        return (f"t.{key}",)

    def tbtn(icon, tip, **kw):
        """Toolbar button: small icon, no fill."""
        kw.setdefault("variant", "text")
        return v3.VBtn(icon=icon, size="small", density="comfortable", title=T(tip), **kw)

    def sep():
        html.Div(classes="av-sep")

    def sec(key):
        html.Div(f"{{{{ t.{key} }}}}", classes="av-sec")

    def row(key):
        """Property row: label on the left, control on the right (as in ParaView)."""
        r = html.Div(classes="av-row")
        with r:
            html.Label(f"{{{{ t.{key} }}}}")
        return r

    theme = {"defaultTheme": "light", "themes": {
        "light": {"colors": {"background": "#e6e8ec", "surface": "#f7f8fa", "primary": "#1f62d0",
                             "on-surface": "#1f2329", "on-background": "#1f2329"}},
        "dark": {"dark": True, "colors": {"background": "#15171b", "surface": "#22252b", "primary": "#5d9cff",
                                          "on-surface": "#e3e6eb", "on-background": "#e3e6eb"}}}}

    with VAppLayout(server, theme=("dark ? 'dark' : 'light'",), vuetify_config={"theme": theme}) as layout:
        client.Style(CSS)
        with html.Div(classes="av-root"):
            # ------------------------------------------------ header
            with html.Div(classes="av-head"):
                tbtn("mdi-dock-left", "tip_side", click="side = !side", classes="ml-n1")
                html.Span("Aster View", classes="av-brand")
                html.Span("{{ title }}", classes="av-file", title=("title",))
                v3.VSpacer()
                with v3.VMenu():
                    with html.Template(v_slot_activator="{ props }"):
                        v3.VBtn("{{ lang.toUpperCase() }}", v_bind="props", prepend_icon="mdi-translate",
                                size="small", variant="text", title=T("language"))
                    with v3.VList(density="compact"):
                        v3.VListItem(v_for="l in langs", key="l.value", title=("l.title",),
                                     click="lang = l.value", active=("lang === l.value",))
                tbtn(("dark ? 'mdi-weather-sunny' : 'mdi-weather-night'",), "tip_theme", click="dark = !dark")
            # ------------------------------------------------ toolbars
            with html.Div(classes="av-tools"):
                with html.Div(classes="av-group"):
                    v3.VIcon("mdi-palette-outline", size=16, classes="av-muted mx-1", title=T("tip_color_by"))
                    v3.VSelect(v_model=("field",), items=("fields",), **fld, style="width: 138px",
                               title=T("tip_color_by"))
                    v3.VSelect(v_model=("comp",), items=("comps",), **fld, style="width: 92px",
                               title=T("tip_color_by"))
                    v3.VSelect(v_if="is_elga", v_model=("cell_reduce",), items=("reduces",), **fld,
                               style="width: 118px", title=T("cell_reduce"))
                sep()
                with html.Div(classes="av-group"):
                    v3.VSelect(v_model=("representation",), items=("reps",), **fld, style="width: 168px",
                               title=T("tip_rep"))
                    tbtn("mdi-grid", "tip_edges",
                         click="representation = (representation === 'surface_edges' ? 'surface' : 'surface_edges')",
                         active=("representation === 'surface_edges'",))
                    tbtn("mdi-dots-grid", "tip_nodes", click="show_nodes = !show_nodes", active=("show_nodes",))
                sep()
                with html.Div(classes="av-group"):
                    v3.VSelect(v_model=("cmap",), items=("cmaps",), **fld, style="width: 150px", title=T("tip_cmap"))
                    tbtn("mdi-swap-vertical", "tip_invert", click="invert = !invert", active=("invert",))
                    tbtn("mdi-arrow-expand-horizontal", "tip_rescale", click="auto_range = true",
                         active=("auto_range",))
                    tbtn("mdi-clock-outline", "tip_all_steps", click=ctrl.full_range)
                    tbtn("mdi-gradient-vertical", "tip_bar", click="show_bar = !show_bar", active=("show_bar",))
                sep()
                with html.Div(classes="av-group"):
                    with v3.VBtnToggle(v_model=("click_mode",), mandatory=True, density="compact", divided=True,
                                       variant="outlined", color="primary", classes="av-modes"):
                        for val, icon, tip in (("rotar", "mdi-rotate-3d-variant", "tip_rotate"),
                                               ("mover", "mdi-hand-back-right-outline", "tip_pan"),
                                               ("valor", "mdi-eyedropper", "tip_probe"),
                                               ("centrar", "mdi-crosshairs-gps", "tip_center"),
                                               ("acercar", "mdi-selection-search", "tip_zoombox"),
                                               ("plano", "mdi-vector-square", "tip_plane")):
                            v3.VBtn(icon=icon, value=val, size="small", title=T(tip))
                sep()
                with html.Div(classes="av-group"):
                    tbtn("mdi-fit-to-screen-outline", "tip_fit", click=ctrl.fit)
                    for v in ("iso", "+x", "-x", "+y", "-y", "+z", "-z"):
                        v3.VBtn(v.upper() if v != "iso" else "iso", click=(ctrl.set_view, f"['{v}']"), size="small",
                                variant="text", density="comfortable", min_width=0, classes="av-axbtn")
                    tbtn(("parallel ? 'mdi-cube-outline' : 'mdi-cube-scan'",), "tip_parallel",
                         click="parallel = !parallel", active=("parallel",))
                    tbtn("mdi-magnify-plus-outline", "tip_zoom_in", click=(ctrl.zoom, "[1.5]"))
                    tbtn("mdi-magnify-minus-outline", "tip_zoom_out", click=(ctrl.zoom, "[0.67]"))
                    tbtn("mdi-camera-outline", "tip_png", click=ctrl.save_png)
                sep()
                with html.Div(classes="av-group av-time"):
                    tbtn("mdi-skip-previous", "tip_first", click=(ctrl.go, "[null, 0]"))
                    tbtn("mdi-chevron-left", "tip_prev", click=(ctrl.go, "[-1]"))
                    tbtn(("playing ? 'mdi-pause' : 'mdi-play'",), "tip_play", click=ctrl.toggle_play)
                    tbtn("mdi-chevron-right", "tip_next", click=(ctrl.go, "[1]"))
                    tbtn("mdi-skip-next", "tip_last", click=(ctrl.go, "[null, nsteps - 1]"))
                    html.Span("{{ t.time }}", classes="av-muted ml-1")
                    html.Span("{{ time_txt }}", classes="av-time-val")
                    html.Span("{{ Number(step) + 1 }} / {{ nsteps }}", classes="av-muted")
                    v3.VSlider(v_model=("step",), min=0, max=("nsteps - 1",), step=1, **dense, color="primary",
                               classes="av-tslider")
            # ------------------------------------------------ body
            with html.Div(classes="av-body"):
                with html.Div(v_show="side", classes="av-side"):
                    # pipeline
                    with html.Div(classes="av-pipe"):
                        html.Div("{{ t.pipeline }}", classes="av-pane-title")
                        with html.Div(classes=("'av-node' + (sel === 'source' ? ' av-sel' : '')",),
                                      click="sel = 'source'; tab = 'props'"):
                            html.I(classes="mdi mdi-database-outline av-ico")
                            html.Span("{{ title }}", classes="av-lbl")
                            html.Span("{{ mesh_name }}", v_if="meshes.length > 1", classes="av-detail")
                        for key, flag, icon, label, detail, cond in (
                                ("warp", "warp", "mdi-vector-curve", "f_warp", "'× ' + warp_scale", "has_depl"),
                                ("threshold", "thr_on", "mdi-filter-outline", "f_threshold",
                                 "(thr_min || '-∞') + ' … ' + (thr_max || '∞')", None),
                                ("clip", "clip_on", "mdi-box-cutter", "f_clip",
                                 "(clip_modes.find(c => c.value === clip_mode) || {}).title", None),
                                ("window", "win_on", "mdi-arrow-collapse-horizontal", "f_window",
                                 "win.map(x => Number(x).toPrecision(3)).join(' … ')", None)):
                            with html.Div(v_if=cond, classes=(
                                    f"'av-node av-child' + (sel === '{key}' ? ' av-sel' : '') + ({flag} ? '' : ' av-off')",),
                                    click=f"sel = '{key}'; tab = 'props'"):
                                html.I(classes=(f"'mdi av-eye ' + ({flag} ? 'mdi-eye' : 'mdi-eye-off-outline')",),
                                       click=f"{flag} = !{flag}; $event.stopPropagation()", title=T("tip_eye"))
                                html.I(classes=f"mdi {icon} av-ico")
                                html.Span(f"{{{{ t.{label} }}}}", classes="av-lbl")
                                html.Span(f"{{{{ {flag} ? {detail} : '' }}}}", classes="av-detail")
                    # tabs
                    with v3.VTabs(v_model=("tab",), density="compact", color="primary", classes="av-tabs",
                                  show_arrows=False):
                        for k in ("props", "info", "values", "fig"):
                            v3.VTab(f"{{{{ t.tab_{k} }}}}", value=k, classes="av-tab")
                    with html.Div(classes="av-props"):
                        # ---- file properties (source)
                        with html.Div(v_if="tab === 'props' && sel === 'source'"):
                            with html.Div(v_if="meshes.length > 1"):
                                sec("mesh_lbl")
                                with row("mesh_lbl"):
                                    v3.VSelect(v_model=("mesh_name",), items=("meshes",), **fld)
                            sec("sec_coloring")
                            with row("colormap"):
                                v3.VSelect(v_model=("cmap",), items=("cmaps",), **fld)
                            with row("bands"):
                                v3.VSelect(v_model=("bands",), items=("[0, 6, 8, 10, 12, 16, 20]",), **fld)
                            with row("range"):
                                with html.Div(classes="d-flex", style="gap: 4px"):
                                    v3.VTextField(v_model=("rmin",), disabled=("auto_range",), **fld)
                                    v3.VTextField(v_model=("rmax",), disabled=("auto_range",), **fld)
                            with row("auto_short"):
                                v3.VCheckbox(v_model=("auto_range",), **chk)
                            with row("symmetric"):
                                v3.VCheckbox(v_model=("symmetric",), **chk)
                            with row("log"):
                                v3.VCheckbox(v_model=("log",), **chk)
                            with row("invert"):
                                v3.VCheckbox(v_model=("invert",), **chk)
                            with row("color_bar"):
                                with html.Div(classes="d-flex align-center", style="gap: 4px"):
                                    v3.VCheckbox(v_model=("show_bar",), **chk, style="flex: 0 0 auto")
                                    v3.VTextField(v_model=("bar_title",), placeholder=T("bar_title"), **fld)
                            with row("bar_where"):
                                v3.VSelect(v_model=("bar_pos",), items=("bar_poss",), disabled=("!show_bar",),
                                           title=T("bar_drag_help"), **fld)
                            html.Div("{{ t.bar_drag_help }}", classes="av-help mb-1")
                            sec("sec_styling")
                            with row("representation"):
                                v3.VSelect(v_model=("representation",), items=("reps",), **fld)
                            with row("opacity"):
                                v3.VSlider(v_model=("opacity",), min=0.05, max=1, step=0.05, **dense, color="primary",
                                           thumb_label=True)
                            with row("shading"):
                                v3.VCheckbox(v_model=("shading",), **chk)
                            with row("edge_style"):
                                with html.Div(classes="d-flex align-center", style="gap: 6px"):
                                    html.Input(type="color", v_model=("edge_color",), classes="av-color",
                                               title=T("tip_edge_color"))
                                    v3.VSlider(v_model=("edge_width",), min=0.5, max=6, step=0.5, **dense,
                                               color="primary", thumb_label=True, title=T("tip_edge_width"))
                            with row("node_style"):
                                with html.Div(classes="d-flex align-center", style="gap: 6px"):
                                    v3.VCheckbox(v_model=("show_nodes",), **chk, style="flex: 0 0 auto",
                                                 title=T("tip_show_nodes"))
                                    html.Input(type="color", v_model=("node_color",), classes="av-color",
                                               title=T("tip_node_color"))
                                    v3.VSlider(v_model=("node_size",), min=1, max=20, step=1, **dense,
                                               color="primary", thumb_label=True, title=T("tip_node_size"))
                            sec("groups")
                            v3.VAutocomplete(v_model=("groups",), items=("group_items",), multiple=True, chips=True,
                                             closable_chips=True, clearable=True, **fld, classes="av-groups")
                            sec("sec_view")
                            with row("background"):
                                v3.VSelect(v_model=("background",), items=("backgrounds",), **fld)
                            v3.VColorPicker(v_if="background === 'custom'", v_model=("bg_custom",), mode="hex",
                                            modes=("['hex']",), canvas_height=80, width=300, elevation=0,
                                            classes="my-1")
                            with row("show_text"):
                                v3.VCheckbox(v_model=("show_text",), **chk)
                            with row("triad"):
                                v3.VCheckbox(v_model=("show_triad",), **chk)
                            sec("sec_saved")
                            with html.Div(classes="d-flex align-center", style="gap: 4px"):
                                v3.VTextField(v_model=("view_name",), placeholder=T("view_name"), **fld)
                                tbtn("mdi-content-save-outline", "tip_save_view", click=ctrl.save_view)
                            with html.Div(classes="d-flex align-center mt-1", style="gap: 4px"):
                                v3.VSelect(v_model=("view_sel",), items=("views",), placeholder=T("saved_views"),
                                           **fld)
                                tbtn("mdi-folder-open-outline", "tip_load_view", click=ctrl.load_view)
                            sec("p_axis")
                            with row("axis_point"):
                                v3.VTextField(v_model=("axis_pt",), **fld)
                            with row("axis_dir"):
                                v3.VTextField(v_model=("axis_dir",), **fld)
                        # ---- deformed shape
                        with html.Div(v_if="tab === 'props' && sel === 'warp'"):
                            sec("f_warp")
                            with row("enabled"):
                                v3.VCheckbox(v_model=("warp",), **chk)
                            with row("warp"):
                                with html.Div(classes="d-flex align-center", style="gap: 4px"):
                                    v3.VTextField(v_model=("warp_scale",), **fld)
                                    for f in ("1", "10", "100"):
                                        v3.VBtn(f"×{f}", click=f"warp_scale = '{f}'; warp = true", size="small",
                                                variant="tonal", density="comfortable", min_width=0)
                            html.Div("{{ t.warp_help }}", classes="av-help")
                        # ---- threshold
                        with html.Div(v_if="tab === 'props' && sel === 'threshold'"):
                            sec("f_threshold")
                            with row("enabled"):
                                v3.VCheckbox(v_model=("thr_on",), **chk)
                            with row("from"):
                                v3.VTextField(v_model=("thr_min",), **fld)
                            with row("to"):
                                v3.VTextField(v_model=("thr_max",), **fld)
                            with row("cells_wo_value"):
                                v3.VCheckbox(v_model=("hide_nan",), label=T("hide"), **chk)
                            html.Div("{{ t.thr_help }}", classes="av-help")
                        # ---- plane cut
                        with html.Div(v_if="tab === 'props' && sel === 'clip'"):
                            sec("f_clip")
                            with row("enabled"):
                                v3.VCheckbox(v_model=("clip_on",), **chk)
                            with row("mode"):
                                with html.Div(classes="d-flex align-center", style="gap: 4px"):
                                    v3.VSelect(v_model=("clip_mode",), items=("clip_modes",), **fld)
                                    tbtn("mdi-swap-horizontal", "tip_flip", click="clip_invert = !clip_invert",
                                         active=("clip_invert",))
                            with row("presets"):
                                with html.Div(classes="d-flex flex-wrap", style="gap: 3px"):
                                    for k in ("x", "y", "z"):
                                        v3.VBtn(k.upper(), click=(ctrl.plane_preset, f"['{k}']"), size="small",
                                                variant="tonal", density="comfortable", min_width=0,
                                                title=(f"t.normal_k.replace('{{k}}', '{k.upper()}')",))
                                    for k, lab, tip in (("transversal", "transverse", "tip_transverse"),
                                                        ("longitudinal", "longitudinal", "tip_longitudinal"),
                                                        ("camara", "camera", "tip_camera")):
                                        v3.VBtn(f"{{{{ t.{lab} }}}}", click=(ctrl.plane_preset, f"['{k}']"),
                                                size="small", variant="tonal", density="comfortable", title=T(tip))
                            with row("theta_short"):
                                v3.VSlider(v_model=("long_theta",), min=0, max=180, step=5, **dense, color="primary",
                                           thumb_label=True, end=(ctrl.plane_preset, "['longitudinal']"))
                            with row("pos_short"):
                                v3.VSlider(v_model=("clip_s",), min=("clip_smin",), max=("clip_smax",),
                                           step=("clip_sstep",), **dense, color="primary")
                            with row("origin"):
                                v3.VTextField(v_model=("clip_o",), **fld)
                            with row("normal"):
                                v3.VTextField(v_model=("clip_n",), **fld)
                            with row("draggable"):
                                v3.VCheckbox(v_model=("show_plane",), **chk)
                            with row("context"):
                                v3.VCheckbox(v_model=("context",), **chk)
                            html.Div("{{ t.plane_tip }}", classes="av-help")
                        # ---- axial window
                        with html.Div(v_if="tab === 'props' && sel === 'window'"):
                            sec("f_window")
                            with row("enabled"):
                                v3.VCheckbox(v_model=("win_on",), **chk)
                            v3.VRangeSlider(v_model=("win",), min=("s_lo",), max=("s_hi",), step=("s_step",),
                                            thumb_label="always", **dense, color="primary", classes="mt-7 mx-2")
                            html.Div("{{ t.win_help }}", classes="av-help")
                        # ---- information
                        with html.Div(v_if="tab === 'info'"):
                            sec("sec_shown")
                            html.Div("{{ step_txt }}", classes="av-help")
                            html.Div("{{ info_txt }}", classes="av-help")
                            html.Div("{{ pg_txt }}", v_if="is_elga", classes="av-help font-weight-medium")
                            sec("sec_mesh")
                            with html.Table(classes="av-table"):
                                with html.Tr(v_for="r in mesh_rows", key="r.k"):
                                    html.Td("{{ t[r.k] }}", classes="av-muted")
                                    html.Td("{{ r.v }}")
                            sec("sec_fields")
                            with html.Table(classes="av-table"):
                                with html.Tr():
                                    for k in ("col_field", "col_support", "col_comps", "col_steps", "time"):
                                        html.Th(f"{{{{ t.{k} }}}}")
                                    html.Th("{{ t.col_mesh }}", v_if="meshes.length > 1")
                                with html.Tr(v_for="f in field_rows", key="f.mesh + f.name"):
                                    for k in ("name", "sup", "nc", "ns", "t"):
                                        html.Td(f"{{{{ f.{k} }}}}")
                                    html.Td("{{ f.mesh }}", v_if="meshes.length > 1")
                        # ---- values at points
                        with html.Div(v_if="tab === 'values'"):
                            html.Div("{{ t.values_help }}", classes="av-help mb-2")
                            with html.Table(classes="av-table", v_if="pick_rows.length"):
                                with html.Tr():
                                    html.Th("#")
                                    html.Th("{{ comp }}")
                                    html.Th("{{ t.col_node }}")
                                    html.Th("x, y, z")
                                with html.Tr(v_for="p in pick_rows", key="p.i"):
                                    for k in ("i", "v", "n", "x"):
                                        html.Td(f"{{{{ p.{k} }}}}")
                            html.Div("{{ t.no_picks }}", v_else=True, classes="av-help")
                            v3.VBtn("{{ t.clear_points }}", click=ctrl.clear_picks, size="small", variant="tonal",
                                    prepend_icon="mdi-eraser", classes="mt-2")
                        # ---- journal figure
                        with html.Div(v_if="tab === 'fig'"):
                            html.Div("{{ t.fig_help }}", classes="av-help mb-1")
                            with row("width"):
                                v3.VSelect(v_model=("fig_width",), items=("fig_widths",), **fld)
                            with row("bar"):
                                v3.VSelect(v_model=("fig_bar",), items=("fig_bars",), **fld)
                            with row("ticks"):
                                v3.VSelect(v_model=("fig_nticks",), items=("[3, 4, 5, 6, 7]",), **fld)
                            with row("label_short"):
                                v3.VTextField(v_model=("fig_label",), title=T("bar_label"), **fld)
                            with row("factor_short"):
                                v3.VTextField(v_model=("fig_factor",), title=T("factor"), **fld)
                            with row("shading"):
                                v3.VCheckbox(v_model=("fig_shading",), **chk)
                            with row("scalebar"):
                                v3.VCheckbox(v_model=("fig_scalebar",), **chk)
                            with row("sb_short"):
                                with html.Div(classes="d-flex", style="gap: 4px"):
                                    v3.VTextField(v_model=("fig_sb_factor",), disabled=("!fig_scalebar",),
                                                  title=T("sb_factor"), **fld)
                                    v3.VTextField(v_model=("fig_sb_unit",), disabled=("!fig_scalebar",), **fld,
                                                  style="max-width: 64px")
                            with row("file_name"):
                                v3.VTextField(v_model=("fig_name",), **fld)
                            v3.VBtn("{{ t.make_figure }}", click=ctrl.make_paper_figure, loading=("busy",),
                                    color="primary", size="small", variant="flat", classes="mt-2",
                                    prepend_icon="mdi-file-pdf-box")
                            html.Img(v_if="fig_preview", src=("fig_preview",), classes="av-preview")
                            html.Pre("{{ fig_msg }}", classes="av-help", style="white-space: pre-wrap; word-break: break-all")
                # ---- view
                with html.Div(classes="av-view"):
                    view = vtkw.VtkRemoteView(scene.rw, interactive_ratio=1, interactive_quality=92)
                    ctrl.view_update = view.update
                    ctrl.view_reset_camera = view.reset_camera
                    # magnifier layer: only exists while the magnifier mode is on
                    with html.Div(
                            v_if="click_mode === 'acercar'",
                            style="position: absolute; inset: 0; cursor: crosshair; z-index: 5; user-select: none;",
                            mousedown="zb = [$event.offsetX, $event.offsetY, $event.offsetX, $event.offsetY]; "
                                      "zb_on = true",
                            mousemove="zb_on && (zb = [zb[0], zb[1], $event.offsetX, $event.offsetY])",
                            mouseup="zb_on && (zb_on = false, trigger('zoom_box', [zb, "
                                    "$event.currentTarget.clientWidth, $event.currentTarget.clientHeight]))",
                            mouseleave="zb_on = false"):
                        html.Div(v_if="zb_on", style=(
                            "`position:absolute; pointer-events:none; border:1.5px dashed #1f62d0; "
                            "background:rgba(31,98,208,0.12); left:${Math.min(zb[0], zb[2])}px; "
                            "top:${Math.min(zb[1], zb[3])}px; width:${Math.abs(zb[2] - zb[0])}px; "
                            "height:${Math.abs(zb[3] - zb[1])}px`",))
                        html.Div("{{ t.zoombox_hint }}", v_if="!zb_on", classes="av-hint")
            # ------------------------------------------------ status bar
            with html.Div(classes="av-status"):
                html.Span("{{ field }} · {{ comp }} · t = {{ time_txt }}", classes="av-status-key")
                html.Span("{{ info_txt }}", classes="av-status-txt", title=("info_txt",))
                html.Span("{{ pg_txt }}", v_if="is_elga", classes="av-status-txt font-weight-medium")
                v3.VSpacer()
                html.Span("{{ error }}", v_if="error", classes="av-status-err", title=("error",))
                html.Span("{{ msg }}", v_else_if="msg", classes="av-status-msg", title=("msg",))
    return server, scene


# page styles: compact, no capitals or shadows, theme colors
CSS = """
html, body { overflow: hidden !important; }
.av-root { position: fixed; inset: 0; display: flex; flex-direction: column; font-size: 12.5px;
  background: rgb(var(--v-theme-background)); color: rgb(var(--v-theme-on-background)); }
.av-root, .av-root .v-field, .av-root .v-list-item-title, .av-root .v-label { font-size: 12.5px; }
.av-line { border-color: rgba(var(--v-border-color), 0.16); }
.av-head { display: flex; align-items: center; gap: 8px; height: 34px; padding: 0 8px; flex: 0 0 auto;
  background: rgb(var(--v-theme-surface)); border-bottom: 1px solid rgba(var(--v-border-color), 0.14); }
.av-brand { font-weight: 600; letter-spacing: .2px; }
.av-file { opacity: .65; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.av-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 3px 4px; padding: 3px 6px; flex: 0 0 auto;
  background: rgb(var(--v-theme-surface)); border-bottom: 1px solid rgba(var(--v-border-color), 0.14); }
.av-group { display: flex; align-items: center; gap: 2px; }
.av-sep { width: 1px; align-self: stretch; margin: 3px 4px; background: rgba(var(--v-border-color), 0.16); }
.av-muted { opacity: .62; }
.av-time-val { font-variant-numeric: tabular-nums; min-width: 40px; font-weight: 600; }
.av-tslider { width: 130px; flex: 0 0 130px; margin: 0 6px; }
.av-axbtn { font-size: 11.5px !important; padding: 0 5px !important; font-variant-numeric: tabular-nums; }
.av-modes { height: 28px !important; }
.av-modes .v-btn { height: 28px !important; min-width: 30px !important; padding: 0 6px !important; }
.av-body { flex: 1 1 auto; display: flex; min-height: 0; }
.av-side { width: 340px; flex: 0 0 340px; display: flex; flex-direction: column; min-height: 0;
  background: rgb(var(--v-theme-surface)); border-right: 1px solid rgba(var(--v-border-color), 0.14); }
.av-pipe { padding: 4px 0 6px; border-bottom: 1px solid rgba(var(--v-border-color), 0.14); }
.av-pane-title { font-weight: 600; font-size: 11.5px; opacity: .7; padding: 2px 10px 4px; }
.av-node { display: flex; align-items: center; gap: 6px; height: 24px; padding: 0 10px; cursor: pointer;
  white-space: nowrap; }
.av-node:hover { background: rgba(var(--v-theme-on-surface), 0.05); }
.av-node.av-sel { background: rgba(var(--v-theme-primary), 0.16); }
.av-child { padding-left: 22px; }
.av-node.av-off .av-lbl, .av-node.av-off .av-ico { opacity: .45; }
.av-ico { font-size: 16px; opacity: .8; }
.av-eye { font-size: 16px; opacity: .75; cursor: pointer; }
.av-eye:hover { opacity: 1; color: rgb(var(--v-theme-primary)); }
.av-lbl { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; }
.av-detail { opacity: .55; font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; max-width: 120px; }
.av-tabs { flex: 0 0 auto; border-bottom: 1px solid rgba(var(--v-border-color), 0.14); }
.av-tabs .v-tab { text-transform: none !important; letter-spacing: 0 !important; font-size: 12.5px !important;
  min-width: 0 !important; padding: 0 10px !important; }
.av-props { flex: 1 1 auto; overflow-y: auto; overflow-x: hidden; padding: 4px 10px 14px; }
.av-row > *, .av-row .d-flex > * { min-width: 0; }
.av-sec { font-weight: 600; font-size: 11.5px; margin: 12px 0 4px; padding-bottom: 3px;
  border-bottom: 1px solid rgba(var(--v-border-color), 0.14); opacity: .85; }
.av-row { display: grid; grid-template-columns: 112px minmax(0, 1fr); align-items: center; gap: 6px;
  min-height: 30px; }
.av-row > label { opacity: .72; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.av-help { font-size: 11.5px; opacity: .7; margin-top: 6px; line-height: 1.35; }
.av-table { width: 100%; border-collapse: collapse; font-size: 11.5px; font-variant-numeric: tabular-nums; }
.av-table th { text-align: left; font-weight: 600; opacity: .7; padding: 2px 4px;
  border-bottom: 1px solid rgba(var(--v-border-color), 0.14); }
.av-table td { padding: 2px 4px; border-bottom: 1px solid rgba(var(--v-border-color), 0.07); vertical-align: top; }
.av-preview { width: 100%; margin-top: 8px; background: white; border: 1px solid rgba(var(--v-border-color), 0.2); }
.av-color { width: 30px; height: 22px; border: 1px solid rgba(var(--v-border-color), 0.3); border-radius: 3px;
  padding: 0; background: none; cursor: pointer; flex: 0 0 auto; }
.av-view { flex: 1 1 auto; position: relative; min-width: 0; }
.av-hint { position: absolute; top: 8px; left: 50%; transform: translateX(-50%); background: rgba(0, 0, 0, .62);
  color: white; padding: 3px 10px; border-radius: 3px; font-size: 12px; pointer-events: none; }
.av-status { flex: 0 0 auto; height: 24px; display: flex; align-items: center; gap: 14px; padding: 0 10px;
  font-size: 11.5px; white-space: nowrap; overflow: hidden; background: rgb(var(--v-theme-surface));
  border-top: 1px solid rgba(var(--v-border-color), 0.14); }
.av-status-key { font-weight: 600; }
.av-status-txt { opacity: .75; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.av-status-msg { color: rgb(var(--v-theme-success)); overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.av-status-err { color: rgb(var(--v-theme-error)); overflow: hidden; text-overflow: ellipsis; min-width: 0; }
/* more compact Vuetify: no capitals, no shadows, 28 px fields */
.av-root .v-btn { text-transform: none; letter-spacing: 0; box-shadow: none !important; }
.av-root .v-btn--active { color: rgb(var(--v-theme-primary)); }
.av-root .v-field { --v-input-control-height: 28px; --v-field-padding-start: 8px; --v-field-padding-end: 4px; }
.av-root .v-field__input { min-height: 28px !important; padding-top: 2px !important; padding-bottom: 2px !important; }
.av-root .v-field__append-inner, .av-root .v-field__clearable { padding-top: 2px !important; align-items: center; }
.av-root .v-field--variant-outlined .v-field__outline { --v-field-border-opacity: 0.22; }
.av-root .v-select__selection-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.av-root .v-selection-control { min-height: 26px; }
.av-root .v-selection-control__wrapper { height: 26px; width: 26px; }
.av-root .v-slider.v-input--horizontal { margin-inline: 4px; }
.av-root .v-slider-thumb { --v-slider-thumb-size: 13px !important; }
.av-root .v-slider-track { --v-slider-track-size: 3px !important; }
.av-groups .v-chip { height: 20px !important; font-size: 11.5px !important; }
"""


def main(argv=None):
    p = argparse.ArgumentParser(prog="aster-view", description="Interactive viewer for code_aster MED results")
    p.add_argument("med", help="result file (.med, .rmed)")
    p.add_argument("--field", "--campo", dest="field", help="field to show first (e.g. DEPL, SIEF_ELGA)")
    p.add_argument("--comp", "--component", dest="comp", help="component (e.g. DY, SIRR)")
    p.add_argument("--port", "--puerto", dest="port", type=int, default=0, help="port (default: a free one)")
    p.add_argument("--no-browser", "--sin-navegador", dest="no_browser", action="store_true",
                   help="do not open a browser (just print the URL)")
    p.add_argument("--mesh", "--malla", dest="mesh",
                   help="mesh to show first, for files with several meshes (default: the first one with fields)")
    p.add_argument("--lang", "--idioma", dest="lang", choices=list(LANGS),
                   help="language of the page (default: the last one chosen in the viewer)")
    p.add_argument("--timeout", type=int, default=600,
                   help="seconds without any connected browser before exiting (0 = never)")
    a = p.parse_args(argv)
    try:
        server, _ = build_app(a.med, a.field, a.comp, lang=a.lang, mesh=a.mesh)
    except MedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    port = a.port or free_port()
    print(f"ASTER_VIEW_URL http://localhost:{port}/", flush=True)
    server.start(port=port, open_browser=not a.no_browser, timeout=a.timeout,
                 show_connection_info=False)


if __name__ == "__main__":
    main()
