"""Quarter of a thick-walled tube, HEXA20, for the Aster View example and tests.

Inner radius 50 mm, outer radius 60 mm, length 100 mm, 0 <= theta <= 90 deg.
All nodes (corner and mid-side) sit on the exact cylindrical geometry: they are
taken from a lattice twice as fine as the element grid, in (r, theta, z).
Groups: Tube (volume), Inner, Outer, SymX (x = 0), SymY (y = 0), Bottom (z = 0), Top (z = L).

Runs with MEDCoupling, e.g. inside the code_aster image (see run.sh):
    python3 make_mesh.py tube_mesh.med
"""
import sys

import medcoupling as mc
import numpy as np

A, B, L = 50.0, 60.0, 100.0
NR, NT, NZ = 3, 12, 8

r = np.linspace(A, B, 2 * NR + 1)
t = np.linspace(0.0, np.pi / 2, 2 * NT + 1)
z = np.linspace(0.0, L, 2 * NZ + 1)
R, T, Z = np.meshgrid(r, t, z, indexing="ij")
xyz = np.column_stack([(R * np.cos(T)).ravel(), (R * np.sin(T)).ravel(), Z.ravel()])


def nid(i, j, k):
    return (i * (2 * NT + 1) + j) * (2 * NZ + 1) + k


# MED HEXA20: corners 0-3 (bottom face), 4-7 (top), then edges 0-1, 1-2, 2-3, 3-0,
# 4-5, 5-6, 6-7, 7-4, 0-4, 1-5, 2-6, 3-7. "Bottom" here is the face at smaller z;
# the corner order is checked below with the signed volume.
conn = []
for i in range(NR):
    for j in range(NT):
        for k in range(NZ):
            I, J, K = 2 * i, 2 * j, 2 * k
            c = [(I, J, K), (I, J + 2, K), (I + 2, J + 2, K), (I + 2, J, K)]
            top = [(a, b, K + 2) for a, b, _ in c]
            mid = lambda p, q: tuple((np.add(p, q) // 2).tolist())
            cc = c + top
            edges = [mid(cc[0], cc[1]), mid(cc[1], cc[2]), mid(cc[2], cc[3]), mid(cc[3], cc[0]),
                     mid(cc[4], cc[5]), mid(cc[5], cc[6]), mid(cc[6], cc[7]), mid(cc[7], cc[4]),
                     mid(cc[0], cc[4]), mid(cc[1], cc[5]), mid(cc[2], cc[6]), mid(cc[3], cc[7])]
            conn.append([nid(*p) for p in cc + edges])

m = mc.MEDCouplingUMesh("tube", 3)
m.setCoords(mc.DataArrayDouble(xyz.tolist(), len(xyz), 3))
m.allocateCells(len(conn))
for c in conn:
    m.insertNextCell(mc.NORM_HEXA20, c)
m.finishInsertingCells()
m.zipCoords()                                   # drop the lattice points no cell uses
# MEDCoupling measures with the corners only: compare with the faceted (chord) volume
vol = m.getMeasureField(False).getArray().toNumPyArray()
dt = np.pi / 2 / NT
exact = np.pi / 4 * (B ** 2 - A ** 2) * L * np.sin(dt) / dt
assert (vol > 0).all() and abs(vol.sum() / exact - 1) < 1e-9, (vol.min(), vol.sum(), exact)

skin = m.computeSkin()
skin.setName("tube")
bary = skin.computeCellCenterOfMass().toNumPyArray()
rb = np.hypot(bary[:, 0], bary[:, 1])
tol = 1e-6
faces = {"Inner": np.abs(rb - A) < 0.5, "Outer": np.abs(rb - B) < 0.5,   # corner barycentre: on the chord
         "SymX": np.abs(bary[:, 0]) < tol, "SymY": np.abs(bary[:, 1]) < tol,
         "Bottom": np.abs(bary[:, 2]) < tol, "Top": np.abs(bary[:, 2] - L) < tol}

mf = mc.MEDFileUMesh()
mf.setMeshAtLevel(0, m)
mf.setMeshAtLevel(-1, skin)
g = mc.DataArrayInt(list(range(m.getNumberOfCells())))
g.setName("Tube")
mf.setGroupsAtLevel(0, [g])
groups = []
for name, mask in faces.items():
    ids = mc.DataArrayInt(np.flatnonzero(mask).tolist())
    ids.setName(name)
    groups.append(ids)
mf.setGroupsAtLevel(-1, groups)
mf.write(sys.argv[1] if len(sys.argv) > 1 else "tube_mesh.med", 2)
print(f"{m.getNumberOfCells()} HEXA20, {m.getNumberOfNodes()} nodes, volume error "
      f"{vol.sum() / exact - 1:.1e} (faceted); faces: " + ", ".join(f"{k}={int(v.sum())}" for k, v in faces.items()))
