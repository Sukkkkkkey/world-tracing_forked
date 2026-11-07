"""Validate appended Pixal3D artifacts and preserve the existing experiment audit."""
import argparse
import json
from pathlib import Path

import numpy as np
import trimesh

from wt.experiment import atomic_json, file_digest, read_json, resolve_reference, run_directory


def audit(root, before, sample_ids=None):
    errors, checked = [], []
    for name, checksum in before[root.name].items():
        if file_digest(root / name) != checksum:
            errors.append(f'Existing input/result changed: {name}')
    paths = sorted((root / 'samples').glob('*/input.json'))
    if sample_ids:
        known = {p.parent.name for p in paths}
        if set(sample_ids) - known:
            raise ValueError('Unknown sample ID')
        paths = [p for p in paths if p.parent.name in sample_ids]
    for path in paths:
        directory = run_directory(root, path.parent.name, 'pixal3d', 'resolution1024-v1', 42)
        try:
            state = read_json(directory / 'run.json')
            if state['status'] != 'complete':
                raise ValueError('Run is not complete')
            if (directory / 'wt_parent.json').exists():
                raise ValueError('Unexpected WT parent')
            if 'Sampling sparse structure (proj): 100%' not in (directory / 'inference.log').read_text():
                raise ValueError('No evidence of completed native sparse-structure sampling')
            sample = read_json(path)
            if state['input_sha256'] != sample['sha256'] or file_digest(resolve_reference(path.parent, sample['image'])) != sample['sha256']:
                raise ValueError('Frozen input checksum mismatch')
            for filename, checksum in state['artifact_sha256'].items():
                if file_digest(directory / filename) != checksum:
                    raise ValueError('Artifact checksum mismatch: ' + filename)
            mesh = trimesh.load(directory / 'decoded_mesh.ply', process=False)
            if not len(mesh.faces) or not np.isfinite(mesh.vertices).all() or np.linalg.norm(mesh.extents) <= 0:
                raise ValueError('Empty/nonfinite/degenerate decoded geometry')
            counts = dict(vertices=len(mesh.vertices), faces=len(mesh.faces))
            del mesh
            scene = trimesh.load(directory / 'mesh.glb', process=False, force='scene')
            if not scene.geometry or not np.isfinite(scene.bounds).all():
                raise ValueError('Invalid GLB scene')
            if not any(getattr(g.visual, 'material', None) is not None for g in scene.geometry.values()):
                raise ValueError('GLB has no material')
            del scene
            metrics = directory / 'metrics.json'
            if 'evaluation_dir' in sample:
                value = read_json(metrics)
                if value['evaluation_status'] != 'complete':
                    raise ValueError('GSO evaluation incomplete')
                for row in value['metrics']:
                    if row['protocol_id'] == 'gso-shape-sim3-v1':
                        if row['status'] != 'complete' or not np.isfinite(row['value']):
                            raise ValueError('Shape metric missing/nonfinite')
                    elif row['status'] != 'N/A':
                        raise ValueError('Unvalidated camera/depth protocol must be N/A')
            checked.append(dict(sample_id=sample['sample_id'], **counts))
        except Exception as exc:
            errors.append(f'{path.parent.name}: {type(exc).__name__}: {exc}')
    return dict(status='passed' if not errors else 'failed', experiment=root.name,
                expected=len(paths), checked=checked, errors=errors,
                preserved_legacy_records=len(before[root.name]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sample-ids', nargs='+')
    args = parser.parse_args()
    report = audit(args.experiment, read_json(args.before), args.sample_ids)
    atomic_json(args.out, report)
    print(json.dumps(report, indent=2))
    raise SystemExit(report['status'] != 'passed')
