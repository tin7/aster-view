"""Quarter of a plate with a central hole, HEXA20, for the Aster View examples.

Hole radius 10 mm, half width 40 mm, half thickness 4 mm (model: 0 <= x, y <= 40, 0 <= z <= 4).
One structured block mapped from the hole (r = a) to the outer square; all nodes, mid-side
ones included, come from a lattice twice as fine as the elements, so the hole is exact.
Groups: Plate (volume), Hole, Right (x = 40), Top (y = 40), SymX (x = 0), SymY (y = 0),
Bottom (z = 0), Front (z = 4).

    python3 make_mesh.py plate_mesh.med        (needs MEDCoupling, see run.sh)
"""
import sys

import medcoupling as mc
import numpy as np

A, W, T = 10.0, 40.0, 4.0
NR, NT, NZ = 16, 12, 1         # elements: radial, per 45 degrees, thickness

ti = (np.arange(2 * NR + 1) / (2 * NR)) ** 1.6          # finer near the hole
th = np.linspace(0.0, np.pi / 2, 4 * NT + 1)             # 2*NT elements over 90 degrees
z = np.linspace(0.0, T, 2 * NZ + 1)


def square(t):
    """Point of the outer square boundary seen from the origin at angle t."""
    return (W, W * np.tan(t)) if t <= np.pi / 4 + 1e-12 else (W / np.tan(t), W)


xy = np.array([[(1 - s) * A * np.cos(t) + s * square(t)[0], (1 - s) * A * np.sin(t) + s * square(t)[1]]
               for s in ti for t in th])                 # index i * len(th) + j
NI, NJ, NK = len(ti), len(th), len(z)
xyz = np.array([[x, y, zz] for (x, y) in xy for zz in z])


def nid(i, j, k):
    return (i * NJ + j) * NK + k


conn = []
for i in range(NR):
    for j in range(2 * NT):
        for k in range(NZ):
            I, J, K = 2 * i, 2 * j, 2 * k
            c = [(I, J, K), (I, J + 2, K), (I + 2, J + 2, K), (I + 2, J, K)]
            cc = c + [(a, b, K + 2) for a, b, _ in c]
            mid = lambda p, q: tuple((np.add(p, q) // 2).tolist())
            edges = [mid(cc[0], cc[1]), mid(cc[1], cc[2]), mid(cc[2], cc[3]), mid(cc[3], cc[0]),
                     mid(cc[4], cc[5]), mid(cc[5], cc[6]), mid(cc[6], cc[7]), mid(cc[7], cc[4]),
                     mid(cc[0], cc[4]), mid(cc[1], cc[5]), mid(cc[2], cc[6]), mid(cc[3], cc[7])]
            conn.append([nid(*p) for p in cc + edges])

m = mc.MEDCouplingUMesh("plate", 3)
m.setCoords(mc.DataArrayDouble(xyz.tolist(), len(xyz), 3))
m.allocateCells(len(conn))
for c in conn:
    m.insertNextCell(mc.NORM_HEXA20, c)
m.finishInsertingCells()
m.zipCoords()
vol = m.getMeasureField(False).getArray().toNumPyArray()
assert (vol > 0).all(), "wrong orientation"

skin = m.computeSkin()
skin.setName("plate")
b = skin.computeCellCenterOfMass().toNumPyArray()
rb, tol = np.hypot(b[:, 0], b[:, 1]), 1e-6
side = (np.abs(b[:, 2]) > tol) & (np.abs(b[:, 2] - T) > tol) & (np.abs(b[:, 0]) > tol) & (np.abs(b[:, 1]) > tol)
faces = {"Hole": (rb < A + 0.5) & side, "Right": np.abs(b[:, 0] - W) < tol, "Top": np.abs(b[:, 1] - W) < tol,
         "SymX": np.abs(b[:, 0]) < tol, "SymY": np.abs(b[:, 1]) < tol,
         "Bottom": np.abs(b[:, 2]) < tol, "Front": np.abs(b[:, 2] - T) < tol}
mf = mc.MEDFileUMesh()
mf.setMeshAtLevel(0, m)
mf.setMeshAtLevel(-1, skin)
g = mc.DataArrayInt(list(range(m.getNumberOfCells())))
g.setName("Plate")
mf.setGroupsAtLevel(0, [g])
groups = []
for name, mask in faces.items():
    ids = mc.DataArrayInt(np.flatnonzero(mask).tolist())
    ids.setName(name)
    groups.append(ids)
mf.setGroupsAtLevel(-1, groups)
mf.write(sys.argv[1] if len(sys.argv) > 1 else "plate_mesh.med", 2)
print(f"{m.getNumberOfCells()} HEXA20, {m.getNumberOfNodes()} nodes; faces: "
      + ", ".join(f"{k}={int(v.sum())}" for k, v in faces.items()))
