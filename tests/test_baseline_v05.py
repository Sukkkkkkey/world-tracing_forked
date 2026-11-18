import json
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from evaluation.baseline import select_best, shape_metrics
from evaluation.render_artifacts import export_render_images, frame_images, depth_limits
from evaluation.visibility import gt_visibility, region_metrics, paired_export_geometry
from examples.evaluate_baseline_v2 import candidate_plan
from examples.evaluate_multiview import valid_result
from examples.summarize_baseline_v2 import asset_group
from wt.experiment import file_digest


def camera():
    return {"K": [[100, 0, 50], [0, 100, 50], [0, 0, 1]],
            "T_world_to_camera": [[1, 0, 0, 0], [0, -1, 0, 0],
                                  [0, 0, -1, 2], [0, 0, 0, 1]],
            "resolution": 100, "near": .01, "far": 10}


@pytest.mark.parametrize("reverse", [False, True])
def test_visibility_front_occlusion_corner_and_outside(reverse):
    mesh = trimesh.creation.box()
    if reverse:
        mesh.faces = mesh.faces[:, ::-1]
    points = np.array([[0, 0, .5], [0, 0, -.5], [.5, .5, .5], [5, 0, .5]])
    result, arrays = gt_visibility(mesh, points, camera(), batch_size=2)
    assert arrays["labels"].tolist() == [1, 2, 1, 0]
    assert result["invalid"] == 0
    assert result["counts"] == {"visible": 2, "occluded": 1, "out_of_view": 1}


def test_small_triangles_and_visibility_tolerance():
    mesh = trimesh.creation.box(extents=[.001, .001, .001])
    result, arrays = gt_visibility(mesh, np.array([[0, 0, .0005], [0, 0, -.0005]]), camera())
    assert arrays["labels"].tolist() == [1, 2]
    assert result["invalid"] == 0
    for thickness, label in ((5e-5, 1), (2e-4, 2)):
        mesh = trimesh.creation.box(extents=[1, 1, thickness])
        _, arrays = gt_visibility(mesh, np.array([[0, 0, -thickness / 2]]), camera())
        assert arrays["labels"].tolist() == [label]


def test_unresolved_ray_is_explicit_and_invalidates_regions():
    mesh = trimesh.creation.box()
    _, arrays = gt_visibility(mesh, np.array([[.8, 0, 0]]), camera())
    assert arrays["labels"].tolist() == [3]
    regions, _ = region_metrics(np.array([[.8, 0, 0]]), np.array([[.8, 0, 0]]), arrays["labels"])
    assert regions["visible"]["status"] == "invalid_visibility"
    assert regions["visible"]["metrics"]["f@0.01"] is None


def test_regions_recompute_neighbours_and_save_both_directions():
    gt = np.array([[0., 0, 0], [1., 0, 0]])
    pred = gt + [.1, 0, 0]
    regions, arrays = region_metrics(pred, gt, np.array([1, 2]))
    for name in ("visible", "occluded"):
        assert regions[name]["metrics"]["cd_euclidean_mean"] == pytest.approx(.1)
        assert arrays[f"{name}_pred_to_gt"].tolist() == pytest.approx([.1])
        assert arrays[f"{name}_gt_to_pred"].tolist() == pytest.approx([.1])
    assert arrays["prediction_labels"].tolist() == [1, 2]
    assert regions["out_of_view"]["status"] == "not_applicable"
    regions, _ = region_metrics(pred[:1], gt, np.array([1, 2]))
    assert regions["occluded"]["status"] == "empty_prediction"
    assert regions["occluded"]["metrics"]["cd_euclidean_mean"] is None
    assert regions["occluded"]["metrics"]["recall@0.01"] == 0
    assert regions["occluded"]["metrics"]["f@0.01"] == 0


def test_export_pair_uses_exact_decoded_matrix_and_area_scale():
    gt = np.array([[1., 0, 0], [3., 0, 0]])
    matrix = np.diag([2., 2., 2., 1.])
    matrix[0, 3] = 1.
    regions, _ = region_metrics(gt, gt, np.array([1, 2]))
    decoded = {"shape": shape_metrics(gt, gt), "regions": regions,
               "registration": {"matrix": matrix.tolist()}, "geometry": {"area_gt_ratio": 2.}}
    points = np.array([[.1, 0, 0], [1.1, 0, 0]])
    pair, _ = paired_export_geometry(points, gt, np.array([1, 2]), decoded, 3., 4.)
    np.testing.assert_array_equal(pair["matrix"], matrix)
    assert pair["glb"]["shape"]["cd_euclidean_mean"] == pytest.approx(.2)
    assert pair["glb"]["regions"]["visible"]["metrics"]["cd_euclidean_mean"] == pytest.approx(.2)
    assert pair["glb"]["geometry"]["aligned_area"] == pytest.approx(12.)
    assert pair["glb"]["geometry"]["area_gt_ratio"] == pytest.approx(3.)
    np.testing.assert_array_equal(points, [[.1, 0, 0], [1.1, 0, 0]])


def frame():
    depth = np.full((8, 8), 2., dtype=np.float32)
    normals = np.zeros((8, 8, 3), dtype=np.float32)
    normals[..., 2] = -1
    return {"depth": depth, "mask": np.ones((8, 8), dtype=bool),
            "normals": normals, "normal_valid": np.ones((8, 8), dtype=bool)}


def test_png_uses_common_gt_scale_and_exact_valid_masks():
    truth = frame()
    prediction = frame()
    prediction["depth"][0, 0] = 2.005
    prediction["normal_valid"][0, 1] = False
    images, limits = frame_images(prediction, truth, {"depth_error_max": .05})
    assert limits == depth_limits(truth)
    assert images["normal_overlap.png"][0, 1] == 0
    assert images["depth_overlap.png"][0, 1] == 255
    assert images["normal.png"][0, 1].tolist() == [127, 127, 127]
    np.testing.assert_array_equal(images["depth_valid.png"], truth["mask"].astype(np.uint8) * 255)
    images2, limits2 = frame_images(frame(), truth, {"depth_error_max": .05})
    assert limits == limits2
    assert not np.array_equal(images["depth.png"][0, 0], images2["depth.png"][0, 0])


def test_export_repairs_only_missing_png_and_preserves_manifest(tmp_path, monkeypatch):
    truth = frame()
    groups = {name: {key: value[None] for key, value in truth.items()}
              for name in ("input", "multiview")}
    args = (tmp_path, {"surfel": groups}, groups, [camera(), camera()],
            {"seed": 42, "stage": "points"}, {"depth_error_max": .05, "save_multiview": True})
    original = export_render_images(*args)
    manifest = json.loads(Path(original["manifest"]).read_text())
    assert original["frame_count"] == 2
    assert len(manifest["files"]) == 22
    missing = tmp_path / "renders/surfel/input/000/depth.png"
    expected = file_digest(missing)
    missing.unlink()
    writes = []
    save = Image.Image.save
    def counting_save(image, *args, **kwargs):
        writes.append(1)
        return save(image, *args, **kwargs)
    monkeypatch.setattr(Image.Image, "save", counting_save)
    repaired = export_render_images(*args)
    assert writes == [1]
    assert repaired == original
    assert file_digest(missing) == expected


def test_numerical_cache_survives_incomplete_artifacts(tmp_path):
    (tmp_path / "array.npz").write_bytes(b"array")
    record = {"signature": "signature", "status": "failed", "numerical_status": "complete",
              "files": {"array.npz": file_digest(tmp_path / "array.npz")}}
    (tmp_path / "result.json").write_text(json.dumps(record))
    assert valid_result(tmp_path, "signature") is None
    assert valid_result(tmp_path, "signature", status_key="numerical_status") == record
    assert valid_result(tmp_path, "changed", status_key="numerical_status") is None
    (tmp_path / "array.npz").write_bytes(b"corrupt")
    assert valid_result(tmp_path, "signature", status_key="numerical_status") is None


def test_calibration_has_70_stages_and_only_single_seed_values(tmp_path):
    source = tmp_path / "source"
    for i in range(10):
        directory = source / "samples" / str(i)
        directory.mkdir(parents=True)
        (directory / "input.json").write_text("{}")
    config = {"report_single_seed": 42, "mesh_stages": ["decoded", "glb"],
              "methods": dict.fromkeys(["wt", "trellis2", "pixal3d", "wt_trellis2"], "default")}
    assert len(candidate_plan(tmp_path / "new", source, config, [42])) == 70
    record = {"seed": 42, "status": "complete", "result_path": "42",
              "shape": {"cd_euclidean_mean": .02}, "registration": {"matrix": np.eye(4).tolist()}}
    group = asset_group([record], [42], 42, calibration=True)
    assert group["expected"] == 1
    assert list(group["values"]) == ["single_seed"]
    assert group["selection"]["status"] == "not_applicable"


def test_stage_winners_ties_and_nonterminal_candidates():
    def candidates(winner):
        return [{"seed": seed, "status": "complete", "result_path": str(seed),
                 "shape": {"cd_euclidean_mean": 0. if seed == winner else 1.}}
                for seed in range(42, 50)]
    decoded, glb = candidates(43), candidates(46)
    assert select_best(decoded, range(42, 50))["seed"] == 43
    assert select_best(glb, range(42, 50))["seed"] == 46
    decoded[0]["shape"]["cd_euclidean_mean"] = 0.
    assert select_best(decoded, range(42, 50))["seed"] == 42
    decoded[-1]["status"] = "running"
    assert select_best(decoded, range(42, 50))["status"] == "pending"


def test_projected_rtree_matches_trimesh_first_hits():
    from evaluation.geometry import surface_points
    from evaluation.visibility import first_hits
    from trimesh.ray.ray_triangle import RayMeshIntersector
    mesh = trimesh.creation.icosphere(subdivisions=2, radius=.5)
    points = surface_points(mesh, 300, 71)
    view = camera()
    origin = np.array([0., 0., 2.])
    offsets = points - origin
    directions = offsets / np.linalg.norm(offsets, axis=1)[:, None]
    _, rays, hits = RayMeshIntersector(mesh).intersects_id(
        np.broadcast_to(origin, points.shape).copy(), directions,
        return_locations=True, multiple_hits=False)
    expected = np.full(len(points), np.nan)
    expected[rays] = np.linalg.norm(hits - origin, axis=1)
    actual = first_hits(mesh, points, view, np.arange(len(points)), 33)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12)


def test_near_tangent_triangle_and_surface_roundoff():
    from evaluation.visibility import first_hits
    # This triangle is almost edge-on to the camera, with |normal dot ray| below 1e-5.
    origin = np.array([0., 0., 2.])
    vertices = np.array([[-.2, 0., 0.], [.2, 0., 0.], [0., 1e-6, .2]])
    mesh = trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2]], process=False)
    point = vertices.mean(axis=0)[None]
    distance = first_hits(mesh, point, camera(), np.array([0]), 256)
    np.testing.assert_allclose(distance, np.linalg.norm(point - origin, axis=1), atol=1e-10)
    rounded = point + mesh.face_normals[0] * 2e-9
    original = rounded.copy()
    result, arrays = gt_visibility(mesh, rounded, camera())
    assert arrays["labels"].tolist() == [1]
    assert result["surface_projection_max"] < 1e-6
    np.testing.assert_array_equal(rounded, original)


def test_surface_anchor_on_small_skinny_triangle():
    from evaluation.visibility import surface_anchors
    vertices = np.array([[0., 0, 0], [2e-4, 0, 0], [1e-4, 1e-7, 0]])
    mesh = trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2]], process=False)
    target = vertices.mean(axis=0)[None] + [0, 0, 3e-9]
    anchors, distance = surface_anchors(mesh, target, np.array([0]), 1e-6)
    np.testing.assert_allclose(anchors, vertices.mean(axis=0)[None], atol=1e-14)
    assert distance[0] == pytest.approx(3e-9)


@pytest.mark.parametrize("save_multiview", [False, True])
def test_cli_indexes_decoded_repaired_during_glb_and_clears_resolved_failure(tmp_path, monkeypatch, save_multiview):
    from examples import evaluate_baseline_v2 as cli
    from wt.experiment import atomic_json, read_json, run_directory
    source = tmp_path / "source"
    experiment = tmp_path / "experiment"
    candidate = run_directory(source, "object", "trellis2", "defaults-v1", 42)
    atomic_json(candidate / "run.json", {"status": "complete"})
    atomic_json(source / "samples/object/input.json", {})
    config_path = tmp_path / "config.json"
    atomic_json(config_path, {"seeds": list(range(42, 50)), "report_single_seed": 42,
                             "methods": {"trellis2": "defaults-v1"},
                             "mesh_stages": ["decoded", "glb"]})
    root = tmp_path / "evaluation"
    class FakeEvaluator:
        def __init__(self, config_path, *, save_multiview_renders=False):
            self.config = read_json(config_path)
            self.config["render_artifacts"] = {"save_multiview": save_multiview_renders}
            self.root = root
            self.revision = "test"
            self.index_updates = []
        def evaluate(self, directory, stage, experiment_name):
            decoded_path = root / "decoded/result.json"
            if stage == "glb":
                repaired = read_json(decoded_path)
                repaired["status"] = "complete"
                atomic_json(decoded_path, repaired)
                self.index_updates.append(repaired)
            result = {
                "sample_id": "object", "method": "trellis2", "config_id": "defaults-v1",
                "seed": 42, "stage": stage, "source_directory": str(directory), "revision": "test",
                "status": "failed" if stage == "decoded" else "complete",
                "result_path": str(root / stage / "result.json"),
                "shape": {"cd_euclidean_mean": .1}, "registration": {"matrix": np.eye(4).tolist()},
            }
            atomic_json(Path(result["result_path"]), result)
            self.index_updates.append(result)
            return result
    monkeypatch.setattr(cli, "BaselineEvaluator", FakeEvaluator)
    monkeypatch.setattr("sys.argv", ["evaluate", "--experiment", str(experiment),
                                   "--source-experiment", str(source), "--config", str(config_path),
                                   "--seeds", "42", "--calibration"]
                        + (["--save-multiview-renders"] if save_multiview else []))
    assert cli.main() == 0
    output = root / experiment.name
    index = read_json(output / "index.json")
    assert read_json(output / "plan.json")["config"]["render_artifacts"]["save_multiview"] == save_multiview
    assert len(index["results"]) == 2
    for row in index["results"]:
        assert row["status"] == "complete"
        assert row["result_sha256"] == file_digest(Path(row["result_path"]))
    assert read_json(output / "last_evaluation.json")["failures"] == []
    assert read_json(output / "summary.json")["status_counts"] == {"complete": 2, "failed": 0}


def test_validation_recomputes_render_metrics_and_detects_mismatch():
    from evaluation.multiview import frame_metrics
    from examples.validate_baseline_v05 import check_frame_metrics
    prediction, reference = frame(), frame()
    prediction["depth"][0, 0] += .02
    config = {"psnr_mse_floor": 1e-12}
    stored = frame_metrics(prediction, reference, config)
    check_frame_metrics(prediction, reference, stored, config)
    for name in ("depth_absrel", "depth_delta1", "depth_delta2",
                 "depth_image_rmse", "depth_image_psnr", "depth_image_lpips",
                 "depth_image_clipped_fraction", "normal_rmse"):
        stored["metrics"].pop(name)
    check_frame_metrics(prediction, reference, stored, config)
    stored.pop("image_metric_region")
    check_frame_metrics(prediction, reference, stored, {**config, "image_metric_region": "full_frame"})
    stored["metrics"]["depth_mae"] += .01
    with pytest.raises(AssertionError):
        check_frame_metrics(prediction, reference, stored, config)


@pytest.mark.parametrize("filename", ["evaluation_protocol.md", "evaluation_protocol_v0.md",
                                      "archived/evaluation_protocol_v0.md"])
def test_validation_preserves_protocol_hash_across_rename(tmp_path, filename):
    from examples.validate_baseline_v05 import verify_preserved_protocol

    path = tmp_path / "docs" / filename
    path.parent.mkdir(parents=True)
    path.write_text("Previous protocol")
    checksum = file_digest(path)
    metadata = verify_preserved_protocol(tmp_path, checksum)
    assert metadata == {"old_protocol_path": str(path), "old_protocol_sha256": checksum}
    path.write_text("Changed protocol")
    with pytest.raises(AssertionError, match="pre-run snapshot"):
        verify_preserved_protocol(tmp_path, checksum)


def test_visibility_exact_frustum_pixel_and_depth_boundaries():
    mesh = trimesh.creation.box(extents=[4., 4., .2])
    mesh.apply_translation([0, 0, .4])
    points = np.array([[-.75, 0, .5], [.75, 0, .5],
                       [0, .75, .5], [0, -.75, .5],
                       [.75 - 1e-9, 0, .5], [-.75 - 1e-9, 0, .5]])
    diagnostics, arrays = gt_visibility(mesh, points, camera())
    assert diagnostics["invalid"] == 0
    assert arrays["in_frustum"].tolist() == [True, False, True, False, True, False]
    assert arrays["labels"].tolist() == [1, 0, 1, 0, 1, 0]
    for near, far, expected in [(1.5, 1.5, 1), (1.5 + 1e-9, 10., 0),
                                (.01, 1.5 - 1e-9, 0)]:
        view = {**camera(), "near": near, "far": far}
        _, labels = gt_visibility(mesh, np.array([[0., 0, .5]]), view)
        assert labels["labels"].tolist() == [expected]


@pytest.mark.parametrize("save_multiview", [False, True])
@pytest.mark.parametrize("reference_only", [False, True])
def test_png_view_selection_and_manifest_validation(tmp_path, save_multiview, reference_only):
    from examples.validate_baseline_v05 import check_manifest

    truth = frame()
    groups = {"input": {key: value[None] for key, value in truth.items()},
              "multiview": {key: np.repeat(value[None], 3, axis=0) for key, value in truth.items()}}
    representations = {"surfel": groups, "native": groups}
    config = {"depth_error_max": .05}
    if save_multiview:
        config["save_multiview"] = True
    artifact = export_render_images(tmp_path, representations, groups, [camera()] * 4,
                                    {"seed": 42}, config, reference_only=reference_only)
    manifest = json.loads(Path(artifact["manifest"]).read_text())
    expected_groups = {"input", "multiview"} if save_multiview else {"input"}
    assert {item["group"] for item in manifest["frames"]} == expected_groups
    assert manifest["config"]["save_multiview"] == save_multiview
    assert artifact["frame_count"] == 2 * (4 if save_multiview else 1)
    assert artifact["file_count"] == artifact["frame_count"] * (5 if reference_only else 11)
    assert (tmp_path / "renders/surfel/multiview").exists() == save_multiview
    assert check_manifest(tmp_path, artifact, representations, groups,
                          reference_only=reference_only) == artifact["file_count"]
    np.testing.assert_array_equal(groups["multiview"]["depth"], np.repeat(truth["depth"][None], 3, axis=0))
