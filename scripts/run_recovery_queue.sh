#!/usr/bin/env bash
# Resume the approved historical scope after the pilot and environment gates.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
export CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
test -n "${TMUX:-}"
python -uB scripts/wait_task.py p0-baseline
python -uB scripts/wait_task.py pixal-setup
python -uB scripts/wait_task.py pixal-clone-repair
python -uB scripts/wait_task.py pixal-revalidation
python -uB scripts/wait_task.py crop-ablation
run_step() {
    local task_name="$1"
    shift
    if python -c 'import json,pathlib,sys; p=pathlib.Path(".runtime/logs/recovery-20261105")/(sys.argv[1]+".status.json"); sys.exit(not(p.is_file() and json.loads(p.read_text())["status"]=="passed"))' "$task_name"; then
        echo "RESUME $task_name already passed"
        return
    fi
    python -uB scripts/run_task.py --name "$task_name"         --log-dir "$WT_REPO_ROOT/.runtime/logs/recovery-20261105"         --artifact-dir "$WT_OUTPUT_ROOT/logs/recovery-20261105" -- "$@"
}
run_step p0-pixal python -uB scripts/recover_experiments.py --experiments P0 --phase pixal
run_step crop-ablation python -uB scripts/recover_crop_ablation.py
run_step r1-baseline python -uB scripts/recover_experiments.py --experiments R1 --phase baseline
run_step r1-pixal python -uB scripts/recover_experiments.py --experiments R1 --phase pixal
run_step texture-seeds python -uB scripts/recover_texture_seeds.py
python -uB scripts/check_recovery_performance.py
run_step r2-baseline python -uB scripts/recover_experiments.py --experiments R2 --phase baseline
run_step r2-pixal python -uB scripts/recover_experiments.py --experiments R2 --phase pixal
run_step final-prepublication python -uB scripts/finalize_recovery.py
