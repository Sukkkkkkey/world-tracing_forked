import json
from pathlib import Path
import numpy as np
import pytest
import trimesh
from scipy.spatial.transform import Rotation

from evaluation.baseline import load_stage_mesh, register_shape, select_best, shape_metrics
from evaluation.geometry import chamfer, transform_points
from examples.evaluate_baseline_v2 import candidate_plan, input_camera, wt_camera_diagnostics


def test_registration_is_equivariant_to_arbitrary_positive_similarity():
    rng = np.random.default_rng(17)
    reference = rng.normal(size=(500, 3)) * [.3, .16, .07]
    reference[:, 0] += .1 * reference[:, 1] ** 2
    prediction = reference + rng.normal(scale=.002, size=reference.shape)
    matrix, _ = register_shape(prediction, reference)
    transformed = np.eye(4)
    transformed[:3, :3] = Rotation.from_euler("xyz", [17, 29, 43], degrees=True).as_matrix() * 2.3
    transformed[:3, 3] = [.4, -.9, 1.3]
    moved = transform_points(prediction, transformed)
    moved_matrix, _ = register_shape(moved, reference)
    np.testing.assert_allclose(transform_points(moved, moved_matrix),
                               transform_points(prediction, matrix), atol=1e-10)
    assert np.linalg.det(matrix[:3, :3]) > 0
    assert shape_metrics(transform_points(prediction, matrix), reference)["cd_euclidean_mean"] < .004


def test_shape_components_match_existing_metric():
    p = np.random.default_rng(1).normal(size=(30, 3))
    q = p + [.05, .02, 0]
    expected = chamfer(p, q)
    actual = shape_metrics(p, q)
    for key, value in expected.items():
        assert actual[key] == pytest.approx(value)
    assert (actual["pred_to_gt_mean"] + actual["gt_to_pred_mean"]) / 2 == pytest.approx(expected["cd_euclidean_mean"])


def test_best_of_eight_uses_one_shape_selected_seed():
    candidates = [{"seed": seed, "status": "complete",
                   "shape": {"cd_euclidean_mean": .1 / (seed - 40)},
                   "result_path": f"/result/{seed}.json"} for seed in range(42, 50)]
    selected = select_best(candidates, list(range(42, 50)))
    assert selected["seed"] == 49
    assert selected["result"] == "/result/49.json"
    assert selected["valid_candidates"] == 8
    assert select_best(candidates[:-1], list(range(42, 50)))["status"] == "pending"
    candidates[7] = {"seed": 49, "status": "failed"}
    assert select_best(candidates, list(range(42, 50)))["seed"] == 48
    with pytest.raises(ValueError, match="Duplicate"):
        select_best(candidates + [candidates[0]], list(range(42, 50)))


@pytest.mark.parametrize("method", ["trellis2", "pixal3d"])
def test_glb_nodes_and_output_axes_are_restored(tmp_path, method):
    original = trimesh.creation.box(extents=[.4, .7, .2])
    export = np.eye(4)
    if method == "trellis2":
        export[:3, :3] = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]
    else:
        export[:3, :3] = np.diag([-1, 1, -1])
    mesh = original.copy()
    mesh.apply_transform(export)
    node = np.eye(4)
    node[:3, 3] = [.2, .3, .4]
    scene = trimesh.Scene()
    scene.add_geometry(mesh, transform=node)
    scene.export(tmp_path / "mesh.glb")
    (tmp_path / "run.json").write_text(json.dumps({"method": method}))
    (tmp_path / "mesh.json").write_text(json.dumps({"decoded_to_glb": export.tolist()}))
    restored = load_stage_mesh(tmp_path, "glb")
    expected = original.copy()
    expected.vertices += np.linalg.inv(export)[:3, :3] @ node[:3, 3]
    np.testing.assert_allclose(restored.bounds, expected.bounds, atol=1e-7)
    assert restored.area == pytest.approx(expected.area, rel=1e-6)


def test_candidate_plan_reuses_seed_42_and_keeps_both_stages(tmp_path):
    source = tmp_path / "source"
    sample = source / "samples/object"
    sample.mkdir(parents=True)
    (sample / "input.json").write_text("{}")
    config = {"methods": {"wt": "defaults-v1", "trellis2": "defaults-v1"},
              "mesh_stages": ["decoded", "glb"], "report_single_seed": 42}
    plan = candidate_plan(tmp_path / "new", source, config, [42, 43])
    assert len(plan) == 6
    assert all(str(source) in row["source_directory"] for row in plan if row["seed"] == 42)
    assert all(str(tmp_path / "new") in row["source_directory"] for row in plan if row["seed"] == 43)
    assert {row["stage"] for row in plan if row["method"] == "wt"} == {"points"}


def test_input_camera_uses_actual_crop_intrinsics():
    camera = {"K": np.eye(3).tolist(), "K_crop": (np.eye(3) * 2).tolist(),
              "T_world_to_camera": np.eye(4).tolist(), "resolution": 1024}
    selected = input_camera(camera)
    assert selected["resolution"] == 504
    assert selected["K"] == camera["K_crop"]
    assert camera["resolution"] == 1024


def test_camera_diagnostics_recover_known_projection(tmp_path):
    v, u = np.mgrid[:12, :12]
    K = np.array([[20., 0, 6.], [0, 21., 6.], [0, 0, 1.]])
    depth = 1.5 + .01 * u + .02 * v
    pixels = np.stack([u + .5, v + .5, np.ones_like(u)], axis=-1)
    xyz = (pixels @ np.linalg.inv(K).T) * depth[..., None]
    mask = np.ones(depth.shape, dtype=bool)
    points = xyz.reshape(-1, 3)
    np.savez(tmp_path / "gt_depth.npz", depth=depth, mask=mask, K=K)
    np.savez(tmp_path / "gt_points.npz", evaluation=points)
    (tmp_path / "camera.json").write_text(json.dumps({"T_world_to_camera": np.eye(4).tolist()}))
    result = wt_camera_diagnostics(xyz, mask, K, tmp_path, points)
    assert result["status"] == "complete"
    assert result["scale_about_camera_origin"] == pytest.approx(1)
    assert result["l0_xyz_rmse"] < 1e-12
    assert result["projections"]["gt"]["mean_pixels"] < 1e-12
    assert result["projections"]["fitted"]["mean_pixels"] < 1e-5


@pytest.mark.parametrize("view_count", [4, 30])
def test_render_summary_preserves_different_view_resolutions(tmp_path, view_count):
    from examples.evaluate_baseline_v2 import summarize_render, save_render_groups
    def maps(count, side):
        depth = np.broadcast_to(np.arange(side, dtype=float)[None, None, :] + 1,
                                (count, side, side)).copy()
        normals = np.zeros((count, side, side, 3), dtype=np.float32)
        normals[..., 2] = -1
        return {"depth": depth, "mask": np.ones_like(depth, dtype=bool),
                "normals": normals, "normal_valid": np.ones_like(depth, dtype=bool)}
    groups = {"input": maps(1, 7), "multiview": maps(view_count, 8)}
    result = summarize_render(groups, groups, {"psnr_mse_floor": 1e-12}, None)
    assert result["input"]["metrics"]["depth_mae"] == 0
    assert len(result["multiview"]["views"]) == view_count
    save_render_groups(tmp_path, "render.npz", groups)
    with np.load(tmp_path / "render.npz", allow_pickle=False) as saved:
        assert saved["input_depth"].shape == (1, 7, 7)
        assert saved["multiview_depth"].shape == (view_count, 8, 8)


def test_summary_preserves_selected_seed_and_fixed_budget():
    from examples.summarize_baseline_v2 import asset_group
    records = [{"seed": seed, "status": "complete", "result_path": str(seed),
                "shape": {"cd_euclidean_mean": .5 - .01 * seed},
                "registration": {"matrix": np.eye(4).tolist()},
                "input_rgb": {"psnr": float(100 - seed)}}
               for seed in range(42, 50)]
    report = asset_group(records, list(range(42, 50)), 42)
    assert report["selection"]["seed"] == 49
    assert report["values"]["best_of_8"]["input_rgb.psnr"] == 51
    assert report["values"]["single_seed"]["input_rgb.psnr"] == 58
    assert report["within_asset"]["input_rgb.psnr"]["valid_seeds"] == 8
    pending = asset_group(records[:-1], list(range(42, 50)), 42)
    assert pending["values"]["mean_of_8"] == {}
    assert pending["selection"]["status"] == "pending"


def test_summary_counts_failed_candidate_without_dropping_asset():
    from examples.summarize_baseline_v2 import asset_group
    records = [{"seed": seed, "status": "failed"} for seed in range(42, 50)]
    records[0] = {"seed": 42, "status": "complete", "result_path": "42",
                  "shape": {"cd_euclidean_mean": .02},
                  "registration": {"matrix": np.eye(4).tolist()}}
    report = asset_group(records, list(range(42, 50)), 42)
    assert report["failed"] == 7
    assert report["selection"]["valid_candidates"] == 1
    assert report["selection"]["seed"] == 42
    assert report["within_asset"]["shape.cd_euclidean_mean"]["valid_seeds"] == 1


def test_parallel_initializations_match_original_solver_exactly():
    from evaluation.baseline import principal_frame
    from evaluation.geometry import register_sim3
    rng = np.random.default_rng(83)
    reference = rng.normal(size=(150, 3)) * [.3, .1, .06]
    prediction = reference + rng.normal(scale=.004, size=reference.shape)
    prediction_frame, _ = principal_frame(prediction)
    reference_frame, _ = principal_frame(reference)
    p = transform_points(prediction, np.linalg.inv(prediction_frame))
    q = transform_points(reference, np.linalg.inv(reference_frame))
    expected, expected_info = register_sim3(p, q)
    expected = reference_frame @ expected @ np.linalg.inv(prediction_frame)
    actual, info = register_shape(prediction, reference, workers=8)
    np.testing.assert_array_equal(actual, expected)
    assert info["starts"] == expected_info["starts"]
    assert info["loss"] == expected_info["loss"]


def test_candidate_failure_rate_keeps_pending_budget_explicit():
    from examples.summarize_baseline_v2 import asset_group, coverage
    records = [{"seed": 42, "status": "failed"}]
    asset = asset_group(records, list(range(42, 50)), 42)
    row = coverage({("asset", "wt", "points"): asset})[0]
    assert row["expected_candidates"] == 8
    assert row["evaluated_candidates"] == 1
    assert row["pending_candidates"] == 7
    assert row["failure_rate_among_evaluated"] == 1
    assert row["budget_failure_rate"] is None
