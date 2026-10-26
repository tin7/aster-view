"""Componentes derivadas y estadísticas sobre un instante de campo.

Componentes cilíndricas respecto de un eje (punto + dirección):
  vector DX,DY,DZ        -> DR, DT, DA  (radial, circunferencial, axial)
  tensor <P>XX..<P>YZ    -> <P>RR, <P>TT, <P>AA, <P>RT, <P>RA, <P>TA
                            (p. ej. SIRR = sigma_r, SITT = sigma_theta)
La dirección radial se calcula con las coordenadas SIN deformar de cada punto
(nodo o punto de Gauss). En code_aster los cortes XY, XZ, YZ del tensor son
componentes tensoriales (no las ingenieriles gamma), así que la rotación es directa.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .medfile import MedError

TENSOR = ("XX", "YY", "ZZ", "XY", "XZ", "YZ")
TENSOR_2D = ("XX", "YY", "ZZ", "XY")          # modelos 2D (D_PLAN, C_PLAN, AXIS): XZ = YZ = 0
CYL_T = ("RR", "TT", "AA", "RT", "RA", "TA")
CYL_V = ("DR", "DT", "DA")


def _circle_center(q, start, iters=30):
    """Centro del círculo que mejor ajusta los puntos 2D q (distancia geométrica, Gauss-Newton
    desde start). Con un tubo de pared gruesa los nodos están en círculos concéntricos y el
    centro sale bien aunque sea un arco parcial (el ajuste algebraico se corre hacia el arco).
    None si los puntos no forman un anillo (dispersión del radio > 20 % del radio medio) o si
    el círculo es mucho más grande que la pieza (una placa plana "encaja" en un círculo enorme)."""
    if len(q) < 10:
        return None
    c = np.asarray(start, float).copy()
    for _ in range(iters):
        v = q - c
        r = np.linalg.norm(v, axis=1)
        if np.any(r == 0):
            return None
        J = np.column_stack([-v / r[:, None], -np.ones(len(q))])
        R = r.mean()
        step = np.linalg.lstsq(J, -(r - R), rcond=None)[0]
        c = c + step[:2]
        if np.linalg.norm(step[:2]) < 1e-12 * (1 + R):
            break
    r = np.linalg.norm(q - c, axis=1)
    half_diag = np.linalg.norm(q.max(axis=0) - q.min(axis=0)) / 2
    ok = 0 < r.mean() < 5 * half_diag and r.std() < 0.2 * r.mean()
    c[np.abs(c) < 1e-9 * half_diag] = 0.0         # restos de redondeo (2e-12 en vez de 0)
    return c if ok else None


@dataclass
class Axis:
    point: np.ndarray
    direction: np.ndarray

    @classmethod
    def auto(cls, mesh):
        """Eje por defecto: la dirección más larga de la caja. Pasa por el centro de los
        círculos que forman los nodos en el plano transversal si encajan bien (tubo entero,
        medio tubo o un cuarto con simetrías); si no, por el centro de la caja."""
        lo, hi = mesh.bbox()
        k = int(np.argmax(hi - lo))
        d = np.zeros(3)
        d[k] = 1.0
        c = (lo + hi) / 2
        q = np.delete(np.asarray(mesh.coords, float), k, axis=1)
        o = _circle_center(q, c[np.arange(3) != k])
        if o is not None:
            c[np.arange(3) != k] = o
        return cls(c, d)

    @classmethod
    def make(cls, mesh, point=None, direction=None):
        a = cls.auto(mesh)
        if point is not None:
            a.point = np.asarray(point, float)
        if direction is not None:
            d = np.asarray(direction, float)
            if np.linalg.norm(d) == 0:
                raise MedError("The axis direction cannot be zero")
            a.direction = d / np.linalg.norm(d)
        return a

    def describe(self):
        p = ", ".join(f"{v:.6g}" for v in self.point)
        d = ", ".join(f"{v:.6g}" for v in self.direction)
        return f"axis through ({p}), direction ({d})"


def tensor_prefixes(comps):
    """Prefijos de tensores simétricos completos: 6 componentes, o las 4 de un modelo 2D."""
    cands = {c[:-2] for c in comps if len(c) > 2}
    return sorted(p for p in cands if all(p + s in comps for s in TENSOR_2D))


def has_vector(comps):
    return "DX" in comps and "DY" in comps


def derived_names(comps, dim=3):
    """Componentes que se pueden calcular. En una malla 2D no se ofrecen las cilíndricas:
    en axisimétrico las componentes ya son r, z, θ (SIXX = σ_r, SIYY = σ_z, SIZZ = σ_θ)."""
    out = []
    if has_vector(comps):
        out += ["NORM"] + (list(CYL_V) if dim == 3 else [])
    for p in tensor_prefixes(comps):
        if dim == 3:
            out += [p + s for s in CYL_T]
        if p == "SI":
            out += ["VMIS", "TRACE"]
    return out


def needs_axis(comp):
    return comp in CYL_V or (len(comp) > 2 and comp[-2:] in CYL_T)


def _frame(pos, axis):
    a = axis.direction
    d = pos - axis.point
    d = d - (d @ a)[..., None] * a
    r = np.linalg.norm(d, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        er = np.where(r > 1e-14, d / r, np.nan)
    et = np.cross(np.broadcast_to(a, er.shape), er)
    ea = np.broadcast_to(a, er.shape)
    return {"R": er, "T": et, "A": ea}


def _compute(arr, comps, comp, pos, axis):
    if comp in comps:
        return arr[..., comps.index(comp)]
    if comp == "NORM" and has_vector(comps):
        idx = [comps.index(c) for c in ("DX", "DY", "DZ") if c in comps]
        return np.sqrt(np.sum(arr[..., idx] ** 2, axis=-1))
    if comp in CYL_V and has_vector(comps):
        U = np.stack([arr[..., comps.index(c)] if c in comps else np.zeros(arr.shape[:-1])
                      for c in ("DX", "DY", "DZ")], axis=-1)
        e = _frame(pos, axis)[comp[1]]
        return np.einsum("...i,...i->...", U, e)
    p = None
    if comp in ("VMIS", "TRACE") and "SI" in tensor_prefixes(comps):
        p = "SI"
    elif len(comp) > 2 and comp[-2:] in CYL_T and comp[:-2] in tensor_prefixes(comps):
        p = comp[:-2]
    if p is None:
        raise MedError(f"Component '{comp}' not available. Options: {comps + derived_names(comps)}")
    zero = np.zeros(arr.shape[:-1])
    g = lambda s: arr[..., comps.index(p + s)] if p + s in comps else zero     # 2D: XZ = YZ = 0
    xx, yy, zz, xy, xz, yz = (g(s) for s in TENSOR)
    T = np.stack([np.stack([xx, xy, xz], -1), np.stack([xy, yy, yz], -1),
                  np.stack([xz, yz, zz], -1)], -2)
    if comp == "TRACE":
        return xx + yy + zz
    if comp == "VMIS":
        s = T - (xx + yy + zz)[..., None, None] / 3 * np.eye(3)
        return np.sqrt(1.5 * np.sum(s * s, axis=(-1, -2)))
    e = _frame(pos, axis)
    a, b = comp[-2], comp[-1]
    return np.einsum("...i,...ij,...j->...", e[a], T, e[b])


def evaluate(res, fs, comp, axis=None):
    """Valores de una componente (cruda o derivada) con la misma forma que el
    campo: (N,) en nodos, o {tipo: (ne, nga)} en celdas."""
    comps = fs.info.components
    mesh = res.mesh_of(fs.info.mesh)
    cyl = needs_axis(comp)
    if cyl and axis is None:
        axis = Axis.auto(mesh)
    if fs.node is not None:
        return _compute(fs.node, comps, comp, mesh.coords if cyl else None, axis)
    out = {}
    for t, v in fs.cells.items():
        pos = None
        if cyl:
            pos = support_xyz(res, fs, t)
        out[t] = _compute(v, comps, comp, pos, axis)
    return out


def support_xyz(res, fs, mtype):
    """Coordenadas (ne, nga, 3) de los puntos donde vive el campo en celdas."""
    nga = fs.cells[mtype].shape[1]
    mesh = res.mesh_of(fs.info.mesh)
    b = mesh.blocks[mtype]
    if fs.info.support == "ELNO" and nga == b.conn.shape[1]:
        return mesh.coords[b.conn]
    return res.gauss_xyz(mtype, fs.loc.get(mtype, ""), nga, mesh)


def flatten(res, fs, vals, group=None):
    """Aplana valores para estadística: (v, xyz, etiquetas). Etiquetas =
    ("nodo", ids 1-based, None), ("celda", número global de celda, punto de Gauss 1-based)
    o, en un campo ELNO, ("elno", número global de celda, número de nodo 1-based)."""
    mesh = res.mesh_of(fs.info.mesh)
    if fs.node is not None:
        idx = np.arange(mesh.n_nodes) if group is None else mesh.group_nodes(group)
        return vals[idx], mesh.coords[idx], ("nodo", idx + 1, None)
    sel = {t: np.arange(v.shape[0]) for t, v in vals.items()} if group is None else mesh.group_cells(group)
    vs, xs, ids, gps = [], [], [], []
    for t, idx in sel.items():
        if t not in vals:
            continue
        v = vals[t][idx]
        nga = v.shape[1]
        vs.append(v.ravel())
        xs.append(support_xyz(res, fs, t)[idx].reshape(-1, 3))
        ids.append(np.repeat(mesh.blocks[t].num[idx], nga))
        elno = fs.info.support == "ELNO" and nga == mesh.blocks[t].conn.shape[1]
        gps.append(mesh.blocks[t].conn[idx].ravel() + 1 if elno else np.tile(np.arange(1, nga + 1), len(idx)))
    if not vs:
        raise MedError("The field has no values on that group")
    kind = "elno" if fs.info.support == "ELNO" else "celda"
    return np.concatenate(vs), np.concatenate(xs), (kind, np.concatenate(ids), np.concatenate(gps))


def label(labels, i):
    kind, ids, gps = labels
    if kind == "nodo":
        return f"node N{ids[i]}"
    if kind == "elno":
        return f"node N{gps[i]} of cell M{ids[i]}"
    return f"cell M{ids[i]}, Gauss point {gps[i]}"


def stats(v):
    ok = np.isfinite(v)
    n = int(ok.sum())
    if n == 0:
        return {"n": len(v), "definidos": 0}
    w = v[ok]
    q = np.percentile(w, [5, 50, 95])
    return {"n": len(v), "definidos": n, "min": float(w.min()), "max": float(w.max()),
            "media": float(w.mean()), "desvio": float(w.std()),
            "p05": float(q[0]), "p50": float(q[1]), "p95": float(q[2]),
            "imin": int(np.flatnonzero(ok)[np.argmin(w)]), "imax": int(np.flatnonzero(ok)[np.argmax(w)])}
