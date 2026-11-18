"""Recompute direct input and multi-view depth metrics from frozen baseline NPZ files."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import numpy as np

from evaluation.multiview import METRIC_UNITS, depth_frame_metrics
from examples.summarize_baseline_v2 import distribution
from wt.experiment import atomic_json, digest, file_digest, read_json
from wt.paths import REPO_ROOT

SOURCES = ("evaluation/multiview.py", "examples/review_cached_depth.py",
           "examples/summarize_baseline_v2.py")


def load_depth_groups(path, expected_digest, *, include_normals=False):
    before = path.stat()
    if file_digest(path) != expected_digest:
        raise ValueError(f"Cache digest mismatch: {path}")
    fields = ("depth", "mask", "normals", "normal_valid") if include_normals else ("depth", "mask")
    with np.load(path, allow_pickle=False) as arrays:
        groups = {group: {name: arrays[f"{group}_{name}"] for name in fields}
                  for group in ("input", "multiview")}
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Cache changed while reading: {path}")
    return groups


def review_depth_groups(prediction, reference, stored):
    comparisons = {}
    for group in ("input", "multiview"):
        predicted, target = prediction[group], reference[group]
        if predicted["depth"].shape != target["depth"].shape:
            raise ValueError(f"Depth grid mismatch: {group}")
        if (predicted["mask"].shape != predicted["depth"].shape
                or target["mask"].shape != target["depth"].shape):
            raise ValueError(f"Mask grid mismatch: {group}")
        old_views = [stored["input"]] if group == "input" else stored["multiview"]["views"]
        if len(old_views) != len(target["depth"]):
            raise ValueError(f"View count mismatch: {group}")
        if group == "input" and len(old_views) != 1:
            raise ValueError("Expected exactly one input view")
        views = []
        for index, old in enumerate(old_views):
            current = depth_frame_metrics(
                {name: values[index] for name, values in predicted.items()},
                {name: values[index] for name, values in target.items()},
            )
            for name, value in current["metrics"].items():
                if name not in old["metrics"]:
                    continue
                expected = old["metrics"][name]
                if value is None or expected is None:
                    if value is not expected:
                        raise ValueError(f"Metric validity mismatch: {group}/{index}/{name}")
                else:
                    np.testing.assert_allclose(value, expected, rtol=0, atol=1e-12,
                                               err_msg=f"{group}/{index}/{name}")
            for name, value in current["pixels"].items():
                if value != old["pixels"][name]:
                    raise ValueError(f"Pixel count mismatch: {group}/{index}/{name}")
            views.append(current)
        if group == "input":
            comparisons[group] = views[0]
            continue
        metrics = []
        for name in views[0]["metrics"]:
            valid = [view["metrics"][name] for view in views
                     if view["metrics"][name] is not None and np.isfinite(view["metrics"][name])]
            complete = len(valid) == len(views)
            metrics.append({
                "metric": name, "unit": METRIC_UNITS[name],
                "value": float(np.mean(valid)) if complete else None,
                "status": "complete" if complete else "failed",
                "valid_views": len(valid), "total_views": len(views),
            })
        comparisons[group] = {"views": views, "metrics": metrics}
    return comparisons


def inspect_asset(rows):
    records = []
    reference_path = None
    for row in rows:
        result_path = Path(row["result_path"])
        if file_digest(result_path) != row["result_sha256"]:
            raise ValueError(f"Result digest mismatch: {result_path}")
        result = read_json(result_path)
        if result["status"] != "complete":
            raise ValueError(f"Candidate incomplete: {result_path}")
        current_reference = Path(result["reference"])
        if reference_path is None:
            reference_path = current_reference
            reference = read_json(reference_path)
            reference_sha = file_digest(reference_path)
            target_path = reference_path.parent / "geometry.npz"
            target_sha = reference["files"]["geometry.npz"]
            target = load_depth_groups(target_path, target_sha)
        if current_reference != reference_path:
            raise ValueError(f"GT reference mismatch within asset: {row['sample_id']}")
        comparisons = {}
        sources = {
            str(result_path): row["result_sha256"],
            str(reference_path): reference_sha,
            str(target_path): target_sha,
        }
        for representation in ("surfel", "native"):
            if representation not in result["comparisons"]:
                continue
            stored = result["comparisons"][representation]
            cache_path = result_path.parent / f"{representation}.npz"
            expected = result["files"][cache_path.name]
            prediction = load_depth_groups(cache_path, expected)
            comparisons[representation] = review_depth_groups(prediction, target, stored)
            sources[str(cache_path)] = expected
        records.append({
            **{key: row[key] for key in ("sample_id", "method", "config_id", "seed", "stage")},
            "result_path": str(result_path), "source_files": sources,
            "registration_sha256": digest(result["registration"]["matrix"]),
            "cameras_sha256": digest(reference["cameras"]),
            "comparisons": comparisons,
        })
    return records


def aggregate(records):
    buckets = defaultdict(lambda: defaultdict(list))
    asset_counts = defaultdict(int)
    for record in records:
        for representation, comparison in record["comparisons"].items():
            for group in ("input", "multiview"):
                key = (record["method"], record["stage"], representation, group)
                asset_counts[key] += 1
                values = (comparison["input"]["metrics"] if group == "input" else
                          {row["metric"]: row["value"] for row in comparison["multiview"]["metrics"]
                           if row["status"] == "complete"})
                for name, value in values.items():
                    if value is not None and np.isfinite(value):
                        buckets[key][name].append(value)
    return [
        {"method": key[0], "stage": key[1], "representation": key[2], "view": key[3],
         "assets": asset_counts[key],
         "metrics": {name: distribution(values) for name, values in buckets[key].items()}}
        for key in sorted(asset_counts)
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    started = time.monotonic()
    index_path = args.evaluation / "index.json"
    index_sha = file_digest(index_path)
    sources = {name: file_digest(REPO_ROOT / name) for name in SOURCES}
    index = read_json(index_path)
    by_asset = defaultdict(list)
    for row in index["results"]:
        if row["seed"] == args.seed:
            by_asset[row["sample_id"]].append(row)
    if not by_asset:
        raise ValueError(f"No candidates for seed {args.seed}")
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        groups = [by_asset[sample_id] for sample_id in sorted(by_asset)]
        for completed, rows in enumerate(executor.map(inspect_asset, groups), 1):
            records.extend(rows)
            print(f"Reviewed {completed}/{len(groups)} assets, {len(records)} candidates", flush=True)
    if file_digest(index_path) != index_sha:
        raise ValueError("Evaluation index changed during review")
    if any(file_digest(REPO_ROOT / name) != checksum for name, checksum in sources.items()):
        raise ValueError("Metric source changed during review")
    provenance = {"evaluation_revision": index["revision"], "index_sha256": index_sha,
                  "seeds": [args.seed], "sources": sources}
    report = {
        **provenance, "review_revision": digest(provenance)[:20], "status": "passed",
        "alignment": "full-shape Sim(3), fixed evaluation cameras",
        "aggregation": "equal views within each asset, then equal valid assets",
        "candidate_count": len(records), "asset_count": len(by_asset),
        "representation_count": sum(len(row["comparisons"]) for row in records),
        "groups": aggregate(records), "records": records,
    }
    atomic_json(args.output, report)
    print({"status": "passed", "candidates": len(records), "assets": len(by_asset),
           "review_revision": report["review_revision"],
           "seconds": round(time.monotonic() - started, 2), "output": str(args.output)}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
