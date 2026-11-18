"""Paired camera-ablation analysis, including identical GT visible subsets."""
import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from evaluation.baseline import shape_metrics
from evaluation.geometry import transform_points
from evaluation.visibility import INVALID, REGIONS
from examples.review_ood_protocol import l0_review
from examples.summarize_baseline_v2 import distribution, measurements, numeric
from wt.experiment import atomic_json, digest, file_digest, read_json


def common_visible_metrics(prediction, reference, first_labels, second_labels):
    first_labels, second_labels = np.asarray(first_labels), np.asarray(second_labels)
    if len(first_labels) != len(reference) or len(second_labels) != len(reference):
        raise ValueError("Visibility labels differ from the frozen GT point grid")
    if np.any(first_labels == INVALID) or np.any(second_labels == INVALID):
        return {"status": "invalid_visibility", "metrics": {}}
    visible = (first_labels == REGIONS["visible"]) & (second_labels == REGIONS["visible"])
    inherited = visible[cKDTree(reference).query(prediction, workers=1)[1]]
    predicted, target = prediction[inherited], reference[visible]
    row = {"prediction_points": len(predicted), "gt_points": len(target),
           "common_fraction_of_first_visible": float(visible.sum() / max(1, (first_labels == REGIONS["visible"]).sum())),
           "common_fraction_of_second_visible": float(visible.sum() / max(1, (second_labels == REGIONS["visible"]).sum()))}
    if not len(target) or not len(predicted):
        metrics = {"cd_euclidean_mean": None, "cd_squared_mean": None,
                   "pred_to_gt_mean": None, "gt_to_pred_mean": None}
        for threshold in (.01, .05):
            metrics[f"precision@{threshold:.2f}"] = None
            metrics[f"recall@{threshold:.2f}"] = 0. if len(target) else None
            metrics[f"f@{threshold:.2f}"] = 0. if len(target) else None
        row.update(status="empty_prediction" if len(target) else "not_applicable", metrics=metrics)
    else:
        row.update(status="complete", metrics=shape_metrics(predicted, target))
    return row


def load_verified_npz(path, checksum):
    if file_digest(path) != checksum:
        raise ValueError(f"Array checksum differs: {path}")
    with np.load(path, allow_pickle=False) as saved:
        return {name: saved[name] for name in saved.files}


def load_results(evaluation):
    index_path = evaluation / "index.json"
    index = read_json(index_path)
    rows = {}
    for entry in index["results"]:
        if entry["seed"] != 42:
            raise ValueError("Mixed seeds")
        path = Path(entry["result_path"])
        if file_digest(path) != entry["result_sha256"]:
            raise ValueError("Evaluation result differs")
        record = read_json(path)
        key = tuple(record[name] for name in ("sample_id", "method", "config_id", "stage"))
        if key in rows:
            raise ValueError("Duplicate method/configuration candidate")
        rows[key] = record
    return rows, {"evaluation": str(evaluation), "index_sha256": file_digest(index_path),
                  "revision": index["revision"], "total": len(rows),
                  "complete": sum(row["status"] == "complete" for row in rows.values())}


def extra_metrics(record):
    values = measurements(record)
    if record["method"] != "wt" or record["status"] != "complete":
        return values
    fit = l0_review(record)["l0_ssi"]
    if fit["status"] == "complete":
        values.update({"wt_l0_ssi." + name: fit[name] for name in
                       ("mae", "rmse", "absrel", "delta1", "delta2", "scale", "shift") if name in fit})
    projections = record.get("camera_diagnostics", {}).get("projections", {})
    gt, fitted = projections.get("gt", {}), projections.get("fitted", {})
    if gt.get("status") == fitted.get("status") == "complete":
        truth, predicted = np.array(gt["K"]), np.array(fitted["K"])
        for i, axis in enumerate(("x", "y")):
            ratio = float(predicted[i, i] / truth[i, i])
            values["camera.f" + axis + "_ratio"] = ratio
            values["camera.f" + axis + "_absolute_relative_error"] = abs(ratio - 1)
            values["camera.c" + axis + "_absolute_error_pixels"] = float(abs(predicted[i, 2] - truth[i, 2]))
        values["camera.gt_reprojection_p95"] = gt["p95_pixels"]
    return values


def cluster_interval(values, categories):
    labels = sorted(set(categories))
    totals = np.array([sum(value for value, category in zip(values, categories) if category == label) for label in labels])
    sizes = np.array([categories.count(label) for label in labels])
    rng = np.random.default_rng(20261110)
    chosen = rng.integers(len(labels), size=(5000, len(labels)))
    bootstrap = totals[chosen].sum(axis=1) / sizes[chosen].sum(axis=1)
    return {"clusters": len(labels), "ci95": np.quantile(bootstrap, [.025, .975]).tolist(),
            "sampling": "resample categories, retain every asset within each sampled category"}


def paired_values(rows, dataset):
    names = sorted({name for row in rows for name in row["control"].keys() & row["matched"].keys()})
    output = {}
    for name in names:
        selected = [row for row in rows if name in row["control"] and name in row["matched"]]
        a = [row["control"][name] for row in selected]
        b = [row["matched"][name] for row in selected]
        delta = [right-left for left, right in zip(a, b)]
        item = {"control": distribution(a), "matched": distribution(b), "delta": distribution(delta),
                "matched_lower": sum(right < left for left, right in zip(a, b)),
                "matched_higher": sum(right > left for left, right in zip(a, b)),
                "ties": sum(right == left for left, right in zip(a, b)),
                "sample_ids": [row["sample_id"] for row in selected]}
        if dataset == "OOD":
            item["category_bootstrap"] = cluster_interval(delta, [row["category"] for row in selected])
        output[name] = item
    return output


def method_gap_pairs(rows):
    """Summarize (WT - TRELLIS.2) within each condition on identical assets."""
    indexed = {}
    for row in rows:
        key = tuple(row[name] for name in ("dataset", "group", "sample_id", "method", "config_id", "stage"))
        if key in indexed:
            raise ValueError("Duplicate camera pair in method-gap analysis")
        indexed[key] = row
    buckets = defaultdict(list)
    for key, wt in indexed.items():
        dataset, group, sample_id, method, config_id, stage = key
        if (method, config_id, stage) != ("wt", "defaults-v1", "points"):
            continue
        for mesh_stage in ("decoded", "glb"):
            other = indexed.get((dataset, group, sample_id, "trellis2", "defaults-v1", mesh_stage))
            if other is None:
                continue
            if (wt["control_condition"], wt["matched_condition"], wt["category"]) != (
                    other["control_condition"], other["matched_condition"], other["category"]):
                raise ValueError("Method contrast conditions or category differ")
            names = set.intersection(*(set(row[condition]) for row in (wt, other)
                                       for condition in ("control", "matched")))
            names = {name for name in names
                     if name.startswith(("shape.", "regions.", "common_visible.", "surfel."))}
            item = dict(sample_id=sample_id, category=wt["category"])
            for condition in ("control", "matched"):
                item[condition] = {
                    name: wt[condition][name] - other[condition][name] for name in names
                    if all(numeric(row[side][name]) for row in (wt, other)
                           for side in ("control", "matched"))}
            buckets[(dataset, group, mesh_stage, wt["control_condition"], wt["matched_condition"])].append(item)
    return [
        dict(dataset=dataset, group=group, stage=stage, control=control, matched=matched,
             first="wt/defaults-v1/points", second=f"trellis2/defaults-v1/{stage}",
             condition_difference="WT-minus-TRELLIS.2",
             delta_difference="(WT_matched-TRELLIS.2_matched)-(WT_control-TRELLIS.2_control)",
             metrics=paired_values(selected, dataset))
        for (dataset, group, stage, control, matched), selected in sorted(buckets.items())
    ]


def analyze(state, output, *, include_runtime_control=False):
    output.mkdir(parents=True, exist_ok=True)
    planned_assets = int(state.get("planned_assets_per_dataset", 100))
    if planned_assets <= 0:
        raise ValueError("planned_assets_per_dataset must be positive")
    aliases = state.get("condition_aliases", {})
    records, sources = {}, {}
    for label, entry in state["experiments"].items():
        records[label], sources[label] = load_results(Path(entry["evaluation"]))
    pairs, rows = [], []
    references = {}
    metrics_cache = {}
    comparisons = [("A", "A0", "A1"), ("B", "B0", "B1")]
    if aliases.get("B0") != "A0":
        comparisons.append(("implementation_control", "A0", "B0"))
    if include_runtime_control:
        comparisons.append(("A_same_runtime", "B0", "A1"))
    for dataset in ("GSO", "OOD"):
        for group, first, second in comparisons:
            names = (dataset + "/" + first, dataset + "/" + second)
            if any(name not in records for name in names):
                continue
            first_rows, second_rows = (records[name] for name in names)
            buckets = defaultdict(list)
            for key in sorted(first_rows.keys() & second_rows.keys()):
                a, b = first_rows[key], second_rows[key]
                if a["status"] != "complete" or b["status"] != "complete":
                    continue
                for record in (a, b):
                    ref_path = Path(record["reference"])
                    if str(ref_path) not in references:
                        ref = read_json(ref_path)
                        labels = load_verified_npz(ref_path.parent / "visibility.npz", ref["files"]["visibility.npz"])["labels"]
                        sample = read_json(Path(record["source_directory"]).parents[2] / "input.json")
                        target = Path(sample["evaluation_dir"]) / "gt_points.npz"
                        points = load_verified_npz(target, sample["artifact_sha256"]["gt_points.npz"])["evaluation"]
                        references[str(ref_path)] = (ref, labels, sample, points)
                ra, la, sa, pa = references[a["reference"]]
                rb, lb, sb, pb = references[b["reference"]]
                np.testing.assert_array_equal(pa, pb)
                if ra["cameras"][1:] != rb["cameras"][1:]:
                    raise ValueError("Multiview cameras changed across intervention")
                if sa["artifact_sha256"]["gt_world.ply"] != sb["artifact_sha256"]["gt_world.ply"]:
                    raise ValueError("World geometry changed")
                row = dict(sample_id=key[0], method=key[1], config_id=key[2], stage=key[3],
                           dataset=dataset, group=group, category=sa.get("category"),
                           control_condition=first, matched_condition=second)
                for label, record in (("control", a), ("matched", b)):
                    result_path = Path(record["result_path"])
                    checksum = file_digest(result_path)
                    if checksum not in metrics_cache:
                        metrics_cache[checksum] = extra_metrics(record)
                    values = dict(metrics_cache[checksum])
                    sampled = load_verified_npz(result_path.parent / "sampled_points.npz",
                                                record["files"]["sampled_points.npz"])["evaluation"]
                    aligned = transform_points(sampled, np.asarray(record["registration"]["matrix"]))
                    common = common_visible_metrics(aligned, pa, la, lb)
                    values.update({"common_visible." + name: value for name, value in common["metrics"].items() if numeric(value)})
                    row[label] = values
                    row[label + "_common_visible"] = {k: v for k, v in common.items() if k != "metrics"}
                    row[label + "_result"] = {"path": str(result_path), "sha256": checksum}
                buckets[key[1:]].append(row)
                rows.append(row)
                print("PAIRED", dataset, group, key, flush=True)
            for (method, configuration, stage), selected in sorted(buckets.items()):
                pairs.append(dict(dataset=dataset, group=group, control=first, matched=second,
                                  method=method, config_id=configuration, stage=stage,
                                  paired_assets=len(selected), planned_assets=planned_assets,
                                  metrics=paired_values(selected, dataset)))
    report = {"status": "complete" if state["phase"] == "evaluation_complete_analysis_pending" else "partial",
              "seed": 42, "difference": "matched-minus-control", "planned_assets_per_dataset": planned_assets, "condition_aliases": aliases,
              "include_runtime_control": include_runtime_control,
              "sources": sources, "analysis_source_sha256": file_digest(Path(__file__)),
              "source_revision": state["source_revision"], "pairs": pairs,
              "method_gap_pairs": method_gap_pairs(rows), "records": rows}
    report["revision"] = digest({k: v for k, v in report.items() if k != "records"})[:20]
    atomic_json(output / "camera_analysis.json", report)
    (output / "camera_analysis.md").write_text(markdown(report))
    return report


def markdown(report):
    lines = ["## 相机消融配对结果", "",
             "固定 seed 42；差值为匹配条件减控制条件。区间为资产 bootstrap 5,000 次，"
             "统计 seed 20261110。OOD 类别重抽样区间及全部指标保存在 JSON。", ""]
    if report["status"] != "complete":
        lines.extend([f"当前仅为已完成资产的中间结果，不能代表完整 {report.get('planned_assets_per_dataset', 100)} 资产。", ""])
    for dataset in ("GSO", "OOD"):
        for group in ("A", "B", "implementation_control", "A_same_runtime"):
            selected = [row for row in report["pairs"] if row["dataset"] == dataset and row["group"] == group]
            if not selected:
                continue
            lines.extend([f"### {dataset} · {group}", "",
                          "| 方法 / 配置 / 阶段 | n 完整/共同可见 | 完整 CD 控制→匹配 | Δ完整 CD [95% CI] | 共同可见 CD 控制→匹配 | Δ共同可见 CD [95% CI] |",
                          "| --- | ---: | --- | --- | --- | --- |"])
            for row in selected:
                cells = []
                for name in ("shape.cd_euclidean_mean", "common_visible.cd_euclidean_mean"):
                    values = row["metrics"].get(name)
                    if not values:
                        cells.extend(["N/A", "N/A"])
                    else:
                        a, b, d = (values[k] for k in ("control", "matched", "delta"))
                        cells.extend([f"{a['mean']:.6f}→{b['mean']:.6f}",
                                      f"{d['mean']:+.6f} [{d['ci95'][0]:+.6f}, {d['ci95'][1]:+.6f}]"])
                counts = [row["metrics"].get(name, {}).get("delta", {}).get("n", 0)
                          for name in ("shape.cd_euclidean_mean", "common_visible.cd_euclidean_mean")]
                lines.append(f"| {row['method']} / {row['config_id']} / {row['stage']} | {counts[0]}/{counts[1]} | " + " | ".join(cells) + " |")
            lines.append("")
    lines.extend(["A 组同时改变距离与构图；B 组固定外参和裁剪并改变内参。"
                  "共同可见几何使用两条件同一批 GT 点，并复用各条件完整几何 Sim(3)。"
                  "输入深度按各条件对应相机计算，跨条件差值仍包含可见范围变化。", "",
                  "各指标有效 n 分别统计；表中列出完整与共同可见 CD 的实际配对分母，其他指标见 JSON 的 delta.n。",
                  ("失败和未完成项保留在原始预算。B0 直接引用 A0 的同一结果，不构成独立重跑控制。"
                   if report.get("condition_aliases", {}).get("B0") == "A0" else
                   "失败和未完成项保留在原始预算。实施控制 B0−A0 用于识别重跑和预处理适配带来的变化。"), ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-runtime-control", action="store_true")
    args = parser.parse_args()
    report = analyze(read_json(args.state), args.output, include_runtime_control=args.include_runtime_control)
    print({"status": report["status"], "revision": report["revision"], "pairs": len(report["pairs"])})


if __name__ == "__main__":
    main()
