#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
export PIP_INDEX_URL="${WT_PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple}"
export PIP_CONSTRAINT="$WT_REPO_ROOT/constraints.txt"
python -c 'import os,sys; assert os.path.realpath(sys.prefix) == os.path.realpath(os.environ["WT_ENV_ROOT"])'
python scripts/setup_cpp_runtime.py
bash scripts/clone_dependencies.sh
python -m pip install ./dependencies/utils3d
python -m pip install flash-attn==2.7.3 --no-build-isolation
python -m pip install ./dependencies/nvdiffrast --no-build-isolation
python -m pip install ./dependencies/CuMesh --no-build-isolation
python -m pip install ./dependencies/FlexGEMM --no-build-isolation
python -m pip install ./dependencies/TRELLIS.2/o-voxel --no-build-isolation --no-deps
python -m pip install ./dependencies/nvdiffrec --no-build-isolation
python -m pip check
