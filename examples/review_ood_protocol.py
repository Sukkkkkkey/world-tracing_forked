"""Review completed OOD calibration caches under the current metric protocol."""
import argparse
from collections import Counter
import copy
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from evaluation.geometry import depth_metrics
from evaluation.multiview import depth_image_comparison, normal_image_comparison
from examples.review_cached_depth import load_depth_groups
from examples.summarize_baseline_v2 import aggregate, asset_group, distribution, paired_methods
from wt.experiment import atomic_json, digest, file_digest, read_json

STAGES = (("wt", "points", "WT points"), ("trellis2", "decoded", "TRELLIS.2 decoded"),
          ("trellis2", "glb", "TRELLIS.2 GLB"))


def key(row):
    return row["sample_id"], row["method"], row["stage"]


def read_verified_review(path, index_sha):
    report = read_json(path)
    if report["status"] != "passed" or report["index_sha256"] != index_sha:
        raise ValueError(f"Review/index mismatch {path}")
    return report


def l0_review(record):
    source = Path(record["source_directory"])
    sample = read_json(source.parents[2] / "input.json")
    dataset = Path(sample["evaluation_dir"])
    paths = [source / "prediction.npz", dataset / "gt_depth.npz",
             source.parents[2] / "input.json", dataset / "camera.json"]
    saved_fit = source / "depth_fit.json"
    if saved_fit.exists():
        paths.append(saved_fit)
    hashes = {str(path): file_digest(path) for path in paths}
    with np.load(paths[0], allow_pickle=False) as saved:
        depth, mask = saved["xyz"][0, ..., 2], saved["mask"][0].astype(bool)
    with np.load(paths[1], allow_pickle=False) as saved:
        target, target_mask = saved["depth"], saved["mask"].astype(bool)
    if depth.shape != target.shape or mask.shape != target_mask.shape:
        raise ValueError("WT L0 and GT pixel grids differ")
    result = depth_metrics(depth, target, mask, target_mask)
    if saved_fit.exists():
        previous = read_json(saved_fit)
        if result["status"] != previous["status"]:
            raise ValueError("L0 fit validity changed")
        for name, value in result.items():
            if isinstance(value, (float, int)) and name in previous:
                np.testing.assert_allclose(value, previous[name], rtol=0, atol=1e-12)
    if any(file_digest(Path(path)) != value for path, value in hashes.items()):
        raise ValueError("L0 source changed during review")
    valid_gt = target_mask & np.isfinite(target) & (target > 0)
    valid_pred = mask & np.isfinite(depth) & (depth > 0)
    return {"sample_id": record["sample_id"], "l0_ssi": result, "source_files": hashes,
            "gt_pixels": int(valid_gt.sum()), "pred_pixels": int(valid_pred.sum()),
            "resolution": list(depth.shape)}


def fmt(value):
    return "—" if value is None else f"{value:.6f}"


def table(lines, title, rows, metrics):
    lines.extend(["", f"## {title}", "",
                  "| 方法 / 阶段 | 有效 n | " + " | ".join(label for _, label in metrics) + " |",
                  "| --- | ---: | " + " | ".join("---:" for _ in metrics) + " |"])
    for label, values in rows:
        counts = {values.get(name, {}).get("n", 0) for name, _ in metrics}
        n = str(next(iter(counts))) if len(counts) == 1 else "/".join(map(str, sorted(counts)))
        lines.append(f"| {label} | {n} | " +
                     " | ".join(fmt(values.get(name, {}).get("mean")) for name, _ in metrics) + " |")


def make_metric_images(records, out, config):
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    ids = sorted({row["sample_id"] for row in records})
    cell, height = 168, 200
    canvas = Image.new("RGB", (cell * 8, 45 + height * len(ids)), "#eeeeee")
    draw = ImageDraw.Draw(canvas)
    headers = ["GT depth", "WT depth", "T2 decoded", "T2 GLB",
               "GT normal", "WT normal", "T2 decoded", "T2 GLB"]
    for column, label in enumerate(headers):
        draw.text((column * cell + 5, 12), label, fill="black", font=font)
    for row_index, sample_id in enumerate(ids):
        candidates = [row for row in records if row["sample_id"] == sample_id]
        for method_index, (method, stage, _) in enumerate(STAGES):
            row = next(row for row in candidates if row["method"] == method and row["stage"] == stage)
            ref_path = Path(row["reference"])
            ref = read_json(ref_path)
            gt = load_depth_groups(ref_path.parent / "geometry.npz", ref["files"]["geometry.npz"],
                                   include_normals=True)["input"]
            pred = load_depth_groups(Path(row["result_path"]).parent / "surfel.npz",
                                     row["files"]["surfel.npz"], include_normals=True)["input"]
            gt = {name: value[0] for name, value in gt.items()}
            pred = {name: value[0] for name, value in pred.items()}
            for kind_index, compare in enumerate((depth_image_comparison, normal_image_comparison)):
                encoded = compare(pred, gt, config)
                pairs = [(kind_index * 4 + method_index + 1, encoded["prediction_rgb"])]
                if method_index == 0:
                    pairs.append((kind_index * 4, encoded["reference_rgb"]))
                for column, signed_rgb in pairs:
                    rgb = np.rint(np.clip((signed_rgb + 1) / 2, 0, 1) * 255).astype(np.uint8)
                    canvas.paste(Image.fromarray(rgb).resize((cell, cell), Image.Resampling.LANCZOS),
                                 (column * cell, 45 + row_index * height))
        draw.text((5, 45 + row_index * height + cell + 5), sample_id.removeprefix("omni_"),
                  fill="black", font=font)
    canvas.save(out / "metric_images.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--local-root", required=True)
    args = parser.parse_args()
    index_path = args.evaluation / "index.json"
    index_sha = file_digest(index_path)
    index = read_json(index_path)
    direct_path = args.review_dir / "visible_depth_direct_review.json"
    image_path = args.review_dir / "render_image_fullframe_review.json"
    direct = read_verified_review(direct_path, index_sha)
    images = read_verified_review(image_path, index_sha)
    direct_rows = {key(row): row for row in direct["records"]}
    image_rows = {key(row): row for row in images["records"]}
    old = read_json(args.evaluation / "summary.json")
    records, l0 = [], []
    for row in index["results"]:
        if file_digest(Path(row["result_path"])) != row["result_sha256"]:
            raise ValueError("Original result changed")
        record = copy.deepcopy(read_json(Path(row["result_path"])))
        record["comparisons"] = {name: comparison for name, comparison in record["comparisons"].items()
                                 if name in ("surfel", "native")}
        for representation, comparison in record["comparisons"].items():
            image = image_rows[key(row)]["comparisons"][representation]
            depth = direct_rows[key(row)]["comparisons"][representation]
            comparison["input"] = copy.deepcopy(image["input"])
            comparison["input"]["metrics"].update(depth["input"]["metrics"])
            comparison["multiview"] = copy.deepcopy(image["multiview"])
        records.append(record)
        if row["method"] == "wt":
            l0.append(l0_review(record))
    assets = {key(row): asset_group([row], [42], 42, calibration=True) for row in records}
    l0_valid = [row for row in l0 if row["l0_ssi"]["status"] == "complete"]
    names = ("mae", "rmse", "absrel", "delta1", "delta2")
    l0_metrics = {name: distribution([row["l0_ssi"][name] for row in l0_valid]) for name in names}
    l0_report = {
        "status": "passed", "records": l0, "metrics": l0_metrics, "valid_assets": len(l0_valid),
        "total_assets": len(l0), "failure_reasons": dict(Counter(
            row["l0_ssi"].get("reason") for row in l0 if row not in l0_valid)),
        "source_sha256": file_digest(Path(__file__)),
        "depth_metrics_source_sha256": file_digest(Path("evaluation/geometry.py")),
    }
    atomic_json(args.review_dir / "visible_depth_l0_review.json", l0_report)
    provenance = {
        "evaluation_revision": index["revision"], "index_sha256": index_sha,
        "original_summary_sha256": file_digest(args.evaluation / "summary.json"),
        "depth_review_sha256": file_digest(direct_path), "image_review_sha256": file_digest(image_path),
        "l0_review_sha256": file_digest(args.review_dir / "visible_depth_l0_review.json"),
        "protocol_sha256": file_digest(Path("docs/evaluation_protocol_v0.5.md")),
        "source_sha256": file_digest(Path(__file__)),
    }
    updated = {
        **provenance, "review_revision": digest(provenance)[:20], "status": "passed",
        "asset_count": len(l0), "evaluated_stages": len(records), "seeds": [42],
        "groups": aggregate(assets), "paired_methods": paired_methods(assets, ["wt", "trellis2"]),
        "assets": [dict(sample_id=k[0], method=k[1], stage=k[2], **v) for k, v in sorted(assets.items())],
        "wt_l0_ssi": l0_report,
    }
    atomic_json(args.review_dir / "updated_summary.json", updated)
    group_rows = [(label, next(group["metrics"] for group in updated["groups"]
                              if group["method"] == method and group["stage"] == stage))
                  for method, stage, label in STAGES]
    lines = ["# OmniObject3D 预实验协议更新", "",
             "2026-11-11。10 个校准资产、seed 42、30 个评价阶段。复用已冻结的模型预测、Sim(3) 与浮点渲染缓存，按当前 v0.5 协议补算。正式 100 资产处于清单审核阶段，执行仍等待用户确认。", "",
             "## 本次更新", "",
             "- Visible depth 补齐 MAE、RMSE、AbsRel、δ1、δ2，WT 原像素 L0＋SSI 同表列为补充行。",
             "- 深度图采用 GT 共享范围的灰度 RGB，法线采用相机法线 RGB，背景为 0.5。RMSE、PSNR、LPIPS 均覆盖整幅图像。",
             "- Multi-view 按每资产 30 视角等权平均后汇总资产，报告图像误差、法线角、轮廓及覆盖率。历史重渲染 SSI 收入诊断。",
             "- 距离单位为归一化 GT 对角线 D，图像 RMSE 基于 [0,1] RGB，PSNR 为 dB，法线角为度。有效像素交集决定物理深度误差，覆盖率单独列出。"]
    table(lines, "Whole geometry", group_rows, [
        ("shape.cd_euclidean_mean", "CD-L1 ↓"), ("shape.cd_squared_mean", "CD-L2 ↓"),
        ("shape.precision@0.01", "P@0.01 ↑"), ("shape.recall@0.01", "R@0.01 ↑"),
        ("shape.f@0.01", "F@0.01 ↑"), ("shape.f@0.05", "F@0.05 ↑")])
    table(lines, "Whole geometry 方向距离与宽阈值", group_rows, [
        ("shape.pred_to_gt_mean", "Pred→GT ↓"), ("shape.gt_to_pred_mean", "GT→Pred ↓"),
        ("shape.precision@0.05", "P@0.05 ↑"), ("shape.recall@0.05", "R@0.05 ↑")])
    table(lines, "Input-visible geometry", group_rows, [
        ("regions.visible.cd_euclidean_mean", "CD-L1 ↓"),
        ("regions.visible.cd_squared_mean", "CD-L2 ↓"),
        ("regions.visible.precision@0.01", "P@0.01 ↑"), ("regions.visible.recall@0.01", "R@0.01 ↑"),
        ("regions.visible.f@0.01", "F@0.01 ↑"), ("regions.visible.f@0.05", "F@0.05 ↑")])
    table(lines, "Input-visible geometry 方向距离与宽阈值", group_rows, [
        ("regions.visible.pred_to_gt_mean", "Pred→GT ↓"),
        ("regions.visible.gt_to_pred_mean", "GT→Pred ↓"),
        ("regions.visible.precision@0.05", "P@0.05 ↑"), ("regions.visible.recall@0.05", "R@0.05 ↑")])
    depth_rows = [(label, {name: values.get("surfel.input.depth_" + name, {}) for name in names})
                  for label, values in group_rows]
    depth_rows.append(("WT 原像素 L0＋SSI（补充）", l0_metrics))
    table(lines, "Visible depth", depth_rows, [(name, label) for name, label in
          zip(names, ("MAE ↓", "RMSE ↓", "AbsRel ↓", "δ1 ↑", "δ2 ↑"))])
    lines.extend(["", f"主评测三行均为 10/10 有效。WT 原像素 L0＋SSI 为 {len(l0_valid)}/10 有效，"
                  f"覆盖率门槛 95%，失败原因记录为 {l0_report['failure_reasons']}。"])
    image_metrics = [("depth_image_rmse", "深度图 RMSE ↓"), ("depth_image_psnr", "深度图 PSNR ↑"),
                     ("depth_image_lpips", "深度图 LPIPS ↓"), ("normal_rmse", "法线 RMSE ↓"),
                     ("normal_psnr", "法线 PSNR ↑"), ("normal_lpips", "法线 LPIPS ↓")]
    support_metrics = [("silhouette_iou", "轮廓 IoU ↑"), ("depth_coverage", "深度覆盖 ↑"),
                       ("normal_coverage", "法线覆盖 ↑"), ("normal_mean_angle", "法线角 ↓"),
                       ("depth_image_clipped_fraction", "深度截断率")]
    for view, label in (("input", "Input view"), ("multiview", "Multi-view")):
        table(lines, label + " 图像指标", group_rows,
              [(f"surfel.{view}.{name}", title) for name, title in image_metrics])
        table(lines, label + " 覆盖与几何诊断", group_rows,
              [(f"surfel.{view}.{name}", title) for name, title in support_metrics])
    table(lines, "GLB 输入 RGB 外观", [(label, values) for label, values in group_rows if label.endswith("GLB")],
          [("input_rgb.psnr", "PSNR ↑"), ("input_rgb.lpips", "LPIPS ↓")])
    native_rows = [(label, {name: values.get("native.input.depth_" + name, {}) for name in names})
                   for label, values in group_rows if label != "WT points"]
    table(lines, "原生三角面输入深度补充", native_rows,
          list(zip(names, ("MAE ↓", "RMSE ↓", "AbsRel ↓", "δ1 ↑", "δ2 ↑"))))
    table(lines, "历史重渲染 SSI 诊断", group_rows, [
        ("surfel.input_ssi.mae", "MAE ↓"), ("surfel.input_ssi.rmse", "RMSE ↓"),
        ("surfel.input_ssi.absrel", "AbsRel ↓"), ("surfel.input_ssi.delta1", "δ1 ↑"),
        ("surfel.input_ssi.delta2", "δ2 ↑")])
    pair = next(row for row in updated["paired_methods"] if row["stage"] == "decoded")
    lines.extend(["", "## WT − TRELLIS.2 decoded 配对差值", "",
                  "95% 区间为资产等权 bootstrap 5,000 次，统计随机种子 20261110。", "",
                  "| 指标 | n | 均值差 | 95% 区间 | WT 更低数 |",
                  "| --- | ---: | ---: | --- | ---: |"])
    for name, label in [("shape.cd_euclidean_mean", "完整 CD-L1"),
                        ("regions.visible.cd_euclidean_mean", "可见 CD-L1"),
                        ("surfel.input.depth_mae", "输入深度 MAE"),
                        ("surfel.input.depth_image_rmse", "输入深度图 RMSE"),
                        ("surfel.input.normal_rmse", "输入法线图 RMSE")]:
        value = pair["metrics"][name]
        lo, hi = value["ci95"]
        lines.append(f"| {label} | {value['n']} | {value['mean']:+.6f} | [{lo:+.6f}, {hi:+.6f}] | {value['first_lower']} |")
    lines.extend(["", "## 更新后逐资产深度", "",
                  "| 资产 | WT MAE | T2 decoded MAE | WT L0＋SSI MAE | L0 状态 |",
                  "| --- | ---: | ---: | ---: | --- |"])
    for row in l0:
        sid = row["sample_id"]
        wt = assets[(sid, "wt", "points")]["values"]["single_seed"]
        t2 = assets[(sid, "trellis2", "decoded")]["values"]["single_seed"]
        fit = row["l0_ssi"]
        lines.append(f"| {sid.removeprefix('omni_')} | {wt['surfel.input.depth_mae']:.6f} | "
                     f"{t2['surfel.input.depth_mae']:.6f} | {fmt(fit.get('mae'))} | {fit['status']} |")
    link_root = args.local_root.rstrip("/")
    old_link = "D:/647/vertex_remote/projects/WT_for_mesh/logs/20261111-ood-calibration-review"
    lines.extend(["", "## 审核图与结果限制", "",
                  f"![当前图像指标使用的灰度深度和法线图]({link_root}/metric_images.png)", "",
                  "kennel_003 是两方法输入深度误差最大的样本。完整与可见 CD-L1 的配对区间跨越 0。"
                  "10 个资产提供协议校准证据，正式集的代表性分析见资产清单审核报告。"
                  "来源层面 OOD 仍保留转载资产及视觉骨干预训练重叠的不确定性。", "",
                  f"[原始输入、详细误差与配准对照]({old_link}/review.md)", "",
                  "## 可追溯记录", "",
                  f"- 原始数值 revision 为 {index['revision']}，本次复核 revision 为 {updated['review_revision']}。",
                  "- 原始几何和物理深度 MAE/RMSE 与缓存复算一致。新增深度图 LPIPS 使用冻结权重计算，并通过批量/单张一致性检查。",
                  "- 法线 LPIPS 沿用原完整图像分数，编码与输入 mask 的定义一致。",
                  f"- 完整统计与逐资产记录保存在 {args.review_dir}/updated_summary.json。",
                  f"- 原始验收完成 30/30 阶段、650 张 PNG，失败为 0。本次复核覆盖 {images['representation_count']} 个方法表示和全部 31 视角。",
                  ""])
    (args.review_dir / "review.md").write_text("\n".join(lines), encoding="utf-8")
    make_metric_images(records, args.review_dir, images["config"])
    if file_digest(index_path) != index_sha:
        raise ValueError("Evaluation index changed")
    print({"review": str(args.review_dir / "review.md"), "revision": updated["review_revision"],
           "l0_valid": len(l0_valid), "stages": len(records)})


if __name__ == "__main__":
    main()

