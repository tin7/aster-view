#!/bin/sh
# Regenerates the test files with the official code_aster image (Docker); about 1 min.
# multi.export also reads examples/thick_tube/tube_mesh.med.
set -e
cd "$(dirname "$0")"
cp ../../examples/thick_tube/tube_mesh.med .
IMG=${IMG:-simvia/code_aster:17.4.22}
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" -w /work "$IMG" bash -c '
  source /opt/activate.sh
  python3 make_meshes.py
  export PATH=$PATH:$(dirname $(find /opt/spack -name run_aster -type f | head -1))
  for c in axis dplan_t6 multi; do run_aster $c.export; done'
rm -f tube_mesh.med axis_mesh.med plate2d_q8.med plate2d_t3.med *.mess
