"""Add depth-image similarity and normal RMSE to frozen baseline render results."""
import argparse
from collections import defaultdict
import importlib.metadata
from pathlib import Path
import time

import numpy as np

from evaluation.multiview import (
    METRIC_UNITS, PHYSICAL_DEPTH_METRICS, NormalLPIPS, depth_frame_metrics,
    depth_image_comparison, normal_image_comparison,
)
from examples.review_cached_depth import aggregate, load_depth_groups
from wt.experiment import atomic_json, digest, file_digest, read_json
from wt.paths import CACHE_ROOT, REPO_ROOT, WEIGHTS_ROOT, configure_cache_paths

SOURCES = ("evaluation/multiview.py", "evaluation/render_artifacts.py",
           "examples/review_cached_images.py", "examples/review_cached_depth.py",
           "examples/summarize_baseline_v2.py")


def review_views(predicted, target, stored, config, metric, batch_size, verify_batch=False):
    if predicted["depth"].shape != target["depth"].shape or len(stored) != len(target["depth"]):
        raise ValueError("Depth grids or view counts differ")
    frames = []
    largest_error = 0.
    for start in range(0, len(stored), batch_size):
        comparisons = []
        for index in range(start, min(start + batch_size, len(stored))):
            prediction = {name: values[index] for name, values in predicted.items()}
            reference = {name: values[index] for name, values in target.items()}
            direct = depth_frame_metrics(prediction, reference)
            for name in ("depth_mae", "depth_rmse", "silhouette_iou", "depth_coverage"):
                actual, expected = direct["metrics"][name], stored[index]["metrics"][name]
                if actual is None or expected is None:
                    if actual is not expected:
                        raise ValueError(f"Cached metric validity mismatch: {name}")
                else:
                    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12, err_msg=name)
            for name, value in direct["pixels"].items():
                if value != stored[index]["pixels"][name]:
                    raise ValueError(f"Cached pixel count mismatch: {name}")
            comparison = depth_image_comparison(prediction, reference, config)
            values = {**stored[index]["metrics"], **comparison["metrics"]}
            region = config.get("image_metric_region", "valid_intersection")
            if region == "full_frame":
                values.update(normal_image_comparison(prediction, reference, config)["metrics"])
            else:
                mse = values["normal_mse"]
                values["normal_rmse"] = None if mse is None else float(np.sqrt(mse))
            frames.append({"metrics": values, "pixels": stored[index]["pixels"],
                           "image_metric_region": region,
                           "depth_image_encoding": comparison["encoding"]})
            comparisons.append(comparison)
        prediction_rgb = np.stack([row["prediction_rgb"] for row in comparisons])
        reference_rgb = np.stack([row["reference_rgb"] for row in comparisons])
        scores = metric.batch(prediction_rgb, reference_rgb)
        if len(scores) != len(comparisons) or not np.isfinite(scores).all():
            raise ValueError("Invalid LPIPS batch output")
        if verify_batch and start == 0:
            scalar = metric(prediction_rgb[0], reference_rgb[0])
            largest_error = abs(float(scores[0]) - scalar)
            np.testing.assert_allclose(scores[0], scalar, rtol=0, atol=1e-5)
        for frame, score in zip(frames[start:], scores):
            frame["metrics"]["depth_image_lpips"] = float(score)
    return frames, largest_error


def summarize_views(frames, config=None):
    config = config or {}
    rows = []
    for name in frames[0]["metrics"]:
        if name in PHYSICAL_DEPTH_METRICS and not config.get("multiview_physical_depth_metrics", True):
            continue
        valid = [frame["metrics"][name] for frame in frames
                 if frame["metrics"][name] is not None and np.isfinite(frame["metrics"][name])]
        complete = len(valid) == len(frames)
        rows.append({"metric": name, "unit": METRIC_UNITS[name],
                     "value": float(np.mean(valid)) if complete else None,
                     "status": "complete" if complete else "failed",
                     "valid_views": len(valid), "total_views": len(frames)})
    return {"views": frames, "metrics": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=REPO_ROOT/"configs/multiview_baseline_v2.json")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    configure_cache_paths()
    started = time.monotonic()
    config = read_json(args.config)
    include_normals = config.get("image_metric_region", "valid_intersection") == "full_frame"
    environment = read_json(CACHE_ROOT/"multiview_environment.json")
    weights = {
        WEIGHTS_ROOT/"torch/hub/checkpoints/alexnet-owt-7be5be79.pth": config["alexnet_sha256"],
        Path(environment["lpips_linear"]["path"]): config["lpips_linear_sha256"],
    }
    for path, expected in weights.items():
        if file_digest(path) != expected:
            raise ValueError(f"LPIPS weight checksum mismatch: {path}")
    import torch
    torch.set_num_threads(4)
    metric = NormalLPIPS(args.device)
    sources = {name: file_digest(REPO_ROOT/name) for name in SOURCES}
    config_sha = file_digest(args.config)
    index_path = args.evaluation/"index.json"
    index_sha = file_digest(index_path)
    index = read_json(index_path)
    assets = defaultdict(list)
    for row in index["results"]:
        if row["seed"] == args.seed:
            assets[row["sample_id"]].append(row)
    if not assets:
        raise ValueError("No candidates for requested seed")
    records = []
    max_batch_error = 0.
    batch_checks = 0
    for completed, (sample_id, candidates) in enumerate(sorted(assets.items()), 1):
        target = None
        for row in candidates:
            result_path = Path(row["result_path"])
            if file_digest(result_path) != row["result_sha256"]:
                raise ValueError(f"Result digest mismatch: {result_path}")
            result = read_json(result_path)
            if result["status"] != "complete":
                raise ValueError(f"Candidate incomplete: {result_path}")
            if target is None:
                reference_path = Path(result["reference"])
                reference = read_json(reference_path)
                reference_sha = file_digest(reference_path)
                target_path = reference_path.parent/"geometry.npz"
                target_sha = reference["files"]["geometry.npz"]
                target = load_depth_groups(target_path, target_sha, include_normals=include_normals)
            if Path(result["reference"]) != reference_path:
                raise ValueError("GT reference differs within asset")
            comparisons = {}
            files = {str(result_path): row["result_sha256"], str(reference_path): reference_sha,
                     str(target_path): target_sha}
            for representation in ("surfel", "native"):
                if representation not in result["comparisons"]:
                    continue
                cache = result_path.parent/f"{representation}.npz"
                expected = result["files"][cache.name]
                prediction = load_depth_groups(cache, expected, include_normals=include_normals)
                files[str(cache)] = expected
                stored = result["comparisons"][representation]
                comparison = {}
                for group in ("input", "multiview"):
                    old = [stored["input"]] if group == "input" else stored["multiview"]["views"]
                    frames, error = review_views(prediction[group], target[group], old,
                                                 config, metric, args.batch_size, completed == 1)
                    max_batch_error = max(max_batch_error, error)
                    batch_checks += int(completed == 1)
                    comparison[group] = frames[0] if group == "input" else summarize_views(frames, config)
                comparisons[representation] = comparison
            records.append({
                **{key: row[key] for key in ("sample_id", "method", "config_id", "seed", "stage")},
                "result_path": str(result_path), "source_files": files,
                "registration_sha256": digest(result["registration"]["matrix"]),
                "cameras_sha256": digest(reference["cameras"]),
                "comparisons": comparisons,
            })
        print(f"Reviewed {completed}/{len(assets)} assets, {len(records)} candidates", flush=True)
    if file_digest(index_path) != index_sha or file_digest(args.config) != config_sha:
        raise ValueError("Input index or configuration changed")
    if any(file_digest(REPO_ROOT/name) != checksum for name, checksum in sources.items()):
        raise ValueError("Metric implementation changed during review")
    provenance = {
        "evaluation_revision": index["revision"], "index_sha256": index_sha,
        "seeds": [args.seed], "sources": sources, "config": config, "config_sha256": config_sha,
        "weights": {str(path): checksum for path, checksum in weights.items()},
        "versions": {name: importlib.metadata.version(name) for name in ["numpy", "torch", "torchvision", "lpips"]},
        "device": args.device, "batch_size": args.batch_size,
    }
    report = {
        **provenance, "review_revision": digest(provenance)[:20], "status": "passed",
        "candidate_count": len(records), "asset_count": len(assets),
        "representation_count": sum(len(row["comparisons"]) for row in records),
        "batch_parity": {"checks": batch_checks, "max_absolute_difference": max_batch_error, "tolerance": 1e-5},
        "groups": aggregate(records), "records": records,
    }
    atomic_json(args.output, report)
    print({"status": "passed", "assets": len(assets), "candidates": len(records),
           "review_revision": report["review_revision"],
           "seconds": round(time.monotonic()-started, 2), "output": str(args.output)}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
