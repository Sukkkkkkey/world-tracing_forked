"""Append pinned Pixal3D runs to an existing frozen R1/P0/R2 experiment."""
import argparse
import fcntl
import os
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import multiprocessing

from wt.baselines.pixal3d import Pixal3DBackend
from wt.baselines.pixal3d_batch import run_batch
from wt.paths import WEIGHTS_ROOT


def shard_inputs(sample_ids, devices):
    if not devices or len(set(devices)) != len(devices) or any(not d.isdigit() for d in devices):
        raise ValueError('GPU devices must be unique nonnegative indices')
    return [(device, sample_ids[index::len(devices)]) for index,device in enumerate(devices)
            if sample_ids[index::len(devices)]]


def run_shard(manifest, root, sample_ids, seed, device):
    # Spawned processes initialize CUDA only after selecting their own GPU.
    os.environ['CUDA_VISIBLE_DEVICES'] = device
    with (root / f'pixal3d-gpu{device}.log').open('a', buffering=1) as log:
        with redirect_stdout(log), redirect_stderr(log):
            backend = Pixal3DBackend(manifest)
            return run_batch(root, backend, sample_ids, seed,
                             summary_file=f'pixal3d-batch-gpu{device}.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=WEIGHTS_ROOT / 'pixal3d/manifest.json')
    parser.add_argument('--sample-ids', nargs='+', help='Subset of existing sample IDs; default is all')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--dry-run', action='store_true', help='Validate frozen inputs/config/weights without inference or writes')
    parser.add_argument('--devices', nargs='+', help='Explicit GPU indices for disjoint sample workers; parent retains writer lock')
    args = parser.parse_args()
    if not (os.environ.get('STY') or os.environ.get('TMUX')):
        parser.error('Run in a dedicated screen/tmux session')
    if not (args.experiment / 'experiment.json').is_file():
        parser.error('--experiment must contain existing frozen inputs')
    with (args.experiment / '.writer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another writer is active in this experiment')
        backend = Pixal3DBackend(args.manifest)
        if args.devices and not args.dry_run:
            # Entire queue passes preflight before children write any results.
            run_batch(args.experiment, backend, args.sample_ids, args.seed, dry_run=True)
            ids = args.sample_ids or [p.parent.name for p in sorted((args.experiment / 'samples').glob('*/input.json'))]
            shards = shard_inputs(ids, args.devices)
            with ProcessPoolExecutor(max_workers=len(shards), mp_context=multiprocessing.get_context('spawn')) as pool:
                futures = [pool.submit(run_shard,args.manifest,args.experiment,ids,args.seed,device)
                           for device,ids in shards]
                return int(any([future.result() for future in futures]))
        return run_batch(args.experiment, backend, args.sample_ids, args.seed, args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
