"""Reads code_aster MED results with h5py (no MEDCoupling).

Format conventions, checked against real code_aster 17.4 files:
- coordinates, connectivities and values in NON-interlaced mode:
  x1..xN, y1..yN, z1..zN; in a field, component by component and, within
  each one, entity by entity and Gauss point by Gauss point;
- a field with a profile only holds values for the entities of
  /PROFILS/<pfl>/PFL (1-based indices within the type). Outside the profile
  we return NaN: never index by id (with a profile, the index is not the node number);
- the global cell number (code_aster's M<n>) is NUM, not the order of the
  types in the HDF5 (which is alphabetical);
- an ELNO field comes in the entity NOE.<type> (one value per node of each cell, in
  connectivity order);
- a file can hold several meshes (/ENS_MAA/<name>, code_aster calls them
  00000001, 00000002...) and each field names its own (attribute MAI). MedResult.view(mesh)
  gives the file seen from a single mesh: its fields and its geometry.
"""
from __future__ import annotations

import copy
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

import h5py
import numpy as np

NO_PROFILE = "MED_NO_PROFILE_INTERNAL"

# MED type -> (VTK cell type, dimension, nodes the VTK cell uses)
# H27/QU9/P18/TR7 are drawn as their serendipity version (the face/centre
# nodes are dropped): the corner + edge topology is the same.
MED_TYPES = {
    "PO1": (1, 0, 1), "SE2": (3, 1, 2), "SE3": (21, 1, 3),
    "TR3": (5, 2, 3), "TR6": (22, 2, 6), "TR7": (22, 2, 6),
    "QU4": (9, 2, 4), "QU8": (23, 2, 8), "QU9": (23, 2, 8),
    "TE4": (10, 3, 4), "T10": (24, 3, 10),
    "PY5": (14, 3, 5), "P13": (27, 3, 13),
    "PE6": (13, 3, 6), "P15": (26, 3, 15), "P18": (26, 3, 15),
    "HE8": (12, 3, 8), "H20": (25, 3, 20), "H27": (25, 3, 20),
}

# Exponents of the polynomial basis of each reference element. With them the
# shape functions are built from the reference coordinates stored in
# the file itself (/GAUSS/<loc>/COO), so the node order is always
# the file's and there are no permutation tables that could be wrong.
def _exps(mtype):
    r01, r012 = (0, 1), (0, 1, 2)
    if mtype == "HE8":
        return [(i, j, k) for i in r01 for j in r01 for k in r01]
    if mtype == "H20":
        return [(i, j, k) for i in r012 for j in r012 for k in r012 if (i, j, k).count(2) <= 1]
    if mtype == "H27":
        return [(i, j, k) for i in r012 for j in r012 for k in r012]
    if mtype == "TE4":
        return [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    if mtype == "T10":
        return [(i, j, k) for i in r012 for j in r012 for k in r012 if i + j + k <= 2]
    if mtype == "PE6":
        return [(i, j, k) for k in r01 for (i, j) in [(0, 0), (1, 0), (0, 1)]]
    if mtype == "P15":
        tri2 = [(0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2)]
        return ([(i, j, k) for k in r01 for (i, j) in tri2]
                + [(i, j, 2) for (i, j) in [(0, 0), (1, 0), (0, 1)]])
    if mtype == "P18":
        tri2 = [(0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2)]
        return [(i, j, k) for k in r012 for (i, j) in tri2]
    if mtype == "QU4":
        return [(i, j) for i in r01 for j in r01]
    if mtype == "QU8":
        return [(i, j) for i in r012 for j in r012 if (i, j).count(2) <= 1]
    if mtype == "QU9":
        return [(i, j) for i in r012 for j in r012]
    if mtype == "TR3":
        return [(0, 0), (1, 0), (0, 1)]
    if mtype == "TR6":
        return [(0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2)]
    if mtype == "SE2":
        return [(0,), (1,)]
    if mtype == "SE3":
        return [(0,), (1,), (2,)]
    return None  # PY5, P13, TR7: no simple polynomial basis -> centroid


class MedError(Exception):
    """Error with a message for the user."""


def _s(v):
    return v.decode("latin-1") if isinstance(v, (bytes, np.bytes_)) else str(v)


def _split16(s, n):
    s = _s(s)
    return [s[16 * i:16 * (i + 1)].strip() for i in range(int(n))]


def _names80(arr):
    out = []
    for row in np.atleast_2d(arr):
        b = np.asarray(row).astype(np.uint8).tobytes().split(b"\0")[0]
        out.append(b.decode("latin-1").strip())
    return out


@dataclass
class Block:
    mtype: str
    conn: np.ndarray     # (ne, nn) 0-based node indices, MED order
    fam: np.ndarray      # (ne,)
    num: np.ndarray      # (ne,) code_aster global 1-based numbering

    @property
    def ne(self):
        return len(self.fam)

    @property
    def dim(self):
        return MED_TYPES.get(self.mtype, (0, -1, 0))[1]


@dataclass
class Mesh:
    name: str
    coords: np.ndarray                          # (N, 3); in 2D, z = 0
    node_fam: np.ndarray                        # (N,)
    blocks: "OrderedDict[str, Block]"           # in global numbering order
    node_groups: dict = field(default_factory=dict)   # name -> node idx
    cell_groups: dict = field(default_factory=dict)   # name -> {type: idx}
    space_dim: int = 3                          # space dimension of the mesh (2 or 3)

    @property
    def n_nodes(self):
        return len(self.coords)

    @property
    def max_dim(self):
        return max((b.dim for b in self.blocks.values()), default=0)

    def group_dim(self, name):
        cg = self.cell_groups.get(name)
        if not cg:
            return 0
        return max(self.blocks[t].dim for t in cg)

    def group_nodes(self, name):
        """Nodes of a group: a node group, or the nodes of the cells of the group."""
        if name in self.node_groups:
            return self.node_groups[name]
        if name in self.cell_groups:
            parts = [np.unique(self.blocks[t].conn[idx]) for t, idx in self.cell_groups[name].items()]
            return np.unique(np.concatenate(parts)) if parts else np.zeros(0, int)
        raise MedError(f"No group '{name}'. Groups: {self.group_names()}")

    def group_cells(self, name):
        if name in self.cell_groups:
            return self.cell_groups[name]
        if name in self.node_groups:
            raise MedError(f"'{name}' is a NODE group and this field lives on cells: "
                           "use a cell group.")
        raise MedError(f"No group '{name}'. Groups: {self.group_names()}")

    def group_names(self):
        return sorted(set(self.node_groups) | set(self.cell_groups))

    def centroids(self, mtype):
        b = self.blocks[mtype]
        nn = MED_TYPES.get(mtype, (0, 0, b.conn.shape[1]))[2]
        return self.coords[b.conn[:, :nn]].mean(axis=1)

    def bbox(self):
        return self.coords.min(axis=0), self.coords.max(axis=0)


@dataclass
class StepInfo:
    key: str
    ndt: int
    nor: int
    time: float


@dataclass
class FieldInfo:
    name: str
    mesh: str
    components: list
    steps: list
    support: str          # NODE | ELGA | ELEM | ELNO
    profiled: bool

    @property
    def short(self):
        # code_aster names the fields <result, 8 chars><field>: RESU____DEPL
        return self.name[8:] if len(self.name) > 8 else self.name

    def step_index(self, step=None, time=None):
        """Index of the requested time step: by time (the nearest) or by index
        (negative = from the end). Default: the last one."""
        if not self.steps:
            raise MedError(f"Field {self.name} has no time steps")
        if time is not None:
            t = np.array([s.time for s in self.steps])
            return int(np.argmin(np.abs(t - float(time))))
        i = -1 if step is None else int(step)
        if not -len(self.steps) <= i < len(self.steps):
            raise MedError(f"Step {i} out of range: {self.name} has {len(self.steps)} time steps")
        return i % len(self.steps)


@dataclass
class FieldStep:
    info: FieldInfo
    index: int
    step: StepInfo
    node: np.ndarray | None = None              # (N, nc) with NaN outside the profile
    cells: dict = field(default_factory=dict)   # type -> (ne, nga, nc)
    loc: dict = field(default_factory=dict)     # type -> Gauss localization name


class MedResult:
    """A MED file opened read-only. The HDF5 is not kept open between
    calls (so as not to block code_aster if the file is being written)."""

    def __init__(self, path):
        self.path = os.path.realpath(os.path.expanduser(path))
        if not os.path.isfile(self.path):
            raise MedError(f"File not found: {self.path}")
        st = os.stat(self.path)
        self.size, self.mtime = st.st_size, st.st_mtime
        self._lock = threading.RLock()
        self._meshes = {}                # name -> Mesh (shared with the views)
        self._loc = None
        self._cache = OrderedDict()
        with self._open() as f:
            if "ENS_MAA" not in f:
                raise MedError(f"{self.path} does not look like a MED file (no /ENS_MAA)")
            self.mesh_names = list(f["ENS_MAA"].keys())
            self.fields = OrderedDict()
            for name, g in f.get("CHA", {}).items():
                self.fields[name] = self._field_info(name, g)
        self.all_fields = self.fields
        # default mesh: the first one with fields
        used = {f.mesh for f in self.fields.values()}
        self.mesh_name = next((m for m in self.mesh_names if m in used), self.mesh_names[0] if self.mesh_names else None)

    def view(self, mesh_name):
        """The same file seen from one mesh: only its fields and its geometry
        (shares the caches with the original)."""
        if mesh_name not in self.mesh_names:
            raise MedError(f"No mesh '{mesh_name}'. Meshes: {self.mesh_names}")
        v = copy.copy(self)
        v.mesh_name = mesh_name
        v.fields = OrderedDict((k, f) for k, f in self.all_fields.items() if f.mesh == mesh_name)
        return v

    def _open(self):
        try:
            return h5py.File(self.path, "r", locking=False)
        except OSError as e:
            m = re.search(r"eof = (\d+).*stored_eof = (\d+)", str(e))
            if m:
                have, want = int(m.group(1)), int(m.group(2))
                raise MedError(
                    f"TRUNCATED file: {have/1e6:.1f} MB on disk but the HDF5 header expects "
                    f"{want/1e6:.1f} MB ({100*have/want:.0f} %). Most likely an incomplete "
                    "copy (interrupted transfer): look for the original.") from None
            raise MedError(f"Could not open {self.path}: {e}") from None

    # ------------------------------------------------------------------ fields
    @staticmethod
    def _field_info(name, g):
        comps = _split16(g.attrs["NOM"], g.attrs["NCO"])
        steps = [StepInfo(k, int(s.attrs["NDT"]), int(s.attrs["NOR"]), float(s.attrs["PDT"]))
                 for k, s in g.items()]
        steps.sort(key=lambda s: (s.ndt, s.nor))
        support, profiled = "NODE", False
        if steps:
            s0 = g[steps[-1].key]
            for ent, eg in s0.items():
                for pname, pg in eg.items():
                    profiled |= pname != NO_PROFILE
                    if ent.startswith("MAI."):
                        nga = int(pg.attrs["NGA"])
                        support = "ELGA" if (nga > 1 or _s(pg.attrs.get("GAU", "")).strip()) else "ELEM"
                    elif ent.startswith("NOE.") or ent.startswith("NOM."):
                        support = "ELNO"           # one value per node of each cell
        return FieldInfo(name, _s(g.attrs["MAI"]), comps, steps, support, profiled)

    def field(self, name):
        """Resolves the field name: full (RESU____DEPL) or short (DEPL)."""
        if name in self.fields:
            return self.fields[name]
        cands = [f for f in self.fields.values() if f.short == name or f.name.endswith(name)]
        if len(cands) == 1:
            return cands[0]
        if not cands:
            raise MedError(f"No field '{name}'. Fields: {[f.short for f in self.fields.values()]}")
        raise MedError(f"'{name}' is ambiguous: " + ", ".join(f"{f.name} (mesh {f.mesh})" for f in cands)
                       + ". Use the full name or choose the mesh.")

    def label(self, info):
        """Name to show and to give back to field(): the short one, or the full one when
        two fields of the same mesh share it (CARGA___DEPL and DESCARGADEPL are both DEPL)."""
        same = sum(f.short == info.short and f.mesh == info.mesh for f in self.all_fields.values())
        return info.name if same > 1 else info.short

    def read(self, field_name, step=None, time=None):
        info = self.field(field_name)
        i = info.step_index(step, time)
        key = (info.name, i)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        st = info.steps[i]
        mesh = self.mesh_of(info.mesh)
        nc = len(info.components)
        fs = FieldStep(info, i, st)
        with self._open() as f:
            sg = f["CHA"][info.name][st.key]
            for ent, eg in sg.items():
                for pname, pg in eg.items():
                    co = np.asarray(pg["CO"][()], dtype=float)
                    nga = int(pg.attrs.get("NGA", 1))
                    n = co.size // (nc * nga)
                    vals = co.reshape(nc, n, nga).transpose(1, 2, 0)
                    ids = None
                    if pname != NO_PROFILE:
                        ids = f["PROFILS"][pname]["PFL"][()].astype(np.int64) - 1
                        if len(ids) != n:
                            raise MedError(f"Profile {pname}: {len(ids)} ids for {n} values")
                    if ent == "NOE":
                        out = np.full((mesh.n_nodes, nc), np.nan)
                        out[slice(None) if ids is None else ids] = vals[:, 0, :]
                        fs.node = out
                    else:
                        mtype = ent.split(".", 1)[1]
                        ne = mesh.blocks[mtype].ne
                        out = np.full((ne, nga, nc), np.nan)
                        out[slice(None) if ids is None else ids] = vals
                        fs.cells[mtype] = out
                        fs.loc[mtype] = _s(pg.attrs.get("GAU", "")).strip()
        with self._lock:
            self._cache[key] = fs
            while len(self._cache) > 6:
                self._cache.popitem(last=False)
        return fs

    # ------------------------------------------------------------------- mesh
    @property
    def mesh(self):
        return self.mesh_of(self.mesh_name)

    def mesh_of(self, name):
        with self._lock:
            if name not in self._meshes:
                self._meshes[name] = self._read_mesh(name)
            return self._meshes[name]

    def _read_mesh(self, name):
        with self._open() as f:
            mg = f["ENS_MAA"][name]
            sg = mg[next(iter(mg.keys()))]
            coo = sg["NOE"]["COO"]
            n = int(coo.attrs["NBR"])
            X = coo[()].reshape(-1, n).T
            space_dim = X.shape[1]
            if X.shape[1] < 3:
                X = np.hstack([X, np.zeros((n, 3 - X.shape[1]))])
            node_fam = sg["NOE"]["FAM"][()] if "FAM" in sg["NOE"] else np.zeros(n, int)
            blocks = []
            for mtype, bg in sg.get("MAI", {}).items():
                ne = len(bg["FAM"]) if "FAM" in bg else int(bg["NOD"].attrs["NBR"])
                conn = bg["NOD"][()].reshape(-1, ne).T.astype(np.int64) - 1
                fam = bg["FAM"][()] if "FAM" in bg else np.zeros(ne, int)
                num = bg["NUM"][()] if "NUM" in bg else np.arange(1, ne + 1)
                blocks.append(Block(mtype, conn, fam, num))
            blocks.sort(key=lambda b: int(b.num[0]) if b.ne else 0)
            fams = {"NOEUD": {}, "ELEME": {}}
            if "FAS" in f and name in f["FAS"]:
                for kind in fams:
                    for _, g in f["FAS"][name].get(kind, {}).items():
                        if "GRO" in g:
                            fams[kind][int(g.attrs["NUM"])] = _names80(g["GRO"]["NOM"][()])
        mesh = Mesh(name, X, node_fam, OrderedDict((b.mtype, b) for b in blocks), space_dim=space_dim)
        by_group = {}
        for num, names in fams["NOEUD"].items():
            for gname in names:
                by_group.setdefault(gname, []).append(num)
        for gname, nums in by_group.items():
            mesh.node_groups[gname] = np.nonzero(np.isin(node_fam, nums))[0]
        by_group = {}
        for num, names in fams["ELEME"].items():
            for gname in names:
                by_group.setdefault(gname, []).append(num)
        for gname, nums in by_group.items():
            d = {}
            for b in blocks:
                idx = np.nonzero(np.isin(b.fam, nums))[0]
                if len(idx):
                    d[b.mtype] = idx
            mesh.cell_groups[gname] = d
        return mesh

    # ------------------------------------------------------- Gauss points
    def _localizations(self):
        if self._loc is None:
            self._loc = {}
            with self._open() as f:
                for lname, g in f.get("GAUSS", {}).items():
                    self._loc[lname] = (g["COO"][()], g["GAU"][()])
        return self._loc

    def gauss_xyz(self, mtype, loc_name, nga, mesh=None):
        """Physical coordinates (ne, nga, 3) of the Gauss points. If the shape functions
        cannot be built, returns the centroid repeated."""
        mesh = mesh or self.mesh
        b = mesh.blocks[mtype]
        cent = mesh.centroids(mtype)[:, None, :]
        locs = self._localizations()
        exps = _exps(mtype)
        if nga == 1 or loc_name not in locs or exps is None:
            return np.repeat(cent, nga, axis=1)
        coo, gau = locs[loc_name]
        nn = b.conn.shape[1]
        dim = coo.size // nn
        ref = coo.reshape(dim, nn).T                  # non-interlaced (checked)
        if len(np.unique(np.round(ref, 9), axis=0)) != nn:
            ref = coo.reshape(nn, dim)                # interlaced
            gp = gau.reshape(nga, dim)
        else:
            gp = gau.reshape(dim, nga).T
        if len(exps) != nn:
            return np.repeat(cent, nga, axis=1)
        mono = lambda P: np.stack([np.prod(P ** np.array(e)[None, :], axis=1) for e in exps], axis=1)
        V = mono(ref)
        if np.linalg.cond(V) > 1e8:
            return np.repeat(cent, nga, axis=1)
        N = mono(gp) @ np.linalg.inv(V)               # (nga, nn)
        if not np.allclose(N.sum(axis=1), 1.0, atol=1e-8):
            return np.repeat(cent, nga, axis=1)
        return np.einsum("gn,enk->egk", N, mesh.coords[b.conn])


_OPEN = OrderedDict()
_OPEN_LOCK = threading.Lock()


def open_med(path) -> MedResult:
    """MedResult cached by (path, size, date): if the file changes, it is read again."""
    p = os.path.realpath(os.path.expanduser(path))
    try:
        st = os.stat(p)
    except FileNotFoundError:
        raise MedError(f"File not found: {p}") from None
    key = (p, st.st_size, st.st_mtime)
    with _OPEN_LOCK:
        if key in _OPEN:
            _OPEN.move_to_end(key)
            return _OPEN[key]
    r = MedResult(p)
    with _OPEN_LOCK:
        _OPEN[key] = r
        while len(_OPEN) > 4:
            _OPEN.popitem(last=False)
    return r
