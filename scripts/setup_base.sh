#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
python -c 'import os,sys; assert sys.version_info[:2] == (3,11); assert os.path.realpath(sys.prefix) == os.path.realpath(os.environ["WT_ENV_ROOT"])'
export PIP_INDEX_URL="${WT_PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple}"
export PIP_CONSTRAINT="$WT_REPO_ROOT/constraints.txt"
mkdir -p "$PIP_CACHE_DIR" "$TMPDIR"
# Avoid the slow NVIDIA package CDN; this is the identical official wheel.
if ! python -c 'import importlib.metadata as m; assert m.version("nvidia-nccl-cu12") == "2.21.5"' 2>/dev/null; then
    python -m pip install --no-deps 'https://download.pytorch.org/whl/cu124/nvidia_nccl_cu12-2.21.5-py3-none-manylinux2014_x86_64.whl#sha256=8579076d30a8c24988834445f8d633c697d42397e92ffc3f63fa26766d25e0a0'
fi
if ! python -c 'import importlib.metadata as m; assert [m.version(n) for n in ("torch", "torchvision", "triton")] == ["2.6.0+cu124", "0.21.0+cu124", "3.2.0"]' 2>/dev/null; then
    python -m pip install --no-deps -r requirements.torch.txt
fi
python -m pip install torch==2.6.0 torchvision==0.21.0 --index-url "$PIP_INDEX_URL"
python -m pip install --index-url "$PIP_INDEX_URL" -e '.[viz,bg,textured-mesh,experiments]' ninja packaging wheel setuptools pytest cmake==3.31.10 imageio imageio-ffmpeg tqdm easydict tensorboard pandas lpips zstandard
python -B scripts/setup_viser_client.py
python -m pip check
