# Example: thick-walled tube under internal pressure

Quarter of a tube (inner radius 50 mm, outer radius 60 mm, length 100 mm) under internal
pressure. The pressure is ramped from 0 to 10 MPa in 4 steps. The model has 288 HEXA20
elements, symmetry conditions on x = 0, y = 0 and z = 0, and a free end at z = 100 mm.
Linear elastic, E = 200 GPa, ν = 0.3. Units: mm, N, MPa.

With free ends (σz = 0) the exact 3D solution is Lamé's:

    σr = A − B/r²,   σθ = A + B/r²,   A = p a² / (b² − a²),   B = A b²

`tests/test_reader.py` compares the file with it.

| file | |
|---|---|
| `tube_resu.med` | result: DEPL, SIEF_ELGA (27 Gauss points per element) and SIGM_NOEU at t = 0, 0.25, 0.5, 0.75, 1 |
| `tube_mesh.med` | mesh with groups `Tube`, `Inner`, `Outer`, `SymX`, `SymY`, `Bottom`, `Top` |
| `make_mesh.py` | builds the mesh with MEDCoupling (all nodes on the exact cylinders) |
| `tube.comm`, `tube.export` | code_aster 17.4 input |
| `run.sh` | regenerates everything with the `simvia/code_aster` Docker image (about 30 s) |

```bash
aster-view tube_resu.med --field SIEF_ELGA --comp SITT
```
