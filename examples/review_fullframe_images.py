"""Recompute full-frame image errors while reusing verified whole-image LPIPS scores."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import numpy as np

from evaluation.multiview import depth_image_comparison, normal_image_comparison
from examples.review_cached_depth import aggregate, load_depth_groups
from examples.review_cached_images import summarize_views
from wt.experiment import atomic_json, digest, file_digest, read_json
from wt.paths import REPO_ROOT

SOURCES = ("evaluation/multiview.py", "evaluation/render_artifacts.py",
           "examples/review_cached_depth.py", "examples/review_cached_images.py",
           "examples/review_fullframe_images.py", "examples/summarize_baseline_v2.py")


def update_frame(prediction, reference, previous, config):
    depth = depth_image_comparison(prediction, reference, config)
    normals = normal_image_comparison(prediction, reference, config)
    for name in ("depth_limits_D", "background_intensity", "pred_valid_pixels",
                 "pred_clipped_pixels", "pred_clipped_fraction"):
        actual, expected = depth["encoding"][name], previous["depth_image_encoding"][name]
        if actual is None or expected is None:
            if actual is not expected:
                raise ValueError(f"Depth image encoding changed: {name}")
        else:
            np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12, err_msg=name)
    # The two encoders use each image's own mask and the same neutral background.
    # Changing the averaging domain leaves their LPIPS input images identical.
    values = {**previous["metrics"], **depth["metrics"], **normals["metrics"]}
    values["depth_image_lpips"] = previous["metrics"]["depth_image_lpips"]
    return {**previous, "metrics": values, "depth_image_encoding": depth["encoding"],
            "image_metric_region": "full_frame"}


def inspect_asset(rows, config):
    records = []
    target = None
    for row in rows:
        result_path = Path(row["result_path"])
        if file_digest(result_path) != row["source_files"][str(result_path)]:
            raise ValueError(f"Result digest mismatch: {result_path}")
        original = read_json(result_path)
        if target is None:
            reference_path = Path(original["reference"])
            reference = read_json(reference_path)
            target_path = reference_path.parent/"geometry.npz"
            target = load_depth_groups(target_path, row["source_files"][str(target_path)],
                                       include_normals=True)
        if Path(original["reference"]) != reference_path:
            raise ValueError("GT reference differs within asset")
        comparisons = {}
        for representation, previous in row["comparisons"].items():
            cache = result_path.parent/f"{representation}.npz"
            prediction = load_depth_groups(cache, row["source_files"][str(cache)],
                                           include_normals=True)
            comparison = {}
            for group in ("input", "multiview"):
                old = [previous["input"]] if group == "input" else previous["multiview"]["views"]
                if prediction[group]["depth"].shape != target[group]["depth"].shape:
                    raise ValueError("Depth grids differ")
                if len(old) != len(target[group]["depth"]):
                    raise ValueError("View counts differ")
                frames = [update_frame(
                    {name: value[index] for name, value in prediction[group].items()},
                    {name: value[index] for name, value in target[group].items()},
                    frame, config,
                ) for index, frame in enumerate(old)]
                comparison[group] = frames[0] if group == "input" else summarize_views(frames, config)
            comparisons[representation] = comparison
        records.append({**row, "comparisons": comparisons})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=REPO_ROOT/"configs/multiview_baseline_v2.json")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    started = time.monotonic()
    upstream_sha = file_digest(args.upstream)
    upstream = read_json(args.upstream)
    config = read_json(args.config)
    if config.get("image_metric_region") != "full_frame":
        raise ValueError("Expected full-frame image configuration")
    if config.get("multiview_physical_depth_metrics") is not False:
        raise ValueError("Expected image-only multiview metric selection")
    previous_config = dict(upstream["config"])
    comparable_config = {key: value for key, value in config.items()
                         if key not in ("image_metric_region", "multiview_physical_depth_metrics")}
    if comparable_config != previous_config:
        raise ValueError("Image encoding configuration differs from upstream LPIPS inputs")
    sources = {name: file_digest(REPO_ROOT/name) for name in SOURCES}
    config_sha = file_digest(args.config)
    assets = defaultdict(list)
    for row in upstream["records"]:
        assets[row["sample_id"]].append(row)
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = executor.map(lambda rows: inspect_asset(rows, config),
                               [assets[key] for key in sorted(assets)])
        for completed, rows in enumerate(futures, 1):
            records.extend(rows)
            print(f"Reviewed {completed}/{len(assets)} assets, {len(records)} candidates", flush=True)
    if file_digest(args.upstream) != upstream_sha or file_digest(args.config) != config_sha:
        raise ValueError("Input review or configuration changed")
    if any(file_digest(REPO_ROOT/name) != checksum for name, checksum in sources.items()):
        raise ValueError("Metric implementation changed during review")
    provenance = {
        "evaluation_revision": upstream["evaluation_revision"],
        "index_sha256": upstream["index_sha256"], "seeds": upstream["seeds"],
        "upstream": str(args.upstream), "upstream_sha256": upstream_sha,
        "upstream_review_revision": upstream["review_revision"],
        "config": config, "config_sha256": config_sha, "sources": sources,
    }
    report = {
        **provenance, "review_revision": digest(provenance)[:20], "status": "passed",
        "candidate_count": len(records), "asset_count": len(assets),
        "representation_count": sum(len(row["comparisons"]) for row in records),
        "lpips_provenance": {"reuse_reason": "Identical signed RGB inputs and whole-frame LPIPS",
                             "batch_parity": upstream["batch_parity"], "weights": upstream["weights"]},
        "groups": aggregate(records), "records": records,
    }
    atomic_json(args.output, report)
    print({"status": "passed", "review_revision": report["review_revision"],
           "assets": len(assets), "candidates": len(records),
           "seconds": round(time.monotonic()-started, 2), "output": str(args.output)}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
