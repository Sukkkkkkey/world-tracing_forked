"""Boundary regressions for WT geometry injected into TRELLIS.2."""
from types import SimpleNamespace
import sys
from types import ModuleType

import numpy as np
from PIL import Image
import pytest
import torch

from wt.textured_mesh import (
    aggregate_camera_cloud, canon_inverse, compute_canonical_transform,
    expand_cloud_ray_xyz, inject_coords_into_trellis2, v4_ray_fill,
    save_mesh_glb,
)


class RecordingPipeline:
    device = "cpu"

    def __init__(self):
        self.models = {f"{kind}_slat_flow_model_{res}": f"{kind}-{res}"
                       for kind in ("shape", "tex") for res in (512, 1024)}
        self.calls = []

    def preprocess_image(self, image):
        self.calls.append(("preprocess",))
        return image.convert("RGB")

    def get_cond(self, images, res):
        self.image = images[0]
        return {"resolution": res}

    def sample_shape_slat(self, cond, model, coords, params):
        self.calls.append(("shape", model, cond, params))
        self.coords = coords
        return "shape-latent"

    def sample_shape_slat_cascade(self, low_cond, cond, low_model, model,
                                  low_res, res, coords, params, max_tokens):
        self.calls.append(("cascade", low_model, model, low_res, res, params, max_tokens))
        self.coords = coords
        # Upstream may lower 1536 to 1024; decode must use returned resolution.
        return "shape-latent", 1024

    def sample_tex_slat(self, cond, model, shape, params):
        assert shape == "shape-latent"
        self.calls.append(("texture", model, cond, params))
        return "texture-latent"

    def decode_latent(self, shape, texture, res):
        assert (shape, texture) == ("shape-latent", "texture-latent")
        self.calls.append(("decode", res))
        return [SimpleNamespace(resolution=res)]


@pytest.mark.parametrize("mode,grid,shape,texture,decoded", [
    ("512", 32, "shape-512", "tex-512", 512),
    ("1024", 64, "shape-1024", "tex-1024", 1024),
    ("1024_cascade", 32, "shape-512", "tex-1024", 1024),
    ("1536_cascade", 32, "shape-512", "tex-1024", 1024),
])
def test_injection_routes_grid_conditions_and_sampler_controls(mode, grid, shape, texture, decoded):
    pipeline = RecordingPipeline()
    xyz = np.array([[0, 1, 2], [grid - 1] * 3], dtype=np.int32)
    result = inject_coords_into_trellis2(
        pipeline, Image.new("RGB", (8, 8)), xyz, pipeline_type=mode, ss_res=grid,
        shape_slat_sampler_params={"steps": 2}, tex_slat_sampler_params={"steps": 3},
        max_num_tokens=777,
    )
    assert result[0].resolution == decoded
    assert pipeline.coords.dtype == torch.int32
    np.testing.assert_array_equal(pipeline.coords[:, 1:], xyz)
    assert not pipeline.coords[:, 0].any()
    assert pipeline.calls[0] == ("preprocess",)
    assert pipeline.calls[1][1] == shape
    assert pipeline.calls[-2][1] == texture
    assert pipeline.calls[-2][-1] == {"steps": 3}
    if "cascade" in mode:
        assert pipeline.calls[1][-2:] == ({"steps": 2}, 777)
        assert pipeline.calls[1][3] == 512
    else:
        assert pipeline.calls[1][-1] == {"steps": 2}


@pytest.mark.parametrize("coords,kwargs", [
    (np.empty((0, 3), dtype=int), {}),
    (np.zeros((1, 2), dtype=int), {}),
    (np.array([[0.5, 1, 2]]), {}),
    (np.array([[np.nan, 1, 2]]), {}),
    (np.array([[-1, 1, 2]]), {}),
    (np.array([[32, 1, 2]]), {}),
    (np.array([[1, 0, 1, 2]]), {}),
    (np.zeros((2, 3), dtype=int), {}),
    (np.zeros((1, 3), dtype=int), {"ss_res": 64}),
    (np.zeros((1, 3), dtype=int), {"shape_slat_sampler_params": {"steps": 0}}),
])
def test_bad_coords_fail_before_model_execution(coords, kwargs):
    pipeline = RecordingPipeline()
    with pytest.raises(ValueError):
        inject_coords_into_trellis2(pipeline, Image.new("RGB", (8, 8)), coords,
                                   pipeline_type="1024_cascade", **kwargs)
    assert not pipeline.calls


def test_skip_crop_still_composites_hidden_rgb_and_accepts_batch_column():
    rgba = np.full((8, 8, 4), 255, dtype=np.uint8)
    rgba[0, 0, 3] = 0
    pipeline = RecordingPipeline()
    inject_coords_into_trellis2(pipeline, Image.fromarray(rgba), np.array([[0, 1, 2, 3]]),
                               pipeline_type="512", preprocess_image=False)
    assert pipeline.image.mode == "RGB"
    assert pipeline.image.getpixel((0, 0)) == (0, 0, 0)
    assert pipeline.image.getpixel((1, 1)) == (255, 255, 255)


def test_empty_foreground_rejected():
    with pytest.raises(ValueError, match="foreground"):
        inject_coords_into_trellis2(RecordingPipeline(), Image.new("RGBA", (8, 8)),
                                   np.array([[1, 2, 3]]))


def test_random_geometry_roundtrip_finite_voxelisation_and_deterministic_cap():
    rng = np.random.default_rng(42)
    xyz = rng.normal(size=(3, 12, 12, 3)).astype(np.float32)
    mask = rng.random(xyz.shape[:-1]) > 0.2
    xyz[0, 0, 0] = np.nan
    mask[0, 0, 0] = True
    cloud = aggregate_camera_cloud(xyz, mask)
    transform = compute_canonical_transform(cloud)
    canonical = transform.apply(cloud)
    np.testing.assert_allclose(canon_inverse(canonical, transform), cloud, atol=1e-6)
    assert np.max(np.abs(canonical)) <= 0.450001
    assert np.isfinite(expand_cloud_ray_xyz(xyz, mask)).all()
    first, raw = v4_ray_fill(xyz, mask, transform.apply, res=32, max_voxels=32, seed=42)
    second, _ = v4_ray_fill(xyz, mask, transform.apply, res=32, max_voxels=32, seed=42)
    np.testing.assert_array_equal(first, second)
    assert raw >= len(first) == 32 and first.min() >= 0 and first.max() < 32


def test_nonfinite_cloud_rejected_before_fitting():
    with pytest.raises(ValueError, match="nonfinite"):
        compute_canonical_transform(np.array([[np.nan, 0, 1]]))


def test_empty_or_nonfinite_mesh_is_not_silently_exported(tmp_path):
    mesh = SimpleNamespace(vertices=torch.empty(0, 3), faces=torch.empty(0, 3))
    with pytest.raises(ValueError, match="empty"):
        save_mesh_glb(tmp_path / "empty.glb", mesh)
    mesh.vertices = torch.zeros(3, 3)
    mesh.faces = torch.tensor([[0, 1, 2]])
    mesh.attrs = torch.tensor([[float("nan")]])
    with pytest.raises(ValueError, match="nonfinite"):
        save_mesh_glb(tmp_path / "invalid.glb", mesh)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("include_stage1", [False, True])
@pytest.mark.parametrize("mode,expected", [
    ("512", {"shape_slat_flow_model_512", "tex_slat_flow_model_512"}),
    ("1024", {"shape_slat_flow_model_1024", "tex_slat_flow_model_1024"}),
    ("1024_cascade", {"shape_slat_flow_model_512", "shape_slat_flow_model_1024", "tex_slat_flow_model_1024"}),
])
def test_local_loader_excludes_unused_models_without_mutating_upstream(monkeypatch, tmp_path, mode, expected, include_stage1):
    from wt.textured_mesh import pipeline as bridge

    class Upstream:
        model_names_to_load = ["sparse_structure_flow_model"]

        @classmethod
        def from_pretrained(cls, path):
            instance = cls()
            instance.loaded_path = path
            return instance

        def to(self, device):
            self.device = device

    module = ModuleType("trellis2.pipelines")
    module.Trellis2ImageTo3DPipeline = Upstream
    monkeypatch.setitem(sys.modules, "trellis2.pipelines", module)
    monkeypatch.setattr(bridge, "WEIGHTS_ROOT", tmp_path)
    local = tmp_path / "local-pipelines/TRELLIS.2"
    local.mkdir(parents=True)
    (local / "pipeline.json").write_text("{}")
    pipeline = bridge.load_trellis2_pipeline(device="cpu", pipeline_type=mode, include_stage1=include_stage1)
    if include_stage1:
        expected = expected | {"sparse_structure_flow_model", "sparse_structure_decoder"}
    assert pipeline.loaded_path == str(local)
    assert set(pipeline.model_names_to_load) == expected | {"shape_slat_decoder", "tex_slat_decoder"}
    assert Upstream.model_names_to_load == ["sparse_structure_flow_model"]
