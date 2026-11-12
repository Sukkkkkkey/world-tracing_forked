#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
mkdir -p "$WT_OUTPUT_ROOT/logs" "$TMPDIR"
bash scripts/setup_base.sh
bash scripts/setup_native.sh
