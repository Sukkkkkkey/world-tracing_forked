"""Append Pixal3D to frozen experiment inputs without rewriting older results."""
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import time
import traceback

from wt.baselines.pixal3d import CONFIG
from wt.experiment import (SCHEMA_VERSION, atomic_json, digest, file_digest,
                           identifier, read_json, resolve_reference, run_directory)


def run_batch(root, backend, sample_ids=None, seed=42, dry_run=False, summary_file='last_pixal3d_batch.json'):
    root = Path(root)
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('seed must be an integer in 0..2**32-1')
    if read_json(root / 'experiment.json').get('schema_version') != SCHEMA_VERSION:
        raise ValueError('Unsupported experiment schema')
    if sample_ids is not None:
        sample_ids = [identifier(s) for s in sample_ids]
        if len(set(sample_ids)) != len(sample_ids) or not sample_ids:
            raise ValueError('Sample IDs must be nonempty and unique')
    inputs = sorted((root / 'samples').glob('*/input.json'))
    available = {p.parent.name for p in inputs}
    if sample_ids is not None and set(sample_ids) - available:
        raise ValueError('Requested sample IDs are absent from the frozen experiment')
    inputs = [p for p in inputs if sample_ids is None or p.parent.name in sample_ids]
    if not inputs:
        raise ValueError('No frozen inputs')
    config = dict(parameters=CONFIG, provenance=backend.provenance)
    config_hash = digest(config)
    jobs, skipped = [], 0
    # Validate EVERY identity and input before writing any planned run.
    for path in inputs:
        sample = read_json(path)
        sample_id = identifier(path.parent.name)
        if sample['sample_id'] != sample_id:
            raise ValueError('Input identity mismatch')
        image = resolve_reference(path.parent, sample['image'])
        if file_digest(image) != sample['sha256']:
            raise ValueError(f'Frozen input changed: {sample_id}')
        directory = run_directory(root, sample_id, 'pixal3d', CONFIG['config_id'], seed)
        if (directory / 'wt_parent.json').exists():
            raise ValueError('Independent Pixal3D must not have a WT parent')
        state = dict(schema_version=SCHEMA_VERSION, sample_id=sample_id, method='pixal3d',
                     config_id=CONFIG['config_id'], seed=seed, config_hash=config_hash,
                     input_sha256=sample['sha256'], status='planned')
        if (directory / 'config.json').exists() and read_json(directory / 'config.json') != config:
            raise ValueError(f'Existing configuration/provenance changed: {directory}')
        if (directory / 'run.json').exists():
            previous = read_json(directory / 'run.json')
            for key in ('schema_version', 'sample_id', 'method', 'config_id', 'seed', 'config_hash', 'input_sha256'):
                if previous.get(key) != state[key]:
                    raise ValueError(f'Existing run identity changed: {directory}')
            hashes = previous.get('artifact_sha256', {})
            if previous['status'] == 'complete' and hashes and all(
                    (directory / name).is_file() and file_digest(directory / name) == sha
                    for name, sha in hashes.items()):
                skipped += 1
                continue
            # A prior evaluation belongs to the previous artifact bytes.
            if (directory / 'metrics.json').exists():
                raise ValueError(f'Invalid artifacts have evaluated metrics; preserve audit before repair: {directory}')
        jobs.append((image, directory, state))
    print(dict(selected=len(inputs), queued=len(jobs), skipped=skipped, config_hash=config_hash), flush=True)
    if dry_run or not jobs:
        return 0
    for _, directory, state in jobs:
        atomic_json(directory / 'config.json', config)
        atomic_json(directory / 'run.json', state)
    start = time.perf_counter()
    backend.load()
    load_seconds = time.perf_counter() - start
    for index, (image, directory, state) in enumerate(jobs):
        print(f'[{index+1}/{len(jobs)}] {state["sample_id"]}', flush=True)
        atomic_json(directory / 'run.json', dict(state, status='running'))
        try:
            with (directory / 'inference.log').open('a', buffering=1) as log:
                with redirect_stdout(log), redirect_stderr(log):
                    artifacts = backend.infer(image, directory, seed)
            required = ['mesh.json', 'runtime.json'] + [a['path'] for a in artifacts.values()]
            hashes = {name: file_digest(directory / name) for name in required}
            atomic_json(directory / 'run.json', dict(state, status='complete', artifacts=artifacts,
                                                     artifact_sha256=hashes))
            (directory / 'error.txt').unlink(missing_ok=True)
        except Exception:
            error = traceback.format_exc()
            (directory / 'error.txt').write_text(error)
            atomic_json(directory / 'run.json', dict(state, status='failed', error=error))
            print(error, flush=True)
            # Stop at the first model/CUDA failure; a new process can resume.
            return 1
    atomic_json(root / identifier(summary_file), dict(selected=len(inputs), completed=len(jobs),
        skipped=skipped, model_load_seconds=load_seconds, config_hash=config_hash))
    return 0
