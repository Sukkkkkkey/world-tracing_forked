"""Compare the frozen OOD single-seed results with GSO and account for category clustering."""
import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np

from examples.summarize_baseline_v2 import distribution
from wt.experiment import atomic_json, file_digest, read_json

METRICS = (
    "shape.cd_euclidean_mean", "shape.cd_squared_mean", "shape.f@0.01", "shape.f@0.05",
    "regions.visible.cd_euclidean_mean", "regions.visible.f@0.01",
    "surfel.input.depth_mae", "surfel.input.depth_rmse", "surfel.input.silhouette_iou",
    "surfel.input.normal_mean_angle", "surfel.input.depth_coverage", "surfel.input.normal_coverage",
    "surfel.input_ssi.mae", "surfel.input_ssi.absrel",
    "surfel.multiview.depth_mae", "surfel.multiview.normal_mean_angle",
)


def paired_categories(report, categories, stage):
    assets = {(row["sample_id"], row["method"], row["stage"]): row["values"]["single_seed"]
              for row in report["assets"]}
    output = {}
    for metric in METRICS:
        pairs = []
        for sample_id, category in categories.items():
            wt = assets.get((sample_id, "wt", "points"), {})
            trellis = assets.get((sample_id, "trellis2", stage), {})
            if metric in wt and metric in trellis:
                pairs.append((sample_id, category, wt[metric], trellis[metric]))
        grouped = defaultdict(list)
        for sample_id, category, wt, trellis in pairs:
            grouped[category].append((wt, trellis))
        if not pairs:
            output[metric] = {"paired_assets": 0}
            continue
        category_rows = []
        sums, counts = [], []
        for category, values in sorted(grouped.items()):
            values = np.asarray(values, dtype=float)
            differences = values[:, 0] - values[:, 1]
            sums.append(differences.sum())
            counts.append(len(values))
            category_rows.append({"category": category, "n": len(values),
                                  "wt_mean": float(values[:, 0].mean()),
                                  "trellis2_mean": float(values[:, 1].mean()),
                                  "difference": float(differences.mean())})
        sums, counts = np.asarray(sums), np.asarray(counts)
        rng = np.random.default_rng(20261111)
        indexes = rng.integers(len(counts), size=(5000, len(counts)))
        clustered = sums[indexes].sum(axis=1) / counts[indexes].sum(axis=1)
        differences = [wt - trellis for _, _, wt, trellis in pairs]
        output[metric] = {
            "difference": "WT minus TRELLIS.2", "paired_assets": len(pairs),
            "sample_ids": [sample for sample, _, _, _ in pairs],
            "wt_mean": float(np.mean([wt for _, _, wt, _ in pairs])),
            "trellis2_mean": float(np.mean([trellis for _, _, _, trellis in pairs])),
            "asset_bootstrap": distribution(differences),
            "category_cluster_bootstrap": {
                "categories": len(counts), "mean": float(sums.sum() / counts.sum()),
                "ci95": np.quantile(clustered, [.025, .975]).tolist(),
                "replicates": 5000, "rng_seed": 20261111,
            },
            "category_macro_bootstrap": distribution([row["difference"] for row in category_rows]),
            "wt_lower": sum(value < 0 for value in differences),
            "wt_higher": sum(value > 0 for value in differences),
            "categories": category_rows,
        }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--gso-summary", type=Path, required=True)
    args = parser.parse_args()
    pointer = read_json(args.experiment / "baseline_evaluation.json")
    root = Path(pointer["directory"])
    report = read_json(root / "summary.json")
    if report["pending_stages"]:
        raise ValueError("The frozen OOD budget is still incomplete")
    samples = [read_json(path) for path in (args.experiment / "samples").glob("*/input.json")]
    categories = {sample["sample_id"]: sample["category"] for sample in samples}
    gso = read_json(args.gso_summary)
    domains = {}
    for name, data in (("ood", report), ("gso", gso)):
        domains[name] = [
            {**{key: group[key] for key in ("method", "stage")},
             "metrics": {metric: group["metrics"].get(metric) for metric in METRICS}}
            for group in data["groups"]
            if group["mode"] == "single_seed" and group["method"] in ("wt", "trellis2")]
    result = {
        "ood_summary_sha256": file_digest(root / "summary.json"),
        "gso_summary": str(args.gso_summary),
        "gso_summary_sha256": file_digest(args.gso_summary),
        "source_sha256": file_digest(Path(__file__)),
        "asset_count": len(samples), "category_count": len(set(categories.values())),
        "status_counts": report["status_counts"], "domains": domains,
        "paired": {stage: paired_categories(report, categories, stage) for stage in ("decoded", "glb")},
        "interpretation": ("Dataset and category shifts accompany the source change; "
                           "these comparisons do not isolate training-data memorization."),
    }
    atomic_json(root / "ood_analysis.json", result)
    print({"analysis": str(root / "ood_analysis.json"), "assets": len(samples),
           "categories": result["category_count"], "stages": report["evaluated_stages"]})


if __name__ == "__main__":
    main()
