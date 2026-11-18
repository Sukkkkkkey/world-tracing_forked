"""CPU smoke tests for the real sparse tensor, sampler and Hybrid batch routing."""
from contextlib import contextmanager
import os
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
import torch
from PIL import Image

from scripts.run_hybrid_ablation import execute_plan
from test_hybrid_ablation import FakeBackend, pilot
from wt.experiment import read_json
from wt.hybrid_ablation import parameters
from wt.textured_mesh.batched_cascade import pack_supports, sample_latents


class TinyFlow(torch.nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.in_channels = channels
        self.calls = []

    def forward(self, x, t, cond, concat_cond=None):
        self.calls.append((len(t), x.shape[0], cond.shape[0]))
        values = x.feats * 0.125 + cond[x.coords[:, 0].long(), 0, :]
        if concat_cond is not None:
            assert torch.equal(x.coords, concat_cond.coords)
            values = values + concat_cond.feats * 0.25
        return x.replace(values)


class TinyDecoder(torch.nn.Module):
    def upsample(self, low, upsample_times):
        assert upsample_times == 4
        coords = low.coords.clone()
        coords[:, 1:] *= 16
        return torch.cat([coords, coords])  # duplicates both within and across assets


class TinyPipeline:
    device = torch.device("cpu")
    low_vram = False
    def __init__(self):
        from trellis2.pipelines.samplers import FlowEulerGuidanceIntervalSampler
        self.shape_slat_sampler = self.tex_slat_sampler = FlowEulerGuidanceIntervalSampler(sigma_min=1e-5)
        self.shape_slat_sampler_params = self.tex_slat_sampler_params = dict(
            guidance_strength=2., guidance_interval=[0., 1.], guidance_rescale=0.1)
        self.shape_slat_normalization = self.tex_slat_normalization = dict(std=[1.25, .75], mean=[.2, -.1])
        self.models = dict(shape_slat_flow_model_512=TinyFlow(2), shape_slat_flow_model_1024=TinyFlow(2),
                           tex_slat_flow_model_1024=TinyFlow(4), shape_slat_decoder=TinyDecoder())
        self.image_batches = []
        self.preprocess_image = lambda image: image.convert("RGB")

    def get_cond(self, images, res):
        self.image_batches.append((res, len(images)))
        values = torch.tensor([im.getpixel((0, 0))[0] for im in images]).float()[:, None, None] / 255
        return dict(cond=values, neg_cond=torch.zeros_like(values))


def serial_reference(monkeypatch, pipeline, image, coords, seed, cfg):
    # Mesh representations import CUDA kernels at import time. The reference uses
    # the original dependency's two sampling methods only, with CPU model doubles.
    import sys
    import importlib.util
    import trellis2
    mesh_types = ModuleType("trellis2.representations")
    mesh_types.Mesh = mesh_types.MeshWithVoxel = object
    monkeypatch.setitem(sys.modules, mesh_types.__name__, mesh_types)
    path = Path(trellis2.__file__).parent / "pipelines/trellis2_image_to_3d.py"
    spec = importlib.util.spec_from_file_location("trellis2.pipelines._cpu_reference", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.Trellis2ImageTo3DPipeline
    torch.manual_seed(seed)
    lr, hr = (pipeline.get_cond([image], size) for size in (512, 1024))
    shape, res = model.sample_shape_slat_cascade(
        pipeline, lr, hr, pipeline.models["shape_slat_flow_model_512"],
        pipeline.models["shape_slat_flow_model_1024"], 512, 1024,
        pack_supports([coords], "cpu"), dict(steps=cfg["shape_steps"]), cfg["max_num_tokens"])
    assert res == 1024
    tex = model.sample_tex_slat(pipeline, hr, pipeline.models["tex_slat_flow_model_1024"],
                                shape, dict(steps=cfg["tex_steps"]))
    return shape, tex


def test_real_sampler_batch_matches_upstream_singletons(monkeypatch):
    cfg = dict(parameters("defaults-v1"), shape_steps=2, tex_steps=3)
    images = [Image.new("RGB", (4, 4), (v, 0, 0)) for v in (32, 127, 224)]
    xyz = [np.array([[1, 2, 3], [2, 4, 6], [6, 7, 8]][:n], np.int32) for n in (2, 3, 1)]
    seeds = [42, 7, 42]
    for order in ([0, 1, 2], [2, 0, 1]):
        pipe = TinyPipeline()
        shape, tex, lengths, rng_states = sample_latents(pipe, [images[i] for i in order],
                                             [xyz[i] for i in order], [seeds[i] for i in order], cfg)
        assert pipe.image_batches == [(512, 3), (1024, 3)]
        assert lengths == [len(xyz[i]) for i in order]
        for name, flow in pipe.models.items():
            if "flow_model" in name:
                assert flow.calls == [(3, 3, 3)] * (6 if "tex_" in name else 4)
        for slot, i in enumerate(order):
            ref = serial_reference(monkeypatch, TinyPipeline(), images[i], xyz[i], seeds[i], cfg)
            assert torch.equal(torch.get_rng_state(), rng_states[slot])
            for actual, expected in zip((shape[slot], tex[slot]), ref):
                assert torch.equal(actual.coords, expected.coords)
                torch.testing.assert_close(actual.feats, expected.feats, rtol=0, atol=0)
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "" and not torch.cuda.is_initialized()


class BatchedBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.batches = []
        self.current = None

    @contextmanager
    def prepare_batch(self, group):
        assert len({(j["dataset"], j["condition"], j["config_id"]) for j in group}) == 1
        self.current = [j["destination"] for j in group]
        self.batches.append(self.current)
        try:
            yield
        finally:
            self.current = None

    def generate_mesh(self, image, cfg, seed, directory, parent):
        assert str(directory) in self.current
        return super().generate_mesh(image, cfg, seed, directory, parent)


def test_frozen_groups_resume_and_tail(pilot):
    _, _, _, plan = pilot
    backend = BatchedBackend()
    assert execute_plan(plan, lambda: backend, lambda: None, batch_size=3) == 0
    assert len(backend.batches) == 24 * 7
    assert sorted(map(len, backend.batches)) == [2] * 24 + [3] * 144
    group = backend.batches[0]
    for directory in group:
        assert read_json(Path(directory) / "config.json")["hybrid_ablation"]["batch"]["actual_size"] == 3
    # Simulate one missing result in an otherwise completed group.
    import shutil
    shutil.rmtree(group[1])
    resume = BatchedBackend()
    assert execute_plan(plan, lambda: resume, lambda: None, batch_size=3) == 0
    assert resume.batches == [group] and resume.events.count("mesh") == 1
    with pytest.raises(ValueError, match="identity changed"):
        execute_plan(plan, lambda: BatchedBackend(), lambda: None, batch_size=2)

def test_frozen_camera_inputs_and_decode_ownership(monkeypatch, tmp_path):
    import wt.camera_ablation as camera
    from wt.hybrid_ablation_backend import HybridAblationBackend
    backend = HybridAblationBackend.__new__(HybridAblationBackend)
    backend.pipeline, backend.device = TinyPipeline(), torch.device("cpu")
    for name in ("reset_peak_memory_stats", "max_memory_allocated", "max_memory_reserved"):
        monkeypatch.setattr(torch.cuda, name, lambda device: 0)
    cfg = dict(parameters("defaults-v1"), shape_steps=2, tex_steps=2)
    jobs, crops = [], []
    def frozen(image, spatial, method):
        crops.append((image.getpixel((0, 0))[0], spatial, method))
        return image.convert("RGB")
    monkeypatch.setattr(camera, "spatial_record", lambda image: Path(image).parent.name)
    monkeypatch.setattr(camera, "frozen_mesh_image", frozen)
    for i, v in enumerate((31, 223)):
        parent = tmp_path / str(i)
        parent.mkdir()
        rgba = parent / "rgba.png"
        Image.new("RGBA", (3, 3), (v, 0, 0, 255)).save(rgba)
        mask = np.zeros((6, 504, 504), dtype=bool)
        points = np.zeros((*mask.shape, 3), dtype=np.float32)
        mask[0, 0, :i+1] = True
        points[0, 0, 1, 0] = .125
        np.savez_compressed(parent / "prediction.npz", xyz=points, mask=mask)
        jobs.append(dict(input={"image": str(rgba)}, seed=42, strategy="surface", parameters=cfg,
                         canonical_transform=dict(centroid=[0, 0, 0], scale=1, axis_map="identity"),
                         parent_directory=str(parent), destination=str(parent / "out")))
    seen = []
    def decode(shape, tex, res):
        seen.append((len(shape.coords), len(tex.coords), res))
        assert torch.equal(shape.coords, tex.coords) and (shape.coords[:, 0] == 0).all()
        return [len(shape.coords)]
    backend.pipeline.decode_latent = decode
    with backend.prepare_batch(jobs):
        assert backend.pipeline.image_batches == [(512, 2), (1024, 2)]
        for job in reversed(jobs):
            backend.configure_job(job)
            meshes, info = backend.hybrid_mesh(Path(job["parent_directory"]), cfg, {})
            assert meshes == [backend.cascade_tokens] and info["injected_voxels"] == meshes[0]
    assert crops == [(31, "0", "trellis2"), (223, "1", "trellis2")]
    assert seen == [(2, 2, 1024), (1, 1, 1024)] and backend.batch_latents is None
    assert not torch.cuda.is_initialized()
