import numpy as np
import pytest
from PIL import Image

from evaluation.camera_ablation import (
    camera_match, crop_transform, fixed_crop_intrinsics, framed_camera,
    frozen_mesh_image, frozen_spatial_spec, frozen_wt_image, training_intrinsics,
)
from evaluation.render import make_camera
from wt.data import preprocess_rgba_for_model


def test_fixed_crop_changes_only_intrinsics_and_reaches_target():
    rgba = np.zeros((1024, 1024, 4), dtype=np.uint8)
    rgba[215:815, 300:700] = [30, 100, 180, 255]
    spatial = frozen_spatial_spec(rgba)
    original = make_camera(35)
    K = fixed_crop_intrinsics(original, spatial)
    actual = crop_transform(spatial["wt_crop_y_x_side"]) @ K
    np.testing.assert_allclose(actual, training_intrinsics(504), atol=1e-12)
    assert camera_match(actual)["passed"]
    assert original == make_camera(35)


@pytest.mark.parametrize("background,erosion", [((128, 128, 128), 0), ((0, 0, 0), 2)])
def test_frozen_wt_control_is_pixel_identical(background, erosion):
    rgba = np.zeros((1024, 1024, 4), dtype=np.uint8)
    rgba[180:780, 330:730] = [79, 123, 240, 255]
    spatial = frozen_spatial_spec(rgba)
    kwargs = dict(image_size=504, num_layers=6, bg_color=background, alpha_erode_px=erosion)
    original = preprocess_rgba_for_model(rgba, center_crop=True, **kwargs)
    frozen = preprocess_rgba_for_model(frozen_wt_image(rgba, spatial), center_crop=False, **kwargs)
    for a, b in zip(original, frozen):
        np.testing.assert_array_equal(a.numpy(), b.numpy())


def test_frozen_mesh_uses_control_crop_when_foreground_changes():
    control = np.zeros((1024, 1024, 4), dtype=np.uint8)
    control[200:800, 200:800] = [100, 150, 200, 255]
    matched = np.zeros_like(control)
    matched[350:650, 350:650] = [100, 150, 200, 255]
    spatial = frozen_spatial_spec(control)
    for method in ("trellis2", "pixal3d"):
        a = frozen_mesh_image(Image.fromarray(control), spatial, method)
        b = frozen_mesh_image(Image.fromarray(matched), spatial, method)
        assert a.size == b.size
        assert np.count_nonzero(np.asarray(b)[..., 0]) < np.count_nonzero(np.asarray(a)[..., 0])


def test_framing_preserves_rotation_and_reaches_two_thirds():
    vertices = np.array([[x, y, z] for x in (-.3, .3) for y in (-.1, .1) for z in (-.2, .2)])
    original = make_camera(37)
    camera, diagnostics = framed_camera(vertices, original)
    transform = np.array(camera["T_world_to_camera"])
    np.testing.assert_array_equal(transform[:3, :3], np.array(original["T_world_to_camera"])[:3, :3])
    xyz = vertices @ transform[:3, :3].T + transform[:3, 3]
    assert xyz[:, 2].min() > 0
    pixels = xyz @ np.array(camera["K"]).T
    pixels = pixels[:, :2] / pixels[:, 2:3]
    np.testing.assert_allclose((pixels.max(0) + pixels.min(0)) / 2, [512, 512], atol=1e-5)
    assert max(np.ptp(pixels, axis=0)) == pytest.approx(1024 * 2 / 3, abs=1e-5)
    assert max(np.abs(diagnostics["solver_residual_pixels"])) < 1e-5


def test_preprocessor_restores_on_failure():
    from wt.camera_ablation import fixed_mesh_preprocessing
    class Pipeline:
        def preprocess_image(self, image):
            return image
    pipeline = Pipeline()
    original = pipeline.preprocess_image
    rgba = np.zeros((1024, 1024, 4), dtype=np.uint8)
    rgba[200:800, 200:800] = 255
    with pytest.raises(RuntimeError):
        with fixed_mesh_preprocessing(pipeline, frozen_spatial_spec(rgba), "trellis2"):
            assert pipeline.preprocess_image(Image.fromarray(rgba)).mode == "RGB"
            raise RuntimeError("inference failed")
    assert pipeline.preprocess_image == original


def test_summary_keeps_hybrid_configurations_separate(tmp_path):
    from evaluation.camera_summary import summary
    from wt.experiment import atomic_json, file_digest
    plan, index = [], []
    for configuration, score in [("defaults-v1", .1), ("shared-wt-v1", .2)]:
        candidate = dict(sample_id="asset", method="wt_trellis2", config_id=configuration,
                         seed=42, stage="decoded")
        record = dict(candidate, revision="test", status="complete",
                      shape={"cd_euclidean_mean": score}, registration={"matrix": np.eye(4).tolist()},
                      comparisons={})
        path = tmp_path / (configuration + ".json")
        atomic_json(path, record)
        plan.append(candidate)
        index.append(dict(candidate, result_path=str(path), result_sha256=file_digest(path)))
    atomic_json(tmp_path / "plan.json", {"config": {"report_single_seed": 42}, "candidates": plan})
    atomic_json(tmp_path / "index.json", {"revision": "test", "results": index})
    report = summary(tmp_path)
    assert report["evaluated_stages"] == 2
    assert report["pending_stages"] == 0
    values = {r["method"]: r["metrics"]["shape.cd_euclidean_mean"]["mean"] for r in report["groups"]}
    assert values == {"wt_trellis2/defaults-v1": .1, "wt_trellis2/shared-wt-v1": .2}
    atomic_json(tmp_path / "index.json", {"revision": "test", "results": index[:1]})
    assert summary(tmp_path)["pending_stages"] == 1
