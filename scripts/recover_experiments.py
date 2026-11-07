"""Resume the approved P0/R1/R2 recovery in isolated environments on one GPU."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get('WT_OUTPUT_ROOT', '/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing'))
PROCESSED = Path(os.environ.get('WT_PROCESSED_ROOT', '/mnt/oss1/lemonade_factory/SYNC/shuqiliu/data/processed/world_tracing'))


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.partial')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def run(environment, *args):
    command = ['bash', '-c', 'source "$1" && shift && exec "$@"', 'recovery', environment, 'python', '-uB', *map(str, args)]
    print('RUN', environment, *map(str, args), flush=True)
    subprocess.run(command, cwd=REPO, env=os.environ | {
        'CUDA_VISIBLE_DEVICES': '0', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'OMP_NUM_THREADS': '4', 'OPENBLAS_NUM_THREADS': '4', 'MKL_NUM_THREADS': '4', 'PYTHONHASHSEED': '42'}, check=True)


def recover(spec, recipe, phase):
    root = OUTPUT / 'experiments' / spec['id']
    audit_dir = OUTPUT / 'validation/recovery-20261105' / spec['id']
    audit_dir.mkdir(parents=True, exist_ok=True)
    baseline_audit, full_audit = audit_dir / 'baseline.json', audit_dir / 'all-methods.json'
    before = audit_dir / 'before-pixal.json'
    base_env, pixal_env = 'scripts/env.sh', 'compare_methods/pixal3d/env.sh'
    performance = None
    if '-R1-' in root.name or '-R2-' in root.name:
        from scripts.check_recovery_performance import check, DECISION
        performance = check()
    if phase in ('baseline', 'all'):
        assert read(REPO / '.runtime/logs/recovery-20261105/base-validation.status.json')['status'] == 'passed'
        storage = read(OUTPUT / 'validation/artifact-storage.json')
        assert storage['status'] == 'passed' and storage['source_sha256'] == sha(REPO / 'wt/artifacts.py')
        checkpoint = OUTPUT / 'weights/huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt'
        if 'split' in spec:
            inputs = PROCESSED / 'gso/v1' / (spec['split'] + '.jsonl')
            values = [json.loads(line) for line in inputs.read_text().splitlines() if line.strip()]
            expected = read(REPO / 'configs/historical_gso_samples.json')[spec['split']]
            assert len(values) == spec['samples'] and {x['sample_id'] for x in values} == set(expected)
            source_args = ['--inputs', inputs]
        else:
            inputs = REPO / spec['input_dir']
            ids = [p.stem for p in inputs.iterdir() if p.is_file() and p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')]
            assert len(ids) == spec['samples'] and set(ids) == set(recipe['qualitative_ids'])
            source_args = ['--input-dir', inputs]
        if '-R2-' in root.name and performance['workers']['baseline'] == 2:
            execution_path = audit_dir / 'execution-baseline.json'
            if execution_path.exists() and read(execution_path).get('execution_mode') == 'parallel-plus-reviewed-selective-memory-repair':
                from scripts.repair_recovery_memory import verify_completion
                verify_completion(root)
                print('R2 baseline: verified 298 preserved runs and 2 reviewed memory repairs', flush=True)
            else:
                run(base_env, 'scripts/run_parallel_recovery.py', '--experiment', root,
                    '--kind', 'baseline', '--workers', 2, '--decision', DECISION)
        else:
            run(base_env, 'examples/infer_batch.py', *source_args, '--out', root, '--ckpt', checkpoint,
                '--configs', REPO / spec['configs'], '--seeds', recipe['seed'])
        if 'split' in spec:
            run(base_env, 'examples/evaluate_gso.py', '--experiment', root,
                '--workers', recipe['evaluation_workers'], '--methods', 'wt', 'trellis2', 'wt_trellis2')
        run(base_env, 'scripts/audit_recovery_experiment.py', '--experiment', root, '--out', baseline_audit)
        report = read(baseline_audit)
        assert report['status'] == 'passed'
        extra = {'experiment.json': sha(root / 'experiment.json')}
        if '-R2-' in root.name and (audit_dir / 'memory-repair.json').exists():
            from scripts.repair_recovery_memory import SAMPLES, run_path
            for sample in SAMPLES:
                policy_file = run_path(sample) / 'memory-policy.json'
                extra[str(policy_file.relative_to(root))] = sha(policy_file)
        frozen = {root.name: report['artifact_sha256'] | extra}
        if before.exists():
            assert read(before) == frozen, 'Baseline artifacts changed since the Pixal preservation snapshot'
        else:
            write(before, frozen)
    if phase in ('pixal', 'all'):
        assert read(baseline_audit)['status'] == 'passed' and before.is_file()
        assert read(OUTPUT / 'validation/pixal3d-environment.json')['status'] == 'passed'
        if performance and performance['workers']['pixal'] == 2:
            run(pixal_env, 'scripts/run_parallel_recovery.py', '--experiment', root,
                '--kind', 'pixal', '--workers', 2, '--decision', DECISION)
        else:
            run(pixal_env, 'examples/infer_pixal3d_batch.py', '--experiment', root)
        if 'split' in spec:
            run(base_env, 'examples/evaluate_gso.py', '--experiment', root,
                '--workers', recipe['evaluation_workers'], '--methods', 'pixal3d')
    if phase in ('pixal', 'all', 'audit'):
        run(base_env, 'compare_methods/pixal3d/audit_results.py', '--experiment', root,
            '--before', before, '--out', audit_dir / 'pixal-preservation.json')
        run(base_env, 'scripts/audit_recovery_experiment.py', '--experiment', root,
            '--include-pixal', '--out', full_audit)
        assert read(full_audit)['status'] == 'passed' and read(full_audit)['expected'] == spec['runs']
        run(base_env, 'scripts/render_recovery_review.py', '--experiment', root)
    write(audit_dir / (phase + '.complete.json'), dict(status='passed', phase=phase,
        experiment=spec['id'], finished=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        recipe_sha256=sha(REPO / 'configs/recovery_experiments.json'), runner_sha256=sha(Path(__file__))))
    print('RECOVERY PHASE COMPLETE', spec['id'], phase, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiments', nargs='+', choices=['P0', 'R1', 'R2'], default=['P0', 'R1', 'R2'])
    parser.add_argument('--phase', choices=['baseline', 'pixal', 'audit', 'all'], default='all')
    args = parser.parse_args()
    recipe = read(REPO / 'configs/recovery_experiments.json')
    if not (os.environ.get('TMUX') or os.environ.get('STY')):
        raise RuntimeError('Use the dedicated recovery tmux session')
    lock_path = REPO / '.runtime/recovery-gpu.lock'
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for tag, spec in zip(('P0', 'R1', 'R2'), recipe['experiments']):
            if tag in args.experiments:
                recover(spec, recipe, args.phase)


if __name__ == '__main__':
    main()
