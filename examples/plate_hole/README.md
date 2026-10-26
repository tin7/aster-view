# Example: plate with a hole, elastic-plastic

Quarter of a plate with a central hole (radius 10 mm, half width 40 mm, half thickness 4 mm)
pulled in x. The remote tension is ramped from 0 to 150 MPa. The material is elastic-plastic
(`VMIS_ISOT_LINE`): E = 200 GPa, ν = 0.3, yield stress 250 MPa, linear hardening 2 GPa.
At the hole the stress concentration is about 3 in the elastic range, so a plastic zone appears
at about 60 % of the load and grows while the net section stays elastic.
Units: mm, N, MPa.

| file | |
|---|---|
| `plate_resu.med` | result at t = 0, 0.2, …, 1: DEPL, SIEF_ELGA, VARI_ELGA (also with named components EPSPEQ, INDIPLAS), and the nodal SIGM_NOEU and VARI_NOEU |
| `plate_mesh.med` | 384 HEXA20 elements, groups `Plate`, `Hole`, `Right`, `Top`, `SymX`, `SymY`, `Bottom`, `Front` |
| `make_mesh.py` | builds the mesh with MEDCoupling (the hole is exact, mid-side nodes included) |
| `plate.comm`, `plate.export` | code_aster 17.4 input (`3D_SI`, `STAT_NON_LINE`) |
| `run.sh` | regenerates everything with the `simvia/code_aster` Docker image |

```bash
aster-view plate_resu.med --field SIGM_NOEU --comp VMIS
```

Most of the pictures in the main README come from this file (`docs/make_images.py`).
