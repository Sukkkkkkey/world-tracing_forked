"""Summarize one frozen baseline-v2 evaluation with asset-level uncertainty."""
import argparse
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

from evaluation.baseline import select_best
from wt.experiment import atomic_json, file_digest, read_json


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(value)


def measurements(record):
    if record.get("status") != "complete":
        return {}
    values = {f"shape.{key}": value for key, value in record["shape"].items() if numeric(value)}
    for key, value in record.get("geometry", {}).items():
        if numeric(value):
            values[f"geometry.{key}"] = value
    for region, row in record.get("regions", {}).items():
        for name, value in row["metrics"].items():
            if numeric(value):
                values[f"regions.{region}.{name}"] = value
        for name in ("prediction_points", "gt_points"):
            values[f"regions.{region}.{name}"] = row[name]
    pair = record.get("export_pair", {})
    if pair.get("status") == "complete":
        for category in ("shape", "geometry"):
            for name, value in pair["glb"][category].items():
                previous = pair["decoded"][category].get(name)
                if numeric(value) and numeric(previous):
                    values[f"export_pair.delta.{category}.{name}"] = value - previous
        for region, row in pair["glb"]["regions"].items():
            for name, value in row["metrics"].items():
                previous = pair["decoded"]["regions"][region]["metrics"].get(name)
                if numeric(value) and numeric(previous):
                    values[f"export_pair.delta.regions.{region}.{name}"] = value - previous
    matrix = np.asarray(record["registration"]["matrix"])
    values["registration.scale"] = float(np.cbrt(np.linalg.det(matrix[:3, :3])))
    for representation, comparison in record.get("comparisons", {}).items():
        for name, value in comparison["input"]["metrics"].items():
            if numeric(value):
                values[f"{representation}.input.{name}"] = value
        for name, value in comparison["input"]["pixels"].items():
            values[f"{representation}.input.pixels.{name}"] = value
        for row in comparison["multiview"]["metrics"]:
            values[f"{representation}.multiview.{row['metric']}.valid_views"] = row["valid_views"]
            if row["status"] == "complete" and numeric(row["value"]):
                values[f"{representation}.multiview.{row['metric']}"] = row["value"]
        ssi = comparison["input_ssi"]
        if ssi["status"] == "complete":
            for name in ("mae", "rmse", "absrel", "delta1", "delta2", "scale", "shift"):
                if numeric(ssi.get(name)):
                    values[f"{representation}.input_ssi.{name}"] = ssi[name]
    for name in ("psnr", "lpips"):
        value = record.get("input_rgb", {}).get(name)
        if numeric(value):
            values[f"input_rgb.{name}"] = value
    parent = record.get("wt_parent")
    if parent:
        for name, value in parent["shape"].items():
            if numeric(value):
                values[f"wt_parent.shape.{name}"] = value
        values["hybrid_minus_parent.cd"] = (
            record["shape"]["cd_euclidean_mean"] - parent["shape"]["cd_euclidean_mean"])
    diagnostics = record.get("camera_diagnostics", {})
    for name in ("scale_about_camera_origin", "scale_with_translation", "l0_xyz_rmse",
                 "l0_scale_rmse", "l0_scale_translation_rmse"):
        if numeric(diagnostics.get(name)):
            values[f"camera.{name}"] = diagnostics[name]
    for kind in ("native_shape", "scale_only_shape"):
        if numeric(diagnostics.get(kind, {}).get("cd_euclidean_mean")):
            values[f"camera.{kind}.cd"] = diagnostics[kind]["cd_euclidean_mean"]
    for kind, projection in diagnostics.get("projections", {}).items():
        if numeric(projection.get("mean_pixels")):
            values[f"camera.projection.{kind}.mean_pixels"] = projection["mean_pixels"]
    return values


def distribution(values):
    data = np.asarray(values, dtype=float)
    if not len(data):
        return {"n": 0, "mean": None, "ci95": None}
    rng = np.random.default_rng(20261110)
    bootstrap = data[rng.integers(len(data), size=(5000, len(data)))].mean(axis=1)
    return {"n": len(data), "mean": float(data.mean()), "median": float(np.median(data)),
            "std": float(data.std(ddof=1)) if len(data) > 1 else 0.,
            "ci95": np.quantile(bootstrap, [.025, .975]).tolist()}


def asset_group(records, seeds, single_seed, *, calibration=False):
    by_seed = {record["seed"]: record for record in records}
    selected = ({"status": "not_applicable", "reason": "single_seed_calibration"}
                if calibration else select_best(records, seeds))
    selected_record = by_seed.get(selected.get("seed"))
    measured = {seed: measurements(record) for seed, record in by_seed.items()}
    output = {
        "candidates": len(records),
        "complete": sum(record["status"] == "complete" for record in records),
        "failed": sum(record["status"] == "failed" for record in records),
        "expected": len(seeds),
        "selection": selected,
        "values": {"single_seed": measured.get(single_seed, {}), "mean_of_8": {}, "best_of_8": {}},
        "within_asset": {},
    }
    if selected["status"] == "complete":
        output["values"]["best_of_8"] = measurements(selected_record)
    if not calibration and set(by_seed) == set(seeds) and selected["status"] != "pending":
        names = sorted({name for values in measured.values() for name in values})
        for name in names:
            values = [row[name] for row in measured.values() if name in row]
            output["values"]["mean_of_8"][name] = float(np.mean(values))
            output["within_asset"][name] = {
                "valid_seeds": len(values), "expected_seeds": len(seeds),
                "std": float(np.std(values, ddof=1)) if len(values) > 1 else None}
    if calibration:
        output["values"] = {"single_seed": output["values"]["single_seed"]}
    return output


def aggregate(assets):
    buckets = defaultdict(lambda: defaultdict(list))
    for (sample, method, stage), asset in assets.items():
        for mode, values in asset["values"].items():
            for metric, value in values.items():
                buckets[(method, stage, mode)][metric].append(value)
    return [{"method": method, "stage": stage, "mode": mode,
             "metrics": {name: distribution(values) for name, values in metrics.items()}}
            for (method, stage, mode), metrics in sorted(buckets.items())]


def coverage(assets):
    groups = defaultdict(list)
    for (sample, method, stage), asset in assets.items():
        groups[(method, stage)].append(asset)
    rows = []
    for (method, stage), group in sorted(groups.items()):
        expected = sum(asset["expected"] for asset in group)
        evaluated = sum(asset["candidates"] for asset in group)
        failed = sum(asset["failed"] for asset in group)
        pending = expected - evaluated
        rows.append({
            "method": method, "stage": stage, "assets": len(group),
            "expected_candidates": expected, "evaluated_candidates": evaluated,
            "complete_candidates": sum(asset["complete"] for asset in group),
            "failed_candidates": failed, "pending_candidates": pending,
            "failure_rate_among_evaluated": failed / evaluated if evaluated else None,
            "budget_failure_rate": failed / expected if pending == 0 else None,
            "best_of_8_complete_assets": sum(asset["selection"]["status"] == "complete" for asset in group),
            "all_candidates_failed_assets": sum(asset["failed"] == asset["expected"] for asset in group),
        })
    return rows


def paired_methods(assets, methods):
    output = []
    samples = sorted({key[0] for key in assets})
    for stage in ("decoded", "glb"):
        for first, second in combinations(methods, 2):
            for mode in ("single_seed", "mean_of_8", "best_of_8"):
                pairs = []
                for sample in samples:
                    left = assets.get((sample, first, "points" if first == "wt" else stage), {})
                    right = assets.get((sample, second, "points" if second == "wt" else stage), {})
                    a, b = left.get("values", {}).get(mode, {}), right.get("values", {}).get(mode, {})
                    if a and b:
                        pairs.append((sample, a, b))
                names = sorted({name for _, a, b in pairs for name in a.keys() & b.keys()
                                if name.startswith(("shape.", "regions.", "surfel."))})
                metrics = {}
                for name in names:
                    common = [(sample, a[name], b[name]) for sample, a, b in pairs if name in a and name in b]
                    differences = [a - b for _, a, b in common]
                    metrics[name] = {**distribution(differences),
                                     "first_lower": sum(a < b for _, a, b in common),
                                     "first_higher": sum(a > b for _, a, b in common),
                                     "sample_ids": [sample for sample, _, _ in common]}
                if metrics:
                    output.append({"stage": stage, "mode": mode, "first": first, "second": second,
                                   "difference": "first-minus-second", "metrics": metrics})
    return output


def stage_pairs(records, seeds):
    pairs = defaultdict(dict)
    for record in records:
        if record["method"] != "wt":
            pairs[(record["sample_id"], record["method"], record["seed"])][record["stage"]] = record
    assets = defaultdict(lambda: defaultdict(list))
    for (sample, method, seed), stages in pairs.items():
        a, b = measurements(stages.get("decoded", {})), measurements(stages.get("glb", {}))
        for metric in a.keys() & b.keys():
            assets[(sample, method)][metric].append(b[metric] - a[metric])
    method_values = defaultdict(lambda: defaultdict(list))
    counts = defaultdict(list)
    for (sample, method), metrics in assets.items():
        for name, values in metrics.items():
            method_values[method][name].append(float(np.mean(values)))
        counts[method].append({"sample_id": sample, "paired_cd_seeds": len(metrics.get("shape.cd_euclidean_mean", []))})
    return [{"method": method, "difference": "glb-minus-decoded-within-same-seed",
             "alignment": "independent-stage-sim3",
             "expected_seeds": len(seeds), "assets": counts[method],
             "metrics": {name: distribution(values) for name, values in metrics.items()}}
            for method, metrics in sorted(method_values.items())]


def summary(directory):
    plan = read_json(directory / "plan.json")
    config = plan["config"]
    index = read_json(directory / "index.json") if (directory / "index.json").exists() else {"results": []}
    planned = {(row["sample_id"], row["method"], row["seed"], row["stage"]): row for row in plan["candidates"]}
    records = []
    for row in index["results"]:
        key = (row["sample_id"], row["method"], row["seed"], row["stage"])
        if key not in planned:
            raise ValueError("Indexed result is outside the frozen candidate plan")
        path = Path(row["result_path"])
        if file_digest(path) != row["result_sha256"]:
            raise ValueError(f"Result changed after indexing: {path}")
        result = read_json(path)
        if result["revision"] != index["revision"]:
            raise ValueError("Mixed evaluation revisions")
        records.append(result)
    grouped = defaultdict(list)
    for row in plan["candidates"]:
        grouped[(row["sample_id"], row["method"], row["stage"])]
    for record in records:
        grouped[(record["sample_id"], record["method"], record["stage"])].append(record)
    calibration = plan.get("mode") == "calibration"
    seeds = plan["selected_seeds"] if calibration else config["seeds"]
    assets = {key: asset_group(rows, seeds, config["report_single_seed"], calibration=calibration)
              for key, rows in grouped.items()}
    by_candidate = {(r["sample_id"], r["method"], r["seed"], r["stage"]): r for r in records}
    for (sample, method, stage), asset in assets.items():
        if stage != "decoded" or asset["selection"]["status"] != "complete":
            continue
        chosen = asset["selection"]["seed"]
        glb = assets[(sample, method, "glb")]
        glb["decoded_selected_seed"] = chosen
        glb["values"]["decoded_selected_glb"] = measurements(
            by_candidate.get((sample, method, chosen, "glb"), {}))
    status_counts = {status: sum(record["status"] == status for record in records)
                     for status in ("complete", "failed")}
    return {
        "revision": index.get("revision"), "config": config, "mode": plan.get("mode", "formal"),
        "summary_source_sha256": file_digest(Path(__file__)),
        "index_sha256": file_digest(directory / "index.json") if (directory / "index.json").exists() else None,
        "planned_stages": len(plan["candidates"]), "evaluated_stages": len(records),
        "pending_stages": len(plan["candidates"]) - len(records), "status_counts": status_counts,
        "assets": [{"sample_id": sample, "method": method, "stage": stage, **asset}
                   for (sample, method, stage), asset in sorted(assets.items())],
        "groups": aggregate(assets), "coverage": coverage(assets),
        "paired_methods": paired_methods(assets, list(config["methods"])),
         "paired_stages": stage_pairs(records, seeds),
        "render_index": [{key: record.get(key) for key in
                          ("sample_id", "method", "stage", "seed", "status", "result_path",
                           "artifacts", "reference")} for record in records],
    }


def markdown(report):
    lines = ["# Baseline v0.5 评测汇总", "",
             f"完成 {report['status_counts']['complete']} 个阶段，"
             f"失败 {report['status_counts']['failed']} 个，待完成 {report['pending_stages']} 个。", ""]
    if report.get("mode") == "calibration":
        lines += ["P0 校准使用固定 seed 42。", ""]
        modes = {"single_seed": "固定 seed 42"}
    elif report.get("mode") == "fixed_seed":
        seed = report["config"]["report_single_seed"]
        lines += [f"本轮使用固定 seed {seed}。", ""]
        modes = {"single_seed": f"固定 seed {seed}"}
    else:
        lines += ["Best-of-8 按资产、方法和输出阶段的完整几何 CD-L1 选择，"
                  "该组全部指标使用同一 seed。八次均值先在资产内平均有效候选。", ""]
        modes = {"single_seed": "固定 seed 42", "mean_of_8": "八次候选均值",
                 "best_of_8": "CD-L1 best-of-8", "decoded_selected_glb": "Decoded winner 的 GLB"}
    def table(groups, columns):
        rows = ["| 方法 | 阶段 | " + " | ".join(label for label, _ in columns) + " |",
                "| --- | --- | " + " | ".join("---" for _ in columns) + " |"]
        for row in groups:
            values = []
            for _, name in columns:
                result = row["metrics"].get(name, {})
                values.append(f"{result['mean']:.6f} (n={result['n']})"
                              if result.get("mean") is not None else "N/A")
            rows.append(f"| {row['method']} | {row['stage']} | " + " | ".join(values) + " |")
        return rows + [""]
    for mode, title in modes.items():
        groups = [row for row in report["groups"] if row["mode"] == mode]
        if not groups:
            continue
        lines += [f"## {title}", ""]
        for title, prefix in (("完整几何", "shape"), ("输入可见几何", "regions.visible")):
            lines += [f"### {title}", ""]
            lines += table(groups, [(label, f"{prefix}.{metric}") for label, metric in
                                   (("CD-L1", "cd_euclidean_mean"), ("CD-L2", "cd_squared_mean"),
                                    ("F@0.01", "f@0.01"), ("F@0.05", "f@0.05"))])
        depth_columns = (
            ("MAE", "depth_mae"), ("RMSE", "depth_rmse"), ("AbsRel", "depth_absrel"),
            ("δ1", "depth_delta1"), ("δ2", "depth_delta2"),
        )
        lines += ["### Visible depth · 共同 surfel 表示", "",
                  "完整形状 Sim(3) 后，固定 GT 输入相机直接渲染并计算深度误差。", ""]
        lines += table(groups, [(label, f"surfel.input.{metric}")
                                for label, metric in depth_columns])
        image_columns = (
            ("深度图 RMSE", "depth_image_rmse"), ("深度图 PSNR", "depth_image_psnr"),
            ("深度图 LPIPS", "depth_image_lpips"), ("深度覆盖", "depth_coverage"),
        )
        lines += ["### 输入视角 · 深度图、轮廓与法线", ""]
        lines += table(groups, [(label, f"surfel.input.{metric}")
                                for label, metric in image_columns])
        lines += table(groups, [(label, f"surfel.input.{metric}") for label, metric in (
            ("Silhouette IoU", "silhouette_iou"), ("法线角误差", "normal_mean_angle"),
            ("法线图 RMSE", "normal_rmse"), ("法线 PSNR", "normal_psnr"),
            ("法线 LPIPS", "normal_lpips"), ("法线覆盖", "normal_coverage"),
        )])
        lines += ["### 输入视角 · GLB 外观", ""]
        lines += table([row for row in groups if row["stage"] == "glb"], [
            ("RGB PSNR", "input_rgb.psnr"), ("RGB LPIPS", "input_rgb.lpips"),
        ])
        lines += ["### 30 视角 · 共同 surfel 表示", ""]
        lines += table(groups, [(label, f"surfel.multiview.{metric}")
                                for label, metric in image_columns])
        lines += table(groups, [(label, f"surfel.multiview.{metric}") for label, metric in (
            ("Silhouette IoU", "silhouette_iou"), ("法线角误差", "normal_mean_angle"),
            ("法线图 RMSE", "normal_rmse"), ("法线 PSNR", "normal_psnr"),
            ("法线 LPIPS", "normal_lpips"), ("法线覆盖", "normal_coverage"),
        )])
        exported = [row for row in groups if row["stage"] == "glb"]
        if exported:
            lines += ["### 同 seed、同 decoded 变换的导出差值", "",
                      "表中差值为 GLB 减 decoded。", ""]
            lines += table(exported, [
                ("完整 CD-L1 Δ", "export_pair.delta.shape.cd_euclidean_mean"),
                ("可见 CD-L1 Δ", "export_pair.delta.regions.visible.cd_euclidean_mean"),
                ("面积/GT Δ", "export_pair.delta.geometry.area_gt_ratio")])
    historical = [row for row in report["groups"] if row["mode"] in modes
                  and any(name.startswith("surfel.input_ssi.") for name in row["metrics"])]
    if historical:
        lines += ["## 历史诊断 · Sim(3) 重渲染后 SSI", "",
                  "记录逐资产再次拟合深度尺度与偏移的历史结果。"
                  "覆盖率门槛为 95%，n 为通过覆盖率及拟合有效性检查的资产数。", ""]
        for mode, title in modes.items():
            groups = [row for row in historical if row["mode"] == mode]
            if groups:
                lines += [f"### {title}", ""]
                lines += table(groups, [(label, f"surfel.input_ssi.{metric}") for label, metric in
                                       (("MAE", "mae"), ("RMSE", "rmse"), ("AbsRel", "absrel"),
                                        ("δ1", "delta1"), ("δ2", "delta2"))])
    lines += ["## 产物与解释条件", "",
              "主指标使用完整几何正 Sim(3) 配准，输入相机沿用 GT 裁剪内外参。"
              "区域划分复用该变换，预测点按最近 GT 评价点继承标签。"
              "区域边界及 surfel 转换误差见校准报告。", "",
              "每项括号中的 n 为有效资产数。完整 multi-view 均值要求全部 30 个视角有效。"
              "Precision、Recall、双向距离、有效像素及视角数、原生三角面渲染、"
              "相机尺度、遮挡区域、RGB、Hybrid parent 和资产级配对区间保存在 summary.json。", "",
              "[查看渲染产物索引](render_index.md)", ""]
    return "\n".join(lines)


def write_render_index(directory, report):
    atomic_json(directory / "render_index.json", report["render_index"])
    lines = ["# 渲染产物索引", "",
             "| 资产 | 方法 | 阶段 | seed | 产物清单 |", "| --- | --- | --- | --- | --- |"]
    for row in report["render_index"]:
        artifact = row.get("artifacts")
        link = f"[manifest]({artifact['manifest']})" if artifact else row["status"]
        lines.append(f"| {row['sample_id']} | {row['method']} | {row['stage']} | {row['seed']} | {link} |")
    (directory / "render_index.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    args = parser.parse_args()
    report = summary(args.evaluation)
    atomic_json(args.evaluation / "summary.json", report)
    (args.evaluation / "summary.md").write_text(markdown(report))
    write_render_index(args.evaluation, report)
    print({key: report[key] for key in ("revision", "planned_stages", "evaluated_stages", "status_counts", "pending_stages")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
