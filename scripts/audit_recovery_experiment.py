"""Audit recovered runs against the frozen historical scope and actual artifacts."""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path

import numpy as np
import trimesh

from wt.batch import resolve_configs, wt_settings
from wt.experiment import atomic_json, digest, file_digest, read_json, resolve_reference, run_directory

SHAPE = {'cd_euclidean_mean', 'cd_squared_mean', 'f@0.01', 'f@0.05'}
DEPTH = {'mae', 'rmse', 'absrel', 'delta1', 'delta2', 'depth_coverage', 'silhouette_iou'}
PROTOCOLS = {'gso-shape-sim3-v1': SHAPE, 'gso-camera-native-v1': SHAPE, 'gso-depth-ssi-v1': DEPTH}


def audit(root, include_pixal=False):
    repo = Path(__file__).resolve().parents[1]
    recipe = read_json(repo / 'configs/recovery_experiments.json')
    spec = next(x for x in recipe['experiments'] if x['id'] == root.name)
    ids = (read_json(repo / 'configs/historical_gso_samples.json')[spec['split']]
           if 'split' in spec else recipe['qualitative_ids'])
    configs = resolve_configs(read_json(repo / spec['configs']))
    historical = read_json(repo / 'configs/historical_workbook_configs.json')
    wanted = {(sample, cfg['method'], cfg['config_id'], recipe['seed'])
              for sample in ids for cfg in configs}
    if include_pixal:
        wanted |= {(sample, 'pixal3d', 'resolution1024-v1', recipe['seed']) for sample in ids}
    errors, checked, quality_failures, fingerprints = [], [], [], {}
    source_versions, verified_samples = set(), set()
    dataset_checksums = {}
    samples = {p.parent.name: p for p in (root / 'samples').glob('*/input.json')}
    if set(samples) != set(ids):
        errors.append('Sample set differs from the frozen historical scope')
    paths = sorted((root / 'samples').glob('*/*/*/seed-*/run.json'))
    found = set()
    for path in paths:
        rel = path.relative_to(root / 'samples').parts
        identity = (rel[0], rel[1], rel[2], int(rel[3][5:]))
        if not include_pixal and identity[1] == 'pixal3d':
            continue
        found.add(identity)
        if identity not in wanted:
            errors.append('Unexpected run: ' + str(identity))
            continue
        directory = path.parent
        try:
            state = read_json(path)
            assert tuple(state[k] for k in ('sample_id', 'method', 'config_id', 'seed')) == identity
            assert state['status'] == 'complete', state.get('error', 'run incomplete')
            sample_path = samples[identity[0]]
            sample = read_json(sample_path)
            assert state['input_sha256'] == sample['sha256']
            assert file_digest(resolve_reference(sample_path.parent, sample['image'])) == sample['sha256']
            if identity[0] not in verified_samples and 'evaluation_dir' in sample:
                data_dir = Path(sample['evaluation_dir'])
                for name, checksum in sample['artifact_sha256'].items():
                    assert file_digest(data_dir / name) == checksum, 'Frozen ground truth/input changed: ' + name
                    dataset_checksums[str(data_dir / name)] = checksum
                verified_samples.add(identity[0])
            files = [path, directory / 'config.json', sample_path]
            stored_config = read_json(directory / 'config.json')
            historic = next(x for x in historical
                if x['identity'][:4] == [root.name, identity[1], identity[2], identity[3]])
            assert stored_config['parameters'] == historic['parameters'], 'Parameters differ from the original workbook'
            parameter_hash = hashlib.sha256(json.dumps(stored_config['parameters'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
            assert parameter_hash == historic['identity'][4], 'Workbook parameter identity changed'
            if identity[1] != 'pixal3d':
                config = read_json(directory / 'config.json')
                expected = next(c for c in configs if (c['method'], c['config_id']) == identity[1:3])
                assert config['parameters'] == expected, 'Resolved parameters changed'
                assert state['config_hash'] == digest(dict(config=expected, provenance=config['provenance']))
                source_versions.add(config['provenance']['sources'])
                assert config['provenance']['environment']['numpy'] == '1.26.4'
                assert config['provenance']['torch'] == '2.6.0+cu124'
                assert read_json(directory / 'runtime.json'), 'Runtime record missing'
                files.append(directory / 'runtime.json')
            for artifact in state['artifacts'].values():
                file = resolve_reference(directory, artifact['path'])
                assert file.is_file() and file.stat().st_size > 0, 'Missing/empty artifact'
                files.append(file)
            if identity[1] == 'wt':
                with np.load(directory / 'prediction.npz', allow_pickle=False) as data:
                    xyz, mask, K = data['xyz'], data['mask'], data['intrinsics']
                    assert xyz.shape == (6, 504, 504, 3) and mask.shape == xyz.shape[:-1]
                    assert mask.dtype == np.bool_ and mask.any() and np.isfinite(xyz[mask]).all()
                    assert K.shape == (3, 3) and np.isfinite(K).all() and K[0, 0] > 0 and K[1, 1] > 0
                    counts = dict(valid_points=int(mask.sum()))
                runtime = read_json(directory / 'runtime.json')
                cache_dir = root / '_cache/wt' / runtime['cache_key']
                assert read_json(cache_dir / 'complete.json') == runtime
                assert file_digest(directory / 'prediction.npz') == runtime['sha256']
                assert file_digest(cache_dir / 'prediction.npz') == runtime['sha256']
                assert file_digest(cache_dir / 'rgba.png') == runtime['rgba_sha256']
                files += [cache_dir / name for name in ('prediction.npz', 'rgba.png', 'complete.json')]
            else:
                mesh = trimesh.load(directory / 'decoded_mesh.ply', process=False)
                assert len(mesh.faces) and np.isfinite(mesh.vertices).all() and mesh.area > 0
                assert mesh.faces.min() >= 0 and mesh.faces.max() < len(mesh.vertices)
                counts = dict(vertices=len(mesh.vertices), faces=len(mesh.faces))
                del mesh
                scene = trimesh.load(directory / 'mesh.glb', process=False, force='scene')
                assert scene.geometry and np.isfinite(scene.bounds).all()
                assert any(getattr(g.visual, 'material', None) is not None for g in scene.geometry.values())
                del scene
                files.append(directory / 'mesh.json')
                if identity[1] == 'wt_trellis2':
                    parent = read_json(directory / 'wt_parent.json')
                    parent_file = resolve_reference(directory, parent['path']).resolve()
                    assert file_digest(parent_file) == parent['sha256']
                    assert parent['settings'] == wt_settings(expected)
                    cache = read_json(parent_file.parent / 'complete.json')
                    assert cache['sha256'] == parent['sha256']
                    assert file_digest(parent_file.parent / 'rgba.png') == cache['rgba_sha256']
                    assert 'canonical_transform' in read_json(directory / 'mesh.json')
                    if identity[2] == 'shared-wt-v1':
                        baseline = run_directory(root, identity[0], 'wt', 'defaults-v1', identity[3])
                        assert file_digest(baseline / 'prediction.npz') == parent['sha256'], 'Shared WT parent differs'
                    files.append(directory / 'wt_parent.json')
                    files += [parent_file, parent_file.parent / 'rgba.png', parent_file.parent / 'complete.json']
                else:
                    assert not (directory / 'wt_parent.json').exists(), 'Native method has a WT parent'
                if identity[1] == 'trellis2':
                    assert 'Sampling sparse structure: 100%' in (directory / 'run.log').read_text(), 'Native Stage 1 missing'
                if identity[1] == 'pixal3d':
                    for name, checksum in state['artifact_sha256'].items():
                        assert file_digest(directory / name) == checksum
            if 'split' in spec:
                value = read_json(directory / 'metrics.json')
                assert value['evaluation_status'] == 'complete'
                assert value['source_run_hash'] == file_digest(path)
                rows = value['metrics']
                assert len(rows) == 15
                assert {(r['protocol_id'], r['metric']) for r in rows} == {
                    (p, metric) for p, metrics in PROTOCOLS.items() for metric in metrics}
                for row in rows:
                    if identity[1] in ('trellis2', 'pixal3d') and row['protocol_id'] != 'gso-shape-sim3-v1':
                        assert row['status'] == 'N/A' and row['value'] is None
                    elif row['status'] == 'complete':
                        assert row['value'] is not None and np.isfinite(row['value'])
                    else:
                        assert row['protocol_id'] == 'gso-depth-ssi-v1' and row['metric'] in DEPTH - {'depth_coverage', 'silhouette_iou'}
                        assert row['status'] == 'failed' and row.get('reason'), 'Unexplained metric failure'
                        quality_failures.append(dict(run=list(identity), metric=row['metric'], reason=row['reason']))
                files += [directory / n for n in ('metrics.json', 'registration.json', 'evaluation_points.npz')]
            for file in set(files):
                fingerprints[str(file.relative_to(root))] = file_digest(file)
            checked.append(dict(run=list(identity), **counts))
            print('AUDIT', len(checked), '/', len(wanted), '/'.join(map(str, identity)), flush=True)
        except Exception as exc:
            errors.append(str(identity) + ': ' + type(exc).__name__ + ': ' + str(exc))
    if found != wanted:
        errors.append('Run coverage mismatch: missing=' + str(sorted(wanted - found)) + ', extra=' + str(sorted(found - wanted)))
    if len(source_versions) != 1:
        errors.append('WT source provenance is not identical across baseline runs')
    return dict(status='passed' if not errors else 'failed', experiment=root.name, expected=len(wanted),
                checked=checked, by_method=dict(Counter(x['run'][1] for x in checked)),
                quality_failures=quality_failures, artifact_sha256=fingerprints, dataset_sha256=dataset_checksums, errors=errors,
                auditor_sha256=file_digest(Path(__file__)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--include-pixal', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.experiment, args.include_pixal)
    atomic_json(args.out, report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('artifact_sha256', 'dataset_sha256', 'checked')}, indent=2))
    raise SystemExit(report['status'] != 'passed')
