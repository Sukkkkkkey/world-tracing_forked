#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
mkdir -p "$TMPDIR" "$WT_OUTPUT_ROOT/validation"
python -m pip check
export HF_HUB_OFFLINE=1
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
python -m pytest tests -q -p no:cacheprovider
python scripts/check_artifact_storage.py
python scripts/smoke_wt.py
python scripts/smoke_trellis2.py
python scripts/smoke_hybrid.py
for example in examples/infer_rgba.py examples/infer_scene.py examples/infer_video.py examples/infer_textured_mesh.py examples/check_reproduction.py; do
    python "$example" --help > /dev/null
done
python -m pip freeze > requirements.lock.txt
