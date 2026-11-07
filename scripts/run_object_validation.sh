#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
export HF_HUB_DISABLE_XET=1
checkpoint_path="$(python scripts/download_object.py)"
unset HF_TOKEN
export HF_HUB_OFFLINE=1
export CUDA_VISIBLE_DEVICES=0
python examples/infer_rgba.py --image examples/test_images/object/obj014_leather_briefcase.png --ckpt "$checkpoint_path" --config r75b --seed 42 --out "$WT_OUTPUT_ROOT/validation/object_seed42.rrd"
