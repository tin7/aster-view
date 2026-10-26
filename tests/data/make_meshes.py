"""2D test meshes: axisymmetric tube (QU8), plate with a hole in plane strain
(QU8, and TR3 that code_aster turns into TR6). Runs with MEDCoupling (see run.sh)."""
import medcoupling as mc
import numpy as np


def write(name, coords, cells, ctype, faces_of, fname):
    m = mc.MEDCouplingUMesh(name, 2)
    m.setCoords(mc.DataArrayDouble(coords.tolist(), len(coords), 2))
    m.allocateCells(len(cells))
    for c in cells:
        m.insertNextCell(ctype, c)
    m.finishInsertingCells()
    m.zipCoords()
    area = m.getMeasureField(False).getArray().toNumPyArray()
    print(name, ctype, "signed area: min", area.min(), "max", area.max())
    skin = m.computeSkin()
    skin.setName(name)
    b = skin.computeCellCenterOfMass().toNumPyArray()
    mf = mc.MEDFileUMesh()
    mf.setMeshAtLevel(0, m)
    mf.setMeshAtLevel(-1, skin)
    g = mc.DataArrayInt(list(range(m.getNumberOfCells())))
    g.setName("Body")
    mf.setGroupsAtLevel(0, [g])
    gs = []
    for gname, mask in faces_of(b).items():
        ids = mc.DataArrayInt(np.flatnonzero(mask).tolist())
        ids.setName(gname)
        gs.append(ids)
    mf.setGroupsAtLevel(-1, gs)
    mf.write(fname, 2)
    print(fname, m.getNumberOfCells(), "cells", m.getNumberOfNodes(), "nodes", {k: int(v.sum()) for k, v in faces_of(b).items()})


def quad8(nI, nJ, nid):
    cells = []
    for i in range(nI):
        for j in range(nJ):
            I, J = 2 * i, 2 * j
            c = [(I, J), (I + 2, J), (I + 2, J + 2), (I, J + 2)]
            mid = lambda p, q: ((p[0] + q[0]) // 2, (p[1] + q[1]) // 2)
            e = [mid(c[0], c[1]), mid(c[1], c[2]), mid(c[2], c[3]), mid(c[3], c[0])]
            cells.append([nid(*p) for p in c + e])
    return cells


# ---- axisymmetric tube: r in [50, 60], z in [0, 100]
A, B, L, NR, NZ = 50.0, 60.0, 100.0, 4, 10
r, z = np.linspace(A, B, 2 * NR + 1), np.linspace(0, L, 2 * NZ + 1)
X = np.array([[ri, zk] for ri in r for zk in z])
write("axis", X, quad8(NR, NZ, lambda i, k: i * len(z) + k), mc.NORM_QUAD8,
      lambda b: {"Inner": np.abs(b[:, 0] - A) < 1e-6, "Outer": np.abs(b[:, 0] - B) < 1e-6,
                 "Bottom": np.abs(b[:, 1]) < 1e-6, "Top": np.abs(b[:, 1] - L) < 1e-6}, "axis_mesh.med")

# ---- quarter plate with a hole, radius 10, half width 40
a, W, NS, NT = 10.0, 40.0, 8, 6
ti = (np.arange(2 * NS + 1) / (2 * NS)) ** 1.5
th = np.linspace(0, np.pi / 2, 4 * NT + 1)
sq = lambda t: (W, W * np.tan(t)) if t <= np.pi / 4 + 1e-12 else (W / np.tan(t), W)
P = np.array([[(1 - s) * a * np.cos(t) + s * sq(t)[0], (1 - s) * a * np.sin(t) + s * sq(t)[1]] for s in ti for t in th])
P[np.abs(P) < 1e-9] = 0.0
faces = lambda b: {"Hole": np.hypot(b[:, 0], b[:, 1]) < a + 0.3, "Right": np.abs(b[:, 0] - W) < 1e-6,
                   "SymX": np.abs(b[:, 0]) < 1e-6, "SymY": np.abs(b[:, 1]) < 1e-6}
nidp = lambda i, j: i * len(th) + j
write("plate2d", P, quad8(NS, 2 * NT, nidp), mc.NORM_QUAD8, faces, "plate2d_q8.med")
# corner nodes split into triangles (TR3); code_aster turns them into TR6
cells4 = [[nidp(2 * i, 2 * j), nidp(2 * i + 2, 2 * j), nidp(2 * i + 2, 2 * j + 2), nidp(2 * i, 2 * j + 2)]
          for i in range(NS) for j in range(2 * NT)]
tris = []
for q in cells4:
    tris += [[q[0], q[1], q[2]], [q[0], q[2], q[3]]]
write("plate2d", P, tris, mc.NORM_TRI3, faces, "plate2d_t3.med")
