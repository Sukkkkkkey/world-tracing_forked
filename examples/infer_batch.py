"""Run an image directory through persistent WT and TRELLIS stages, with resumable outputs."""
import argparse
import fcntl
import json
from pathlib import Path

from wt.batch import InferenceBackend, run_batch
from wt.experiment import WT_METHODS as METHODS
from wt.paths import WEIGHTS_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input-dir', type=Path, help='Flat directory of input images')
    source.add_argument('--inputs', type=Path, help='JSONL with sample_id/image; paths relative to JSONL')
    parser.add_argument('--out', required=True, type=Path, help='Experiment root')
    parser.add_argument('--ckpt', type=Path, help='Local r75b checkpoint; required for WT/hybrid')
    parser.add_argument('--trellis-model', type=Path, default=WEIGHTS_ROOT / 'local-pipelines/TRELLIS.2')
    parser.add_argument('--configs', type=Path, help='JSON list of method/config_id and parameter overrides')
    parser.add_argument('--methods', choices=METHODS, nargs='+', default=list(METHODS))
    parser.add_argument('--seeds', type=int, nargs='+', default=[42])
    args = parser.parse_args()
    configs = json.loads(args.configs.read_text()) if args.configs else [dict(method=m) for m in args.methods]
    if any(c['method'] != 'trellis2' for c in configs) and (not args.ckpt or not args.ckpt.is_file()):
        parser.error('--ckpt must point to a local r75b checkpoint')
    if args.input_dir:
        inputs = [dict(sample_id=p.stem, image=str(p.resolve())) for p in sorted(args.input_dir.iterdir())
                  if p.is_file() and p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')]
    else:
        inputs = []
        for line in args.inputs.read_text().splitlines():
            if line.strip():
                value = json.loads(line)
                path = Path(value['image'])
                value['image'] = str(path if path.is_absolute() else args.inputs.parent / path)
                if 'ground_truth' in value:
                    path = Path(value['ground_truth']['path'])
                    value['ground_truth']['path'] = str(path if path.is_absolute() else args.inputs.parent / path)
                inputs.append(value)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / '.writer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another batch writer is active in this experiment; use a separate output root')
        backend = InferenceBackend(args.ckpt, args.trellis_model)
        return int(run_batch(args.out, inputs, configs, args.seeds, backend) > 0)


if __name__ == '__main__':
    raise SystemExit(main())
