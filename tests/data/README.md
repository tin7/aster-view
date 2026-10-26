# Test files

Small code_aster 17.4 results for the format tests (`tests/test_formats.py`).

| file | what it covers |
|---|---|
| `axis_resu.med` | 2D axisymmetric model (`AXIS`, QUAD8): thick-walled tube under internal pressure, compared with Lamé. ELNO field `SIGM_ELNO` next to `SIGM_NOEU`, and `SIEQ_ELGA` to check von Mises with 4 stress components. |
| `dplan_t6_resu.med` | 2D plane strain (`D_PLAN`) with TRIA6 elements: plate with a hole. |
| `multi_resu.med` | two meshes in one file: the 3D tube of `examples/thick_tube` (10 MPa) and the 2D axisymmetric tube (20 MPa), with fields of the same short name on each. |

`run.sh` regenerates them with Docker from `make_meshes.py` and the `.comm`/`.export` files.
