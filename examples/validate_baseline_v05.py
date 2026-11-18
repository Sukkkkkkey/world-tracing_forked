"""Validate the complete P0 v0.5 budget, PNG provenance and GT calibration."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
import trimesh

from evaluation.render_artifacts import frame_images, load_render_groups
from evaluation.multiview import frame_metrics
from evaluation.visibility import gt_visibility, region_metrics
from wt.artifacts import save_npz
from wt.experiment import atomic_json, digest, file_digest, read_json
from wt.paths import REPO_ROOT


def check_frame_metrics(prediction, reference, stored, config):
    metric_config = {**config, "image_metric_region": stored.get("image_metric_region", "valid_intersection")}
    actual = frame_metrics(prediction, reference, metric_config)
    assert actual["pixels"] == stored["pixels"]
    added_metrics = {"depth_absrel", "depth_delta1", "depth_delta2",
                     "depth_image_rmse", "depth_image_psnr", "depth_image_lpips",
                     "depth_image_clipped_fraction", "normal_rmse"}
    for name, value in actual["metrics"].items():
        if name in {"normal_lpips", "depth_image_lpips"} or (name in added_metrics and name not in stored["metrics"]):
            continue
        expected = stored["metrics"][name]
        if value is None:
            assert expected is None, name
        else:
            np.testing.assert_allclose(value, expected, rtol=1e-10, atol=1e-12, err_msg=name)


def check_manifest(directory, artifact, representations, reference, *, reference_only=False,
                   comparisons=None, metric_config=None):
    path = Path(artifact["manifest"])
    assert file_digest(path) == artifact["sha256"], f"Manifest hash mismatch: {path}"
    manifest = read_json(path)
    # Older manifests exported every view before this option was introduced.
    groups = ("input", "multiview") if manifest["config"].get("save_multiview", True) else ("input",)
    expected_frames = {(name, group, index) for name, maps in representations.items()
                       for group in groups for index in range(len(maps[group]["depth"]))}
    actual_frames = {(frame["representation"], frame["group"], frame["view"])
                     for frame in manifest["frames"]}
    assert actual_frames == expected_frames
    assert len(manifest["frames"]) == len(expected_frames)
    if comparisons is not None:
        for name, maps in representations.items():
            for group in ("input", "multiview"):
                for index in range(len(maps[group]["depth"])):
                    prediction = {key: value[index] for key, value in maps[group].items()}
                    truth = {key: value[index] for key, value in reference[group].items()}
                    comparison = comparisons[name]
                    stored = comparison["input"] if group == "input" else comparison["multiview"]["views"][index]
                    check_frame_metrics(prediction, truth, stored, metric_config)
    verified = {}
    def check_png(item):
        name, expected = item
        payload = (directory / name).read_bytes()
        checksum = hashlib.sha256(payload).hexdigest()
        assert checksum == manifest["files"][name], f"PNG digest mismatch: {name}"
        with Image.open(io.BytesIO(payload)) as saved:
            np.testing.assert_array_equal(np.asarray(saved), expected, err_msg=name)
        return name, checksum
    with ThreadPoolExecutor(max_workers=4) as executor:
        for frame in manifest["frames"]:
            group, index = frame["group"], frame["view"]
            maps = representations[frame["representation"]][group]
            prediction = {name: value[index] for name, value in maps.items()}
            truth = {name: value[index] for name, value in reference[group].items()}
            images, limits = frame_images(prediction, truth, manifest["config"],
                                          reference_only=reference_only)
            assert limits == frame["depth_limits"]
            expected = {f"{frame['directory']}/{name}": array for name, array in images.items()}
            assert set(expected) == set(frame["files"])
            verified.update(executor.map(check_png, expected.items()))
    assert verified == manifest["files"]
    return len(verified)


def boundary_calibration(directory, sample, gt_record, config):
    destination = directory / "calibration" / sample["sample_id"]
    signature = digest({"gt": gt_record["signature"], "visibility": config["visibility"],
                        "validator": file_digest(Path(__file__))})
    record_path = destination / "boundary.json"
    if record_path.exists():
        previous = read_json(record_path)
        arrays_path = destination / "boundary.npz"
        if (previous.get("signature") == signature and arrays_path.is_file()
                and file_digest(arrays_path) == previous.get("arrays_sha256")):
            return previous
    dataset = Path(sample["evaluation_dir"])
    with np.load(dataset / "gt_points.npz", allow_pickle=False) as saved:
        evaluation, registration = saved["evaluation"], saved["registration"]
    with np.load(Path(gt_record["directory"]) / "visibility.npz", allow_pickle=False) as saved:
        labels = saved["labels"]
    mesh = trimesh.load(dataset / "gt_world.ply", process=False, force="mesh")
    options = config["visibility"]
    diagnostics, traced = gt_visibility(
        mesh, registration, gt_record["cameras"][0], tolerance=options["tolerance"],
        batch_size=options["batch_size"], surface_tolerance=options["surface_tolerance"],
        parallel_epsilon=options["parallel_epsilon"])
    distances, nearest = cKDTree(evaluation).query(registration, workers=1)
    inherited = labels[nearest]
    valid = (traced["labels"] != 3) & (inherited != 3)
    confusion = np.zeros((3, 3), dtype=np.int64)
    np.add.at(confusion, (traced["labels"][valid], inherited[valid]), 1)
    record = {
        "signature": signature, "sample_id": sample["sample_id"], "points": len(registration),
        "direct_visibility": diagnostics, "valid": int(valid.sum()),
        "disagreement": int((traced["labels"][valid] != inherited[valid]).sum()),
        "disagreement_rate": float((traced["labels"][valid] != inherited[valid]).mean()),
        "label_order": ["out_of_view", "visible", "occluded"],
        "confusion_direct_rows_inherited_columns": confusion.tolist(),
        "nearest_distance_mean": float(distances.mean()),
    }
    arrays_path = destination / "boundary.npz"
    save_npz(arrays_path, direct_labels=traced["labels"], inherited_labels=inherited,
             nearest_gt=nearest, nearest_distance=distances)
    record["arrays_sha256"] = file_digest(arrays_path)
    atomic_json(record_path, record)
    return record


def verify_preserved_protocol(root, checksum):
    for name in ("evaluation_protocol.md", "evaluation_protocol_v0.md", "archived/evaluation_protocol_v0.md"):
        path = root / "docs" / name
        if path.is_file() and file_digest(path) == checksum:
            return {"old_protocol_path": str(path), "old_protocol_sha256": checksum}
    raise AssertionError("Previous protocol content differs from its pre-run snapshot")


def validate(directory, previous_directory):
    before = read_json(REPO_ROOT / ".runtime/logs/baseline-v05-20261110/before.json")
    protocol = verify_preserved_protocol(REPO_ROOT, before["docs/evaluation_protocol.md"])
    plan = read_json(directory / "plan.json")
    profile = read_json(directory.parent / "profile.json")
    metric_config = read_json(Path(profile["multiview_profile"]))["config"]
    index = read_json(directory / "index.json")
    report = read_json(directory / "summary.json")
    assert plan["mode"] == "calibration"
    assert plan["selected_seeds"] == [42]
    assert len(plan["candidates"]) == 70
    assert len(index["results"]) == 70
    assert report["status_counts"] == {"complete": 70, "failed": 0}
    assert report["pending_stages"] == 0
    previous = {}
    for row in read_json(previous_directory / "index.json")["results"]:
        record = read_json(Path(row["result_path"]))
        if record["status"] == "complete":
            previous[(record["sample_id"], record["method"], record["stage"])] = record
    results = []
    references = {}
    png_count = 0
    max_cd_delta = 0.
    for row in index["results"]:
        result_path = Path(row["result_path"])
        assert file_digest(result_path) == row["result_sha256"]
        record = read_json(result_path)
        assert record["status"] == record["numerical_status"] == "complete"
        for name, checksum in record["files"].items():
            assert file_digest(result_path.parent / name) == checksum
        reference_path = Path(record["reference"])
        if record["sample_id"] not in references:
            gt = read_json(reference_path)
            gt["directory"] = str(reference_path.parent)
            assert gt["visibility"]["status"] == "complete"
            assert gt["visibility"]["invalid"] == 0
            assert len(gt["cameras"]) == 31
            assert gt["cameras"][0]["resolution"] == 504
            assert all(view["resolution"] == 512 for view in gt["cameras"][1:])
            elevations = [view["elevation_degrees"] for view in gt["cameras"][1:]]
            assert sum(e > 0 for e in elevations) == sum(e < 0 for e in elevations) == 15
            for name, checksum in gt["files"].items():
                assert file_digest(reference_path.parent / name) == checksum
            maps = load_render_groups(reference_path.parent / "geometry.npz")
            surfel = load_render_groups(reference_path.parent / "surfel.npz")
            png_count += check_manifest(reference_path.parent, gt["artifacts"],
                                        {"native": maps, "surfel": surfel}, maps, reference_only=True)
            source = Path(record["source_directory"])
            sample = read_json(source.parents[2] / "input.json")
            dataset = Path(sample["evaluation_dir"])
            camera = gt["cameras"][0]
            y, x, side = camera["crop_y_x_side"]
            original_K = np.asarray(read_json(dataset / "camera.json")["K"])
            crop = np.array([[504 / side, 0, -504 * x / side],
                             [0, 504 / side, -504 * y / side], [0, 0, 1]])
            crop_error = float(np.abs(crop @ original_K - np.asarray(camera["K"])).max())
            assert crop_error < 1e-9
            with np.load(dataset / "gt_depth.npz", allow_pickle=False) as saved:
                mask, depth = saved["mask"].astype(bool), saved["depth"]
            np.testing.assert_array_equal(mask, maps["input"]["mask"][0])
            depth_error = float(np.abs(depth[mask] - maps["input"]["depth"][0][mask]).mean())
            assert depth_error < 1e-5
            boundary = boundary_calibration(directory, sample, gt, plan["config"])
            assert boundary["direct_visibility"]["invalid"] == 0
            with np.load(dataset / "gt_points.npz", allow_pickle=False) as saved:
                gt_points = saved["evaluation"]
            with np.load(reference_path.parent / "visibility.npz", allow_pickle=False) as saved:
                self_regions, _ = region_metrics(gt_points, gt_points, saved["labels"])
            assert self_regions["visible"]["metrics"]["cd_euclidean_mean"] == 0.
            references[record["sample_id"]] = {
                "record": gt, "maps": maps, "crop_matrix_error": crop_error,
                "native_input_depth_mae": depth_error, "boundary": boundary}
        reference = references[record["sample_id"]]
        representations = {
            name: load_render_groups(result_path.parent / f"{name}.npz")
            for name in ("surfel", "native") if f"{name}.npz" in record["files"]}
        png_count += check_manifest(result_path.parent, record["artifacts"], representations, reference["maps"],
                                    comparisons=record["comparisons"], metric_config=metric_config)
        for comparison in record["comparisons"].values():
            assert len(comparison["multiview"]["views"]) == 30
        assert record["regions"]["visible"]["status"] == "complete"
        with np.load(result_path.parent / "distances.npz", allow_pickle=False) as saved:
            for prefix, metrics in (("full", record["shape"]),
                                    ("visible", record["regions"]["visible"]["metrics"])):
                value = (saved[f"{prefix}_pred_to_gt"].mean() + saved[f"{prefix}_gt_to_pred"].mean()) / 2
                assert abs(value - metrics["cd_euclidean_mean"]) < 1e-14
        if record["stage"] == "glb":
            pair = record["export_pair"]
            assert pair["status"] == "complete"
            decoded_path = Path(pair["decoded_result"])
            assert file_digest(decoded_path) == pair["decoded_result_sha256"]
            decoded = read_json(decoded_path)
            assert decoded["seed"] == record["seed"]
            np.testing.assert_array_equal(pair["matrix"], decoded["registration"]["matrix"])
        previous_record = previous[(record["sample_id"], record["method"], record["stage"])]
        delta = abs(record["shape"]["cd_euclidean_mean"] - previous_record["shape"]["cd_euclidean_mean"])
        assert delta < 1e-10
        max_cd_delta = max(max_cd_delta, delta)
        results.append({"sample_id": record["sample_id"], "method": record["method"],
                        "stage": record["stage"], "full_cd_delta_from_previous": delta,
                        "png_count": record["artifacts"]["file_count"]})
        print(f"validated {len(results)}/70 {record['sample_id']} {record['method']} {record['stage']}", flush=True)
    return {
        "status": "passed", "revision": index["revision"], "stages": len(results),
        "png_count": png_count, "gt_assets": len(references),
        "recomputed_render_metrics": [
            "depth_mae", "depth_rmse", "silhouette_iou", "normal_mean_angle",
            "normal_psnr", "normal_mse", "depth_coverage", "normal_coverage", "pixel_counts"],
        "previous_full_cd_max_delta": max_cd_delta,
        **protocol, "validator_sha256": file_digest(Path(__file__)),
        "index_sha256": file_digest(directory / "index.json"), "stages_checked": results,
        "assets": [{key: value for key, value in reference.items() if key != "maps"}
                   for reference in references.values()]}


def markdown(report):
    lines = ["# P0 v0.5 校准", "",
             f"完成 {report['stages']} 个阶段、{report['gt_assets']} 个 GT 资产，"
             f"逐文件摘要及像素数组核对 {report['png_count']} 张 PNG。", "",
             f"与上一轮相同采样及配准的完整 CD-L1 最大差值为 {report['previous_full_cd_max_delta']:.3g}。", "",
             "可见性容差冻结为 1e-4D，表面端点校正上限为 1e-6D，近切线阈值为 1e-12。", "",
             "| 资产 | 可见 GT 点 | 5e-5D 标签变化 | 2e-4D 标签变化 | 最大端点校正 | 标签传递分歧率 | GT surfel 输入法线角误差 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for asset in report["assets"]:
        visibility = asset["record"]["visibility"]
        normal = asset["record"]["surfel_vs_native"]["input"]["metrics"]["normal_mean_angle"]
        boundary = asset["boundary"]
        lines.append(f"| {boundary['sample_id']} | {visibility['counts']['visible']} | "
                     f"{visibility['sensitivity']['5e-05']['changed_from_default']} | "
                     f"{visibility['sensitivity']['0.0002']['changed_from_default']} | "
                     f"{visibility['surface_projection_max']:.3g}D | "
                     f"{boundary['disagreement_rate']:.2%} | {normal:.4f}° |")
    lines += ["", "标签传递分歧率通过独立的 10,000 个 GT 配准采样点测量，"
              "比较直接射线标签与最近 GT 评价点继承标签。"
              "该值量化有限采样下的区域边界误差。"
              "GT surfel 法线差异记录表示转换造成的误差，直接保留在方法指标中。", "",
              "[评测结果](summary.md) · [渲染产物](render_index.md)", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--previous-evaluation", type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.evaluation, args.previous_evaluation)
    atomic_json(args.evaluation / "calibration.json", report)
    (args.evaluation / "calibration.md").write_text(markdown(report))
    print({name: report[name] for name in ("status", "stages", "png_count", "gt_assets")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
