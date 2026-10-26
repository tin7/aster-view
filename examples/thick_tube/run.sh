#!/bin/sh
# Regenerates the example with the official code_aster image (Docker); about 30 s.
set -e
cd "$(dirname "$0")"
IMG=${IMG:-simvia/code_aster:17.4.22}
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" -w /work "$IMG" bash -c '
  source /opt/activate.sh
  python3 make_mesh.py tube_mesh.med
  export PATH=$PATH:$(dirname $(find /opt/spack -name run_aster -type f | head -1))
  run_aster tube.export'
