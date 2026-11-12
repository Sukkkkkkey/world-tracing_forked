import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from evaluation.multiview import (
    cameras, compare_views, frame_metrics, point_normals, prepare_surfels,
    render_frame, render_views, voxel_points,
)
from evaluation.render import Rasterizer
from examples.evaluate_multiview import valid_result, verify_similarity
from wt.experiment import atomic_json, file_digest


@pytest.fixture
def config():
    return json.loads((Path(__file__).parents[1] / "configs/multiview.json").read_text())


def frame(depth=2.0, normal=(0, 0, -1)):
    return {"depth": np.full((16, 16), depth, dtype=np.float32),
            "mask": np.ones((16, 16), dtype=bool),
            "normals": np.broadcast_to(np.array(normal, np.float32), (16, 16, 3)).copy(),
            "normal_valid": np.ones((16, 16), dtype=bool)}


def test_self_and_depth_metric_formula(config):
    base = frame()
    own = frame_metrics(base, base, config)["metrics"]
    assert own["depth_mae"] == own["depth_rmse"] == own["normal_mean_angle"] == 0
    assert own["silhouette_iou"] == own["depth_coverage"] == own["normal_coverage"] == 1
    assert own["normal_psnr"] == 120
    shifted = frame_metrics(frame(2.1), base, config)["metrics"]
    assert shifted["depth_mae"] == pytest.approx(.1, abs=1e-6)
    assert shifted["depth_rmse"] == pytest.approx(.1, abs=1e-6)
    assert shifted["depth_absrel"] == pytest.approx(.05, abs=1e-6)
    assert shifted["depth_delta1"] == shifted["depth_delta2"] == 1
    angled = frame_metrics(frame(normal=(1, 0, 0)), base, config)["metrics"]
    assert angled["normal_mean_angle"] == pytest.approx(90)
    assert angled["normal_mse"] == pytest.approx(1 / 6)
    assert angled["normal_rmse"] == pytest.approx(np.sqrt(1 / 6))


def test_missing_geometry_retains_coverage_penalty(config):
    base, empty = frame(), frame()
    empty["mask"][:] = False
    metrics = frame_metrics(empty, base, config)["metrics"]
    assert metrics["depth_coverage"] == metrics["silhouette_iou"] == metrics["normal_coverage"] == 0
    for name in ("depth_mae", "depth_rmse", "depth_absrel", "depth_delta1", "depth_delta2"):
        assert metrics[name] is None
    empty["mask"][:8] = True
    metrics = frame_metrics(empty, base, config)["metrics"]
    assert metrics["silhouette_iou"] == metrics["depth_coverage"] == .5


def test_normal_validity_is_separate_from_depth(config):
    a, b = frame(), frame()
    a["normal_valid"][:] = False
    values = frame_metrics(a, b, config)["metrics"]
    assert values["depth_mae"] == 0
    assert values["depth_coverage"] == 1
    assert values["normal_coverage"] == 0
    assert values["normal_psnr"] is None


def test_all_four_views_required(config):
    reference = {key: np.stack([value] * 4) for key, value in frame().items()}
    predicted = {key: value.copy() for key, value in reference.items()}
    predicted["mask"][0] = False
    rows = {r["metric"]: r for r in compare_views(predicted, reference, config)["metrics"]}
    assert rows["depth_mae"]["status"] == "failed"
    assert rows["depth_mae"]["valid_views"] == 3
    assert rows["silhouette_iou"]["value"] == .75


def test_voxel_choice_is_order_independent_and_observed():
    points = np.array([[.004, .005, .005], [.006, .005, .005], [.024, .005, .005]])
    selected = voxel_points(points, .01)
    np.testing.assert_array_equal(selected, voxel_points(points[::-1], .01))
    assert len(selected) == 2
    assert all(any(np.array_equal(p, q) for q in points) for p in selected)
    assert selected[0, 0] == .004


def test_pca_plane_and_degenerate_line(config):
    u, v = np.meshgrid(np.arange(-5, 6) * .002, np.arange(-5, 6) * .002)
    points = np.c_[u.ravel(), v.ravel(), np.zeros(u.size)]
    normals, valid, _ = point_normals(points, config)
    assert valid.all()
    np.testing.assert_allclose(np.abs(normals[:, 2]), 1)
    line = np.c_[np.arange(20) * .001, np.zeros((20, 2))]
    assert not point_normals(line, config)[1].any()
    assert len(prepare_surfels(np.empty((0, 3)), config)["points"]) == 0


def test_registration_rejects_reflection_and_affine():
    matrix = np.eye(4)
    verify_similarity(matrix)
    matrix[0, 0] = -1
    with pytest.raises(ValueError, match="proper"):
        verify_similarity(matrix)
    matrix[0, 0] = 2
    with pytest.raises(ValueError, match="nonuniform"):
        verify_similarity(matrix)


def test_cache_requires_matching_artifact_bytes(tmp_path):
    artifact = tmp_path / "map.npz"
    artifact.write_bytes(b"first")
    record = {"status": "complete", "signature": "sig", "files": {"map.npz": file_digest(artifact)}}
    atomic_json(tmp_path / "result.json", record)
    assert valid_result(tmp_path, "sig") == record
    assert valid_result(tmp_path, "different") is None
    artifact.write_bytes(b"changed")
    assert valid_result(tmp_path, "sig") is None
    (tmp_path / "result.json").write_text("{")
    assert valid_result(tmp_path, "sig") is None


@pytest.fixture
def renderer():
    import torch
    if not torch.cuda.is_available():
        pytest.skip("CUDA required")
    return Rasterizer()


def test_native_face_depth_orientation_and_chunking(renderer, config):
    config = dict(config, resolution=64)
    view = cameras({"azimuth_degrees": 0}, config)[0]
    box = trimesh.creation.box(extents=[.5, .5, .5])
    a = render_frame(renderer, box, view, face_normals=True)
    renderer.max_faces_per_pass = 2
    b = render_frame(renderer, box, view, face_normals=True)
    np.testing.assert_array_equal(a["mask"], b["mask"])
    np.testing.assert_allclose(a["depth"], b["depth"], atol=1e-6)
    np.testing.assert_allclose(a["normals"], b["normals"], atol=1e-6)
    assert a["mask"].sum() > 100
    assert a["depth"][a["mask"]].min() > view["distance"] - .5
    np.testing.assert_allclose(np.linalg.norm(a["normals"][a["mask"]], axis=1), 1, atol=1e-6)
    flipped = box.copy()
    flipped.faces = flipped.faces[:, ::-1]
    c = render_frame(renderer, flipped, view, face_normals=True)
    np.testing.assert_allclose(a["normals"], c["normals"], atol=1e-6)


def test_surfel_depth_and_invalid_normal_fallback(renderer, config):
    config = dict(config, resolution=64, surfel_radius=.04)
    views = cameras({"azimuth_degrees": 0}, config)
    point = np.zeros((1, 3))
    surfels = {"points": point, "normals": np.array([[1., 0, 0]]), "normal_valid": np.ones(1, bool)}
    rendered = render_views(renderer, surfels, views, config, surfel=True)
    assert rendered["mask"].sum() > 0
    assert rendered["normal_valid"].sum() > 0
    fallback = prepare_surfels(point, config)
    rendered = render_views(renderer, fallback, views, config, surfel=True)
    assert rendered["mask"].sum() > 0
    assert rendered["normal_valid"].sum() == 0
    empty = prepare_surfels(np.empty((0, 3)), config)
    assert not render_views(renderer, empty, views, config, surfel=True)["mask"].any()


def test_summary_counts_runs_whose_evaluation_failed(config):
    from examples.evaluate_multiview import summarize
    planned = [
        {"method": "wt", "config_id": "a", "seed": 42, "config_hash": "h", "parameter_hash": "p", "sample_id": "s"},
        {"method": "trellis2", "config_id": "a", "seed": 42, "config_hash": "h", "parameter_hash": "p", "sample_id": "s"},
    ]
    result = summarize([], planned, config)
    assert result["expected_runs"] == 2
    assert result["complete_runs"] == 0
    from evaluation.multiview import METRIC_UNITS
    assert result["failed_metrics"] == 3 * len(METRIC_UNITS)
    assert all(row["total"] == 1 for row in result["summary"])
    assert all(row["mean"] is None for row in result["summary"])
    wt_native = [r for r in result["summary"]
                 if r["method"] == "wt" and r["protocol_id"] == config["mesh_protocol"]]
    assert all(row["N/A"] == 1 and row["failed"] == 0 for row in wt_native)
    assert all(not assets for assets in result["common_valid_assets"].values())


def test_analytic_camera_z_and_nearest_surface(renderer, config):
    config = dict(config, resolution=64)
    view = cameras({"azimuth_degrees": 37}, config)[0]
    transform = np.asarray(view["T_world_to_camera"])
    xy = np.array([[-.2, -.2], [.2, -.2], [.2, .2], [-.2, .2]])
    camera_vertices = np.vstack([np.c_[xy, np.full(4, z)] for z in (1.5, 2.0)])
    world_vertices = (camera_vertices - transform[:3, 3]) @ transform[:3, :3]
    mesh = trimesh.Trimesh(vertices=world_vertices,
                           faces=[[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], process=False)
    rendered = render_frame(renderer, mesh, view, face_normals=True)
    assert rendered["mask"][32, 32]
    assert rendered["depth"][32, 32] == pytest.approx(1.5, abs=1e-6)
    np.testing.assert_allclose(rendered["normals"][32, 32], [0, 0, -1], atol=1e-6)


def test_tilted_plane_depth_matches_pinhole_ray_intersection(renderer, config):
    config = dict(config, resolution=64)
    view = cameras({"azimuth_degrees": 13}, config)[0]
    transform = np.asarray(view["T_world_to_camera"])
    xy = np.array([[-.5, -.5], [.5, -.5], [.5, .5], [-.5, .5]])
    camera_vertices = np.c_[xy, 1.5 + .2 * xy[:, 0] + .15 * xy[:, 1]]
    world_vertices = (camera_vertices - transform[:3, 3]) @ transform[:3, :3]
    mesh = trimesh.Trimesh(vertices=world_vertices, faces=[[0, 1, 2], [0, 2, 3]], process=False)
    result = render_frame(renderer, mesh, view, face_normals=True)
    y, x = np.indices(result["mask"].shape)
    k = np.asarray(view["K"])
    ray_x = (x + .5 - k[0, 2]) / k[0, 0]
    ray_y = (y + .5 - k[1, 2]) / k[1, 1]
    expected = 1.5 / (1 - .2 * ray_x - .15 * ray_y)
    assert result["mask"].sum() > 100
    error = np.abs(result["depth"][result["mask"]] - expected[result["mask"]])
    # CUDA rasterization uses float32 barycentrics; triangle-edge pixels can
    # deviate by a few micro-units. Bound both the worst pixel and overall error.
    assert error.max() < 1e-5
    assert error.mean() < 5e-7


@pytest.mark.parametrize("different_parameters", [False, True])
def test_summary_groups_parameters_and_retains_provenance(config, different_parameters):
    from examples.evaluate_multiview import summarize
    from evaluation.multiview import METRIC_UNITS
    planned, records = [], []
    for method in ("wt", "trellis2"):
        for index, asset in enumerate(("a", "b")):
            state = {"sample_id": asset, "method": method, "config_id": "default", "seed": 42,
                     "config_hash": f"source-{index}", "parameter_hash": "same"}
            if different_parameters and method == "trellis2" and index == 1:
                state["parameter_hash"] = "changed"
            planned.append(state)
            metrics = []
            for protocol in (config["mesh_protocol"], config["surfel_protocol"]):
                na = method == "wt" and protocol == config["mesh_protocol"]
                metrics.extend({"protocol_id": protocol, "metric": metric, "value": None if na else 1.,
                                "status": "N/A" if na else "complete"} for metric in METRIC_UNITS)
            records.append(dict(state, metrics=metrics, comparisons={}))
    result = summarize(records, planned, config)
    selected = [r for r in result["summary"] if r["method"] == "trellis2"
                and r["protocol_id"] == config["surfel_protocol"] and r["metric"] == "depth_mae"]
    assert len(selected) == (2 if different_parameters else 1)
    assert sum(r["total"] for r in selected) == 2
    if not different_parameters:
        assert selected[0]["source_config_hashes"] == ["source-0", "source-1"]
    assert len(result["common_valid_assets"][config["surfel_protocol"]]) == (0 if different_parameters else 2)


def test_spherical_hammersley_cameras_cover_both_hemispheres(config):
    spherical = dict(config, camera_layout="sphere-hammersley", view_count=30,
                     polar_offset=.5)
    views = cameras({"azimuth_degrees": 37.}, spherical)
    assert len(views) == 30
    expected_heights = 2 * (np.arange(30) + .5) / 30 - 1
    np.testing.assert_allclose(
        np.sin(np.deg2rad([view["elevation_degrees"] for view in views])),
        expected_heights, atol=1e-15)
    np.testing.assert_allclose(
        [view["azimuth_degrees"] for view in views[:4]], [37, 217, 127, 307])
    assert views == cameras({"azimuth_degrees": 37.}, spherical)
    centers = []
    for view in views:
        matrix = np.asarray(view["T_world_to_camera"])
        rotation = matrix[:3, :3]
        np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-14)
        assert np.linalg.det(rotation) == pytest.approx(1)
        np.testing.assert_allclose(matrix[:3, 3], [0, 0, view["distance"]], atol=1e-14)
        center = -rotation.T @ matrix[:3, 3]
        assert np.linalg.norm(center) == pytest.approx(view["distance"])
        centers.append(center)
    assert len(np.unique(np.round(centers, 12), axis=0)) == 30
    assert sum(center[2] > 0 for center in centers) == 15
    assert sum(center[2] < 0 for center in centers) == 15


def test_existing_orbit_camera_coordinates_are_preserved(config):
    from evaluation.render import make_camera
    expected = [make_camera(37 + offset, elevation=config["elevation_degrees"],
                            resolution=config["resolution"], fov=config["fov_degrees"],
                            radius=config["radius"])
                for offset in config["azimuth_offsets_degrees"]]
    assert cameras({"azimuth_degrees": 37}, config) == expected


@pytest.mark.parametrize("count,offset", [(0, .5), (2.5, .5), (30, 0), (30, 1)])
def test_spherical_cameras_reject_invalid_counts_and_pole_offsets(config, count, offset):
    spherical = dict(config, camera_layout="sphere-hammersley", view_count=count,
                     polar_offset=offset)
    with pytest.raises(ValueError):
        cameras({"azimuth_degrees": 0}, spherical)


def test_baseline_uses_thirty_views_and_one_complete_shape_selector():
    root = Path(__file__).parents[1]
    baseline = json.loads((root / "configs/baseline_v2.json").read_text())
    multiview = json.loads((root / baseline["multiview_config"]).read_text())
    assert baseline["selector"] == "shape.cd_euclidean_mean"
    assert baseline["selection_scope"] == "asset-method-stage"
    assert multiview["view_count"] == 30
    assert multiview["camera_layout"] == "sphere-hammersley"
    assert len(cameras({"azimuth_degrees": 0}, multiview)) == 30


def test_direct_depth_metrics_use_strict_thresholds_and_valid_pixels():
    from evaluation.multiview import depth_frame_metrics
    predicted = np.array([[1., 1.25, 1.25 ** 2, np.nan, 0., 2., np.inf]])
    target = np.ones_like(predicted)
    mask = np.ones_like(predicted, dtype=bool)
    gt_mask = mask.copy()
    gt_mask[0, 5] = False
    result = depth_frame_metrics(
        {"depth": predicted, "mask": mask}, {"depth": target, "mask": gt_mask},
    )
    values = result["metrics"]
    assert values["depth_delta1"] == pytest.approx(1 / 3)
    assert values["depth_delta2"] == pytest.approx(2 / 3)
    assert values["depth_absrel"] == pytest.approx((.25 + .5625) / 3)
    assert values["depth_coverage"] == .5
    assert result["pixels"] == {"pred": 4, "gt": 6, "overlap": 3}


def test_direct_depth_does_not_fit_affine_depth(config):
    base = frame()
    shifted = frame(4.)
    result = frame_metrics(shifted, base, config)["metrics"]
    assert result["depth_mae"] == result["depth_rmse"] == 2.
    assert result["depth_absrel"] == 1.
    assert result["depth_delta1"] == result["depth_delta2"] == 0.


def test_depth_image_encoding_uses_shared_gt_limits_and_neutral_background(config):
    from evaluation.multiview import depth_image_comparison
    prediction, reference = frame(), frame()
    reference["depth"][:] = np.linspace(1, 3, 256).reshape(16, 16)
    prediction["depth"][:] = reference["depth"]
    prediction["depth"][0, 0] = 10
    prediction["mask"][0, 1] = False
    comparison = depth_image_comparison(prediction, reference, config)
    assert comparison["encoding"]["depth_limits_D"] == pytest.approx([.8, 3.2])
    assert comparison["encoding"]["pred_clipped_pixels"] == 1
    assert comparison["encoding"]["pred_valid_pixels"] == 255
    np.testing.assert_array_equal(comparison["prediction_rgb"][0, 0], np.ones(3))
    np.testing.assert_array_equal(comparison["prediction_rgb"][0, 1], np.zeros(3))
    mask = prediction["mask"] & reference["mask"]
    error = (comparison["prediction_rgb"][mask].astype(float)
             - comparison["reference_rgb"][mask]) / 2
    mse = np.mean(error ** 2)
    assert comparison["metrics"]["depth_image_rmse"] == pytest.approx(np.sqrt(mse))
    assert comparison["metrics"]["depth_image_psnr"] == pytest.approx(-10*np.log10(mse))


def test_depth_image_empty_mask_and_constant_gt(config):
    from evaluation.multiview import depth_image_comparison
    prediction, reference = frame(), frame()
    own = depth_image_comparison(prediction, reference, config)
    assert own["encoding"]["depth_limits_D"] == pytest.approx([1.99, 2.01])
    assert own["metrics"]["depth_image_rmse"] == 0
    assert own["metrics"]["depth_image_psnr"] == 120
    prediction["mask"][:] = False
    empty = depth_image_comparison(prediction, reference, config)
    assert empty["metrics"]["depth_image_rmse"] is None
    assert empty["metrics"]["depth_image_psnr"] is None
    np.testing.assert_array_equal(empty["prediction_rgb"], 0)


def test_lpips_batch_and_single_use_the_same_rgb_encoding():
    import torch
    from evaluation.multiview import NormalLPIPS
    metric = NormalLPIPS.__new__(NormalLPIPS)
    metric.torch, metric.device = torch, "cpu"
    metric.model = lambda left, right: ((left-right)**2).mean((1, 2, 3), keepdim=True)
    prediction = np.zeros((2, 8, 8, 3), dtype=np.float32)
    reference = prediction.copy()
    prediction[1] = .5
    values = metric.batch(prediction, reference)
    assert values.tolist() == [0., .25]
    assert metric(prediction[1], reference[1]) == .25


def test_cached_image_batches_preserve_order_and_average_per_view_rmse(config):
    from evaluation.multiview import depth_frame_metrics
    from examples.review_cached_images import review_views, summarize_views

    class Metric:
        def batch(self, prediction, reference):
            return np.mean((prediction-reference)**2, axis=(1, 2, 3))
        def __call__(self, prediction, reference):
            return float(self.batch(prediction[None], reference[None])[0])

    gt = np.tile(np.linspace(1., 2., 16).reshape(1, 4, 4), (3, 1, 1))
    target = {"depth": gt, "mask": np.ones_like(gt, dtype=bool)}
    predicted = {"depth": gt + np.array([0., .02, .04])[:, None, None],
                 "mask": np.ones_like(gt, dtype=bool)}
    stored = []
    for index, mse in enumerate([.01, .04, .09]):
        row = depth_frame_metrics(
            {name: value[index] for name, value in predicted.items()},
            {name: value[index] for name, value in target.items()},
        )
        row["metrics"]["normal_mse"] = mse
        stored.append(row)
    frames, error = review_views(predicted, target, stored, config, Metric(), 2, True)
    assert error == 0
    assert frames[0]["metrics"]["depth_image_lpips"] == 0
    assert 0 < frames[1]["metrics"]["depth_image_lpips"] < frames[2]["metrics"]["depth_image_lpips"]
    rows = {row["metric"]: row for row in summarize_views(frames)["metrics"]}
    assert rows["normal_rmse"]["value"] == pytest.approx(.2)
    assert rows["normal_rmse"]["value"] != pytest.approx(np.sqrt(np.mean([.01, .04, .09])))
    stored[0]["pixels"]["overlap"] -= 1
    with pytest.raises(ValueError, match="pixel count"):
        review_views(predicted, target, stored, config, Metric(), 2)


def test_full_frame_image_errors_include_background_and_missing_normals(config):
    from evaluation.multiview import depth_image_comparison, normal_image_comparison
    prediction, reference = frame(), frame()
    reference["depth"][:] = np.linspace(1, 3, 256).reshape(16, 16)
    prediction["depth"][:] = reference["depth"]
    prediction["mask"][:8] = False
    prediction["normal_valid"][:8] = False
    full_config = {**config, "image_metric_region": "full_frame"}
    depth = depth_image_comparison(prediction, reference, full_config)
    normal = normal_image_comparison(prediction, reference, full_config)
    assert depth["metrics"]["depth_image_rmse"] > 0
    assert normal["metrics"]["normal_rmse"] == pytest.approx(np.sqrt(1 / 24))
    result = frame_metrics(prediction, reference, full_config)
    assert result["metrics"]["depth_mae"] == 0
    assert result["metrics"]["normal_mean_angle"] == 0
    assert result["metrics"]["normal_rmse"] > 0
    assert result["image_metric_region"] == "full_frame"
    previous = depth_image_comparison(prediction, reference, config)
    for name in ("prediction_rgb", "reference_rgb"):
        np.testing.assert_array_equal(depth[name], previous[name])
    assert previous["metrics"]["depth_image_rmse"] == 0


def test_full_frame_errors_are_defined_with_empty_prediction(config):
    full_config = {**config, "image_metric_region": "full_frame"}
    prediction, reference = frame(), frame()
    prediction["mask"][:] = False
    result = frame_metrics(prediction, reference, full_config)
    assert result["metrics"]["depth_mae"] is None
    assert result["metrics"]["depth_image_rmse"] is not None
    assert result["metrics"]["normal_rmse"] == pytest.approx(np.sqrt(1 / 12))
    assert result["metrics"]["depth_coverage"] == 0


def test_multiview_physical_depth_exclusion_is_explicit(config):
    from evaluation.multiview import PHYSICAL_DEPTH_METRICS
    reference = {key: np.stack([value] * 4) for key, value in frame().items()}
    result = compare_views(reference, reference,
                           {**config, "image_metric_region": "full_frame",
                            "multiview_physical_depth_metrics": False})
    names = {row["metric"] for row in result["metrics"]}
    assert not names & PHYSICAL_DEPTH_METRICS
    assert {"depth_coverage", "depth_image_rmse", "depth_image_psnr", "silhouette_iou"} <= names


def test_full_frame_cache_update_reuses_identical_lpips_inputs(config):
    from evaluation.multiview import depth_image_comparison, normal_image_comparison
    from examples.review_fullframe_images import update_frame
    prediction, reference = frame(), frame()
    prediction["mask"][:8] = False
    prediction["normal_valid"][:8] = False
    reference["depth"][:] = np.linspace(1, 3, 256).reshape(16, 16)
    prediction["depth"][:] = reference["depth"]
    previous = frame_metrics(prediction, reference, config)
    previous["metrics"]["depth_image_lpips"] = .123
    previous["metrics"]["normal_lpips"] = .456
    full_config = {**config, "image_metric_region": "full_frame"}
    actual = update_frame(prediction, reference, previous, full_config)
    expected = frame_metrics(prediction, reference, full_config)
    for name in ("depth_image_rmse", "depth_image_psnr", "normal_mse", "normal_rmse", "normal_psnr"):
        assert actual["metrics"][name] == pytest.approx(expected["metrics"][name])
    assert actual["metrics"]["depth_image_lpips"] == .123
    assert actual["metrics"]["normal_lpips"] == .456
    for encoder in (depth_image_comparison, normal_image_comparison):
        old = encoder(prediction, reference, config)
        full = encoder(prediction, reference, full_config)
        for name in ("prediction_rgb", "reference_rgb"):
            np.testing.assert_array_equal(old[name], full[name])


def test_generic_multiview_summary_respects_image_only_metric_selection(config):
    from evaluation.multiview import multiview_metric_units
    from examples.evaluate_multiview import summarize
    selected = {**config, "multiview_physical_depth_metrics": False}
    planned = [
        {"method": method, "config_id": "a", "seed": 42, "config_hash": "h",
         "parameter_hash": "p", "sample_id": "asset"} for method in ("wt", "trellis2")
    ]
    report = summarize([], planned, selected)
    assert report["failed_metrics"] == 3 * len(multiview_metric_units(selected))
