"""Batch scheduling and resume tests with tiny deterministic artifacts, no weights."""
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from wt.batch import run_batch, resolve_configs
from wt.experiment import WT_METHODS as METHODS, atomic_json, read_json, scan_experiment, run_directory


class FakeBackend:
    provenance = {'fixture': 'v1'}

    def __init__(self):
        self.calls = []
        self.fail_mesh = False

    def load_wt(self):
        self.calls.append('load_wt')

    def unload_wt(self):
        self.calls.append('unload_wt')

    def load_trellis(self, **kwargs):
        self.calls.append(('load_trellis', kwargs))

    def unload_trellis(self):
        self.calls.append('unload_trellis')

    def recover(self):
        pass

    def predict_wt(self, image, cfg, seed, directory):
        self.calls.append(('wt', image.name, cfg['bg_color'], seed))
        np.savez(directory / 'prediction.npz', xyz=np.ones((2, 3, 4, 3)),
                 mask=np.ones((2, 3, 4), dtype=bool), rgb=np.zeros((3, 4, 3), dtype=np.uint8))
        Image.open(image).save(directory / 'rgba.png')

    def generate_mesh(self, image, cfg, seed, directory, parent):
        import trimesh
        self.calls.append(('mesh', image.name, cfg['method'], seed, parent))
        if self.fail_mesh and image.stem == 'b':
            raise ValueError('synthetic failure')
        trimesh.creation.box().export(directory / 'mesh.glb')
        atomic_json(directory / 'mesh.json', {'canonical_transform': {
            'centroid': [0, 2, 0], 'scale': 2, 'axis_map': 'cam2canonical_zup'}})
        return {'mesh': {'path': 'mesh.glb', 'kind': 'mesh', 'frame': 'gltf_yup', 'metadata': 'mesh.json'}}


def make_inputs(tmp_path):
    result = []
    for index, name in enumerate(('a', 'b')):
        path = tmp_path / f'{name}.png'
        Image.new('RGBA', (8, 8), (30 + index, 60, 90, 255)).save(path)
        result.append(dict(sample_id=name, image=str(path)))
    return result


def test_model_reuse_cache_separation_and_resume(tmp_path):
    backend = FakeBackend()
    root = tmp_path / 'experiment'
    configs = [dict(method=m) for m in METHODS]
    configs.append(dict(method='wt_trellis2', config_id='shared-wt-v1', bg_color=[128]*3, alpha_erode=0))
    inputs = make_inputs(tmp_path)
    assert run_batch(root, inputs, configs, [42, 43], backend) == 0
    assert backend.calls.count('load_wt') == 1
    assert sum(isinstance(c, tuple) and c[0] == 'load_trellis' for c in backend.calls) == 1
    wt_calls = [c for c in backend.calls if isinstance(c, tuple) and c[0] == 'wt']
    assert len(wt_calls) == 8  # two inputs x two preprocessing recipes x two seeds
    meshes = [c for c in backend.calls if isinstance(c, tuple) and c[0] == 'mesh']
    assert len(meshes) == 12
    assert all((call[4] is None) == (call[2] == 'trellis2') for call in meshes)
    assert backend.calls.index('unload_wt') < next(i for i, c in enumerate(backend.calls)
                                                if isinstance(c, tuple) and c[0] == 'load_trellis')
    samples, runs, errors = scan_experiment(root)
    assert len(samples) == 2 and len(runs) == 16 and not errors
    assert all(r.data['status'] == 'complete' for r in runs)
    for sample in samples:
        assert not (run_directory(root, sample, 'trellis2', 'defaults-v1', 42) / 'wt_parent.json').exists()
        standalone = run_directory(root, sample, 'wt', 'defaults-v1', 42) / 'prediction.npz'
        shared = run_directory(root, sample, 'wt_trellis2', 'shared-wt-v1', 42)
        parent = read_json(shared / 'wt_parent.json')
        assert standalone.read_bytes() == (shared / parent['path']).read_bytes()
    backend.calls.clear()
    assert run_batch(root, inputs, configs, [42, 43], backend) == 0
    assert backend.calls == []  # no model load on fully completed resume
    # Different config under the same ID must fail before any overwrite/load.
    old = (runs[0].directory / 'run.json').read_bytes()
    with pytest.raises(ValueError, match='changed'):
        run_batch(root, inputs, [dict(method='wt', wt_steps=10)], [42], backend)
    assert backend.calls == [] and (runs[0].directory / 'run.json').read_bytes() == old


def test_failed_sample_retry_and_missing_artifact_resume(tmp_path):
    backend = FakeBackend()
    backend.fail_mesh = True
    root = tmp_path / 'experiment'
    inputs = make_inputs(tmp_path)
    configs = [dict(method='trellis2')]
    assert run_batch(root, inputs, configs, [42], backend) == 1
    _, runs, _ = scan_experiment(root)
    assert [r.data['status'] for r in runs] == ['complete', 'failed']
    backend.calls.clear()
    backend.fail_mesh = False
    assert run_batch(root, inputs, configs, [42], backend) == 0
    assert len([c for c in backend.calls if isinstance(c, tuple) and c[0] == 'mesh']) == 1
    (run_directory(root, 'a', 'trellis2', 'defaults-v1', 42) / 'mesh.glb').unlink()
    backend.calls.clear()
    assert run_batch(root, inputs, configs, [42], backend) == 0
    assert len([c for c in backend.calls if isinstance(c, tuple) and c[0] == 'mesh']) == 1


@pytest.mark.parametrize('cfg', [dict(method='wt', wt_steps=0), dict(method='wt', wat=3),
    dict(method='wt', config_id='../escape'), dict(method='wt', bg_color=[0, 0, 300])])
def test_invalid_configs(cfg):
    with pytest.raises(ValueError):
        resolve_configs([cfg])


def test_wt_load_failure_does_not_block_native_trellis(tmp_path):
    class BrokenWT(FakeBackend):
        def load_wt(self):
            raise ValueError('checkpoint unavailable')
    backend = BrokenWT()
    root = tmp_path / 'experiment'
    assert run_batch(root, make_inputs(tmp_path), [dict(method=m) for m in METHODS], [42], backend) == 4
    _, runs, _ = scan_experiment(root)
    assert all(r.data['status'] == ('complete' if r.method == 'trellis2' else 'failed') for r in runs)


def test_real_backend_wt_export_contract_with_synthetic_prediction(monkeypatch, tmp_path):
    import torch
    from wt.batch import InferenceBackend
    import wt.inference

    backend = InferenceBackend.__new__(InferenceBackend)
    backend.device = torch.device('cpu')
    backend.model = torch.nn.Linear(1, 1)
    backend.model_cfg = dict(image_size=8, inference_kwargs={})
    calls = []

    def predict(model, rgb, **kwargs):
        calls.append(kwargs)
        assert rgb.shape == (1, 3, 8, 8)
        return torch.ones((1, 6, 8, 8, 3)), kwargs['gt_mask'], None

    monkeypatch.setattr(wt.inference, 'inference_diffusion', predict)
    inputs = make_inputs(tmp_path)
    cfg = resolve_configs([dict(method='wt')])[0]
    backend.predict_wt(Path(inputs[0]['image']), cfg, 42, tmp_path)
    with np.load(tmp_path / 'prediction.npz') as output:
        assert output['xyz'].shape == (6, 8, 8, 3)
        assert output['mask'].shape == (6, 8, 8)
        assert output['rgb'].shape == (8, 8, 3)
        assert output['intrinsics'].shape == (3, 3)
    assert calls[0]['num_steps'] == 20
    assert (tmp_path / 'rgba.png').is_file()


def test_random_streams_independent_of_previous_samples():
    import random
    import torch
    from wt.batch import InferenceBackend
    def draw():
        return random.random(), np.random.rand(), torch.rand(3)
    InferenceBackend.reset_seed(42)
    expected = draw()
    InferenceBackend.reset_seed(123)
    draw()
    InferenceBackend.reset_seed(42)
    actual = draw()
    assert actual[:2] == expected[:2]
    assert torch.equal(actual[2], expected[2])
