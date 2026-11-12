"""Verify a completed OOD evaluation using the existing v0.5 PNG and metric checks."""
import argparse
from pathlib import Path

import numpy as np

from evaluation.render_artifacts import load_render_groups
from evaluation.visibility import region_metrics
from examples.validate_baseline_v05 import check_manifest
from wt.experiment import atomic_json, digest, file_digest, read_json, resolve_reference


def verify_distances(saved, prefix, metrics):
    forward = saved[prefix + "_pred_to_gt"]
    backward = saved[prefix + "_gt_to_pred"]
    actual = {
        "cd_euclidean_mean": (forward.mean() + backward.mean()) / 2,
        "cd_squared_mean": ((forward ** 2).mean() + (backward ** 2).mean()) / 2,
    }
    for threshold in (.01, .05):
        precision = float((forward < threshold).mean())
        recall = float((backward < threshold).mean())
        score = 2 * precision * recall / (precision + recall) if precision + recall else 0.
        for name, value in (("precision", precision), ("recall", recall), ("f", score)):
            actual[f"{name}@{threshold:.2f}"] = value
    for name, value in actual.items():
        np.testing.assert_allclose(value, metrics[name], rtol=0, atol=1e-14, err_msg=name)


def verify_camera(sample, reference, maps):
    dataset = Path(sample["evaluation_dir"])
    for name, checksum in sample["artifact_sha256"].items():
        assert file_digest(dataset / name) == checksum, dataset / name
    camera = reference["cameras"][0]
    original = read_json(dataset / "camera.json")
    y, x, side = camera["crop_y_x_side"]
    crop = np.array([[504 / side, 0, -504 * x / side],
                     [0, 504 / side, -504 * y / side], [0, 0, 1]])
    error = float(np.abs(crop @ np.asarray(original["K"]) - np.asarray(camera["K"])).max())
    assert error < 1e-9
    np.testing.assert_array_equal(original["T_world_to_camera"], camera["T_world_to_camera"])
    with np.load(dataset / "gt_depth.npz", allow_pickle=False) as saved:
        mask, depth = saved["mask"], saved["depth"]
    np.testing.assert_array_equal(mask, maps["input"]["mask"][0])
    depth_error = float(np.abs(depth[mask] - maps["input"]["depth"][0][mask]).mean())
    assert depth_error < 1e-5
    with np.load(dataset / "gt_points.npz", allow_pickle=False) as saved:
        points = saved["evaluation"]
    with np.load(Path(reference["directory"]) / "visibility.npz", allow_pickle=False) as saved:
        self_regions, _ = region_metrics(points, points, saved["labels"])
    for region in self_regions.values():
        if region["status"] == "complete":
            assert region["metrics"]["cd_euclidean_mean"] == 0
            assert region["metrics"]["cd_squared_mean"] == 0
            assert region["metrics"]["f@0.01"] == 1
    return {"crop_matrix_error": error, "native_input_depth_mae": depth_error,
            "native_mask_equal": True, "visibility": reference["visibility"],
            "self_regions": self_regions}


def audit(experiment):
    pointer = read_json(experiment / "baseline_evaluation.json")
    root = Path(pointer["directory"])
    index = read_json(root / "index.json")
    summary = read_json(root / "summary.json")
    assert summary["pending_stages"] == 0
    assert summary["index_sha256"] == file_digest(root / "index.json")
    profile = read_json(root.parent / "profile.json")
    metric_config = read_json(Path(profile["multiview_profile"]))["config"]
    checked, references, runs = [], {}, set()
    verified_sources = {}
    reference_path = None
    gt_maps = None
    for row in index["results"]:
        result_path = Path(row["result_path"])
        assert file_digest(result_path) == row["result_sha256"]
        result = read_json(result_path)
        assert result["revision"] == index["revision"]
        if row["status"] != "complete":
            checked.append({"sample_id": row["sample_id"], "method": row["method"],
                            "stage": row["stage"], "status": row["status"], "png_count": 0})
            continue
        for name, checksum in result["inputs"].items():
            if name not in verified_sources:
                verified_sources[name] = file_digest(Path(name))
            assert verified_sources[name] == checksum, name
        source = Path(result["source_directory"])
        sample = read_json(source.parents[2] / "input.json")
        if source not in runs:
            state = read_json(source / "run.json")
            assert state["status"] == "complete"
            config = read_json(source / "config.json")
            assert state["config_hash"] == digest({
                "config": config["parameters"], "provenance": config["provenance"]})
            assert state["input_sha256"] == sample["sha256"] == file_digest(Path(sample["image"]))
            assert state["artifacts"]
            for artifact in state["artifacts"].values():
                assert resolve_reference(source, artifact["path"]).is_file()
            runs.add(source)
        for name, checksum in result["files"].items():
            assert file_digest(result_path.parent / name) == checksum
        current = Path(result["reference"])
        if current != reference_path:
            gt = read_json(current)
            gt_maps = load_render_groups(current.parent / "geometry.npz")
            reference_path = current
        if str(current) not in references:
            for name, checksum in gt["files"].items():
                assert file_digest(current.parent / name) == checksum
            surfel = load_render_groups(current.parent / "surfel.npz")
            assert len(gt["cameras"]) == 31
            assert sum(camera["elevation_degrees"] > 0 for camera in gt["cameras"][1:]) == 15
            count = check_manifest(current.parent, gt["artifacts"],
                                   {"native": gt_maps, "surfel": surfel}, gt_maps, reference_only=True)
            references[str(current)] = {
                "sample_id": row["sample_id"], "png_count": count,
                "result_sha256": file_digest(current),
                **verify_camera(sample, {**gt, "directory": str(current.parent)}, gt_maps),
            }
            del surfel
        representations = {
            name: load_render_groups(result_path.parent / (name + ".npz"))
            for name in ("surfel", "native") if name + ".npz" in result["files"]}
        count = check_manifest(result_path.parent, result["artifacts"], representations, gt_maps,
                               comparisons=result["comparisons"], metric_config=metric_config)
        with np.load(result_path.parent / "distances.npz", allow_pickle=False) as saved:
            verify_distances(saved, "full", result["shape"])
            for region, value in result["regions"].items():
                if value["status"] == "complete":
                    verify_distances(saved, region, value["metrics"])
        if result["stage"] == "glb":
            pair = result["export_pair"]
            assert pair["status"] == "complete"
            decoded_path = Path(pair["decoded_result"])
            assert file_digest(decoded_path) == pair["decoded_result_sha256"]
            decoded = read_json(decoded_path)
            np.testing.assert_array_equal(pair["matrix"], decoded["registration"]["matrix"])
            with np.load(result_path.parent / "export_pair_distances.npz", allow_pickle=False) as saved:
                verify_distances(saved, "full", pair["glb"]["shape"])
        checked.append({"sample_id": row["sample_id"], "method": row["method"],
                        "stage": row["stage"], "status": "complete", "png_count": count})
        atomic_json(root / "audit_progress.json", {"checked": len(checked), "planned": len(index["results"])})
        print(f"AUDIT {len(checked)}/{len(index['results'])} {row['sample_id']} {row['stage']}", flush=True)
        del representations
    report = {
        "status": "passed", "revision": index["revision"],
        "index_sha256": file_digest(root / "index.json"),
        "stages": len(checked), "inference_runs": len(runs), "gt_assets": len(references),
        "png_count": sum(row["png_count"] for row in checked) + sum(row["png_count"] for row in references.values()),
        "failed_stages": sum(row["status"] != "complete" for row in checked),
        "source_sha256": file_digest(Path(__file__)),
        "recomputed_metrics": "CD-L1/L2, precision/recall/F, depth, masks, normals, coverage and pixel counts",
        "lpips_verification": "Saved output and provenance hashes",
        "references": references, "results": checked,
    }
    atomic_json(root / "audit.json", report)
    print({key: report[key] for key in ("status", "stages", "gt_assets", "png_count", "failed_stages")})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    audit(args.experiment)
