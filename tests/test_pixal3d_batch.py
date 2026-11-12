from pathlib import Path

import pytest

from wt.baselines.pixal3d_batch import run_batch
from wt.experiment import atomic_json, file_digest, read_json, run_directory, scan_experiment


class Backend:
    provenance = {'source': 'frozen'}

    def __init__(self, fail=False):
        self.loads = 0
        self.calls = []
        self.fail = fail

    def load(self):
        self.loads += 1

    def infer(self, image, directory, seed):
        self.calls.append(image)
        if self.fail:
            raise RuntimeError('synthetic GPU failure')
        (directory / 'mesh.glb').write_bytes(b'mesh')
        atomic_json(directory / 'mesh.json', {})
        atomic_json(directory / 'runtime.json', {})
        return {'mesh': {'path': 'mesh.glb', 'kind': 'mesh', 'frame': 'gltf_yup'}}


def experiment(tmp_path):
    root = tmp_path / 'experiment'
    atomic_json(root / 'experiment.json', dict(schema_version=1, experiment_id='experiment'))
    for name in ('a', 'b'):
        image = tmp_path / (name + '.png')
        image.write_bytes(name.encode())
        atomic_json(root / 'samples' / name / 'input.json', dict(sample_id=name, image=str(image),
            sha256=file_digest(image), evaluation_dir='/frozen/gt', custom_metadata={'preserve': True}))
    return root


def test_append_resume_and_corrupt_artifact_repair_preserve_frozen_inputs(tmp_path):
    root = experiment(tmp_path)
    original = {p: p.read_bytes() for p in root.rglob('*.json')}
    backend = Backend()
    assert run_batch(root, backend) == 0
    assert backend.loads == 1 and len(backend.calls) == 2
    assert all(p.read_bytes() == data for p,data in original.items())
    samples, runs, errors = scan_experiment(root)
    assert len(samples) == 2 and len(runs) == 2 and not errors
    assert all(r.method == 'pixal3d' and not (r.directory / 'wt_parent.json').exists() for r in runs)
    resumed = Backend()
    assert run_batch(root, resumed) == 0 and resumed.loads == 0
    (runs[0].directory / 'mesh.glb').write_bytes(b'corrupt')
    assert run_batch(root, resumed) == 0 and len(resumed.calls) == 1


def test_preflight_conflicts_and_dry_run_do_not_create_results(tmp_path):
    root = experiment(tmp_path)
    backend = Backend()
    assert run_batch(root, backend, dry_run=True) == 0
    assert not list(root.rglob('run.json')) and backend.loads == 0
    (tmp_path / 'b.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='Frozen input changed'):
        run_batch(root, backend)
    assert not list(root.rglob('run.json'))


def test_failure_stops_and_resume_retries_without_touching_other_methods(tmp_path):
    root = experiment(tmp_path)
    old = root / 'samples/a/trellis2/defaults-v1/seed-0042/keep.txt'
    old.parent.mkdir(parents=True)
    old.write_bytes(b'original result')
    backend = Backend(fail=True)
    assert run_batch(root, backend) == 1 and len(backend.calls) == 1
    states = [read_json(p)['status'] for p in sorted(root.rglob('run.json'))]
    assert states == ['failed', 'planned']
    assert run_batch(root, Backend()) == 0
    assert old.read_bytes() == b'original result'
    changed = Backend()
    changed.provenance = {'source': 'different'}
    with pytest.raises(ValueError, match='configuration/provenance changed'):
        run_batch(root, changed)


def test_four_method_common_success_uses_explicit_config_pairs():
    from evaluation.records import summarize
    pairs = [('wt','defaults-v1'), ('trellis2','defaults-v1'),
             ('wt_trellis2','defaults-v1'), ('pixal3d','resolution1024-v1')]
    records = [dict(method=m,config_id=c,seed=42,protocol_id='gso-shape-sim3-v1',
                    metric='f@0.01',sample_id=s,status='complete',value=1.)
               for m,c in pairs for s in ('a','b') if not (m=='pixal3d' and s=='b')]
    totals = {(m,c,42): 2 for m,c in pairs}
    old = summarize(records,totals)
    assert next(r for r in old if r['method']=='wt')['common_count'] == 2
    four = summarize(records,totals,shape_comparison=pairs)
    assert all(r['common_count']==1 for r in four)
    assert next(r for r in four if r['method']=='pixal3d')['pending']==1


def test_pixal_decoder_and_export_display_frames_agree():
    import numpy as np
    from viewer import display_transform
    # O-Voxel swaps Y/Z first; official Pixal export applies a second rotation.
    ovoxel = np.array([[1,0,0],[0,0,1],[0,-1,0]])
    pixal = np.array([[-1,0,0],[0,0,-1],[0,-1,0]])
    np.testing.assert_array_equal(display_transform('pixal3d_yup')[:3,:3], pixal @ ovoxel)
    assert np.linalg.det(pixal @ ovoxel) == 1


def test_old_runner_rejects_pixal_instead_of_treating_it_as_wt():
    from wt.batch import resolve_configs
    with pytest.raises(ValueError, match='Unknown method'):
        resolve_configs([dict(method='pixal3d')])


def test_gpu_shards_are_disjoint_and_cover_frozen_queue():
    from examples.infer_pixal3d_batch import shard_inputs
    shards = shard_inputs(list('abcdefghij'), ['0','1','2','3'])
    values = [s for _,ids in shards for s in ids]
    assert len(values) == len(set(values)) == 10 and sorted(values) == list('abcdefghij')
    assert len(shard_inputs(['a'],['0','1'])) == 1
    with pytest.raises(ValueError):
        shard_inputs(['a'],['0','0'])
