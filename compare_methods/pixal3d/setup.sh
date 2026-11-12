#!/usr/bin/env bash
# Run inside a dedicated screen/tmux session. Does not download model weights.
set -euo pipefail
if [ -z "${STY:-}" ] && [ -z "${TMUX:-}" ]; then
    echo 'Run this script inside a dedicated screen/tmux session.' >&2
    exit 1
fi
setup_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "$setup_dir/env.sh"
base_env="$WT_REPO_ROOT/.venv"
if [ "$(realpath -m "$WT_PIXAL3D_ENV")" = "$(realpath "$base_env")" ]; then
    echo 'Refusing to install into the existing world_tracing environment.' >&2
    exit 1
fi
source "$base_env/etc/profile.d/conda.sh"
mkdir -p "$PIP_CACHE_DIR" "$TMPDIR" "$(dirname "$FLEX_GEMM_AUTOTUNE_CACHE_PATH")"
task_log="$WT_OUTPUT_ROOT/logs/pixal3d-setup"
mkdir -p "$task_log"

checkout() {
    local directory="$1" revision="$2" url="$3"
    if [ ! -e "$directory" ]; then
        git init "$directory"
        git -C "$directory" remote add origin "$url"
        git -C "$directory" fetch --depth 1 origin "$revision"
        git -C "$directory" checkout --detach FETCH_HEAD
    fi
    test "$(git -C "$directory" rev-parse HEAD)" = "$revision"
    if [ -n "$(git -C "$directory" status --porcelain)" ]; then
        echo "Checkout has local changes; inspect before installing: $directory" >&2
        exit 1
    fi
}

case "${1:-}" in
prepare)
    while read -r name revision url; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        case "$name" in
            Pixal3D) directory="$(dirname "$WT_REPO_ROOT")/Pixal3D" ;;
            MoGe2) directory="$WT_MOGE2_ROOT" ;;
            NAF) directory="$WT_NAF_ROOT" ;;
            *) echo "Unknown source: $name" >&2; exit 1 ;;
        esac
        checkout "$directory" "$revision" "$url"
    done < "$setup_dir/sources.lock"
    if [ ! -e "$WT_REPO_ROOT/compare_methods/Pixal3D" ] && [ ! -L "$WT_REPO_ROOT/compare_methods/Pixal3D" ]; then
        ln -s ../../Pixal3D "$WT_REPO_ROOT/compare_methods/Pixal3D"
    fi
    test -L "$WT_REPO_ROOT/compare_methods/Pixal3D"
    test "$(realpath "$WT_REPO_ROOT/compare_methods/Pixal3D")" = "$(dirname "$WT_REPO_ROOT")/Pixal3D"
    if [ ! -f "$WT_PIXAL3D_ENV/conda-meta/history" ]; then
        # Explicit source selection avoids changing global channels or accepting ToS.
        conda create --offline --yes --override-channels --channel conda-forge \
            --prefix "$WT_PIXAL3D_ENV" --clone "$base_env"
    fi
    conda activate "$WT_PIXAL3D_ENV"
    python "$setup_dir/reconcile_clone.py" --repair
    if [ ! -f "$task_log/cloned.txt" ]; then
        python -m pip freeze --all > "$task_log/cloned.txt"
    fi
    python -m pip check
    ;;
install)
    conda activate "$WT_PIXAL3D_ENV"
    test "$(realpath "$CONDA_PREFIX")" = "$(realpath "$WT_PIXAL3D_ENV")"
    python -c 'import sys, torch; assert sys.version_info[:2] == (3, 11); assert torch.__version__ == "2.6.0+cu124"'
    export PIP_CONSTRAINT="$setup_dir/constraints.txt"
    export PIP_INDEX_URL="${WT_PIXAL3D_PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple}"
    python -m pip install -r "$setup_dir/requirements.txt"
    wheel_dir="$WT_REPO_ROOT/.runtime/cache/pixal3d/wheels"
    mkdir -p "$wheel_dir"
    wheel_file="$wheel_dir/utils3d-0.0.2-py3-none-any.whl"
    if [ ! -f "$wheel_file" ]; then
        curl -fL --connect-timeout 10 --max-time 90 \
            https://github.com/LDYang694/Storages/releases/download/20260430/utils3d-0.0.2-py3-none-any.whl \
            -o "$wheel_file.part"
        mv "$wheel_file.part" "$wheel_file"
    fi
    echo "ff63440827d6933807dd06c8a5a2db7e51fd5f33c7f3dddcc766a80e0f419252  $wheel_file" | sha256sum -c -
    # Same version string as TRELLIS utils3d, but adds MoGe-2 compatibility APIs.
    python -m pip install --force-reinstall --no-deps "$wheel_file"
    # MoGe-2 is imported from its fixed source checkout via env.sh; its full
    # distribution also requires unrelated training/demo packages (Gradio/pipeline).
    natten_wheel="$wheel_dir/natten-0.21.0-cp311-cp311-linux_x86_64.whl"
    if [ "$NATTEN_CUDA_ARCH" = 8.0 ] && [ -f "$wheel_dir/sm80/$(basename "$natten_wheel")" ]; then
        natten_wheel="$wheel_dir/sm80/$(basename "$natten_wheel")"
        echo "69be4bdeb5831cac07dedd49abef6e7dcd3a84cc41fccbf54b4ccc59474b2a8b  $natten_wheel" | sha256sum -c -
        python -m pip install --no-index --no-deps "$natten_wheel"
    elif [ "$NATTEN_CUDA_ARCH" = 8.9 ] && [ -f "$natten_wheel" ]; then
        # Validated locally against Python 3.11 / torch 2.6.0+cu124 / SM89.
        echo "1033ea88b138e73252a12128bc109cbde10b7a23d213d551d8360d991c6998fa  $natten_wheel" | sha256sum -c -
        python -m pip install --no-index --no-deps "$natten_wheel"
    else
        python -m pip install natten==0.21.0 --no-build-isolation --no-deps
    fi
    python -m pip check
    python -m pip freeze --all > "$setup_dir/requirements.lock.txt"
    ;;
check)
    conda activate "$WT_PIXAL3D_ENV"
    export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
    python "$setup_dir/reconcile_clone.py"
    python "$setup_dir/check_environment.py"
    ;;
*)
    echo "Usage: bash $0 {prepare|install|check}" >&2
    exit 2
    ;;
esac
