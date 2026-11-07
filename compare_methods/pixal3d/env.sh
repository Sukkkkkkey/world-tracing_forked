# Source after activating the isolated Pixal3D environment.
export WT_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export WT_PIXAL3D_ENV="${WT_PIXAL3D_ENV:-$WT_REPO_ROOT/.venv-pixal3d}"
export WT_PIXAL3D_ROOT="${WT_PIXAL3D_ROOT:-$WT_REPO_ROOT/compare_methods/Pixal3D}"
export WT_MOGE2_ROOT="${WT_MOGE2_ROOT:-$WT_REPO_ROOT/dependencies/MoGe2}"
export WT_NAF_ROOT="${WT_NAF_ROOT:-$WT_REPO_ROOT/dependencies/NAF}"
export WT_DATA_ROOT="${WT_DATA_ROOT:-/mnt/oss1/lemonade_factory/SYNC/shuqiliu/data}"
export WT_OUTPUT_ROOT="${WT_OUTPUT_ROOT:-/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing}"
export WT_WEIGHTS_ROOT="${WT_WEIGHTS_ROOT:-$WT_OUTPUT_ROOT/weights}"
export HF_HOME="${HF_HOME:-$WT_WEIGHTS_ROOT/huggingface}"
export TORCH_HOME="${TORCH_HOME:-$WT_WEIGHTS_ROOT/torch}"
export XDG_CACHE_HOME="$WT_REPO_ROOT/.runtime/cache/pixal3d"
export HF_MODULES_CACHE="$XDG_CACHE_HOME/huggingface/modules"
export CONDA_PKGS_DIRS="$WT_REPO_ROOT/.runtime/conda-pkgs,$WT_REPO_ROOT/.venv/pkgs"
export PIP_CACHE_DIR="$XDG_CACHE_HOME/pip"
export TORCH_EXTENSIONS_DIR="$XDG_CACHE_HOME/torch_extensions"
export FLEX_GEMM_AUTOTUNE_CACHE_PATH="$XDG_CACHE_HOME/flex_gemm/autotune_cache.json"
export TRITON_CACHE_DIR="$XDG_CACHE_HOME/triton"
export TMPDIR="$WT_REPO_ROOT/.runtime/tmp/pixal3d"
export CUDA_HOME="${WT_CUDA_HOME:-/usr/local/cuda-12.4}"
export PATH="$WT_PIXAL3D_ENV/bin:$CUDA_HOME/bin:$PATH"
# Do not inherit another project's Python imports or user-site installations.
export PYTHONPATH="$WT_REPO_ROOT:$WT_PIXAL3D_ROOT:$WT_MOGE2_ROOT"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED="${PYTHONHASHSEED:-42}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.0}"
# NATTEN 0.21.0 multiplies this decimal architecture by ten internally.
export NATTEN_CUDA_ARCH="${NATTEN_CUDA_ARCH:-8.0}"
export MAX_JOBS="${MAX_JOBS:-4}" NATTEN_N_WORKERS="${NATTEN_N_WORKERS:-4}"
export ATTN_BACKEND=flash_attn
export OPENCV_IO_ENABLE_OPENEXR=1

export HF_HUB_DISABLE_SYMLINKS_WARNING=1
if [ -f "$WT_REPO_ROOT/.runtime/gitconfig" ]; then export GIT_CONFIG_GLOBAL="$WT_REPO_ROOT/.runtime/gitconfig"; fi
