"""Export a verified review packet from the frozen 100-asset OOD evaluation."""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from wt.artifacts import atomic_artifact

STAGES = (("wt", "points", "WT"), ("trellis2", "decoded", "TRELLIS.2 decoded"),
          ("trellis2", "glb", "TRELLIS.2 GLB"))
PRIMARY = (("shape.cd_euclidean_mean", "完整 CD-L1 ↓"),
           ("regions.visible.cd_euclidean_mean", "可见 CD-L1 ↓"),
           ("surfel.input.depth_mae", "输入深度 MAE ↓"))


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--local-root", required=True)
    args = parser.parse_args()
    pointer = read(args.experiment / "baseline_evaluation.json")
    evaluation = Path(pointer["directory"])
    report, audit, analysis, l0, index = [read(evaluation / f) for f in
        ("summary.json", "audit.json", "ood_analysis.json", "visible_depth_l0_review.json", "index.json")]
    complete = read(args.experiment / "ood_pipeline_complete.json")
    dataset = Path(complete["dataset"])
    selection, sampling = read(dataset / "selection.json"), read(dataset / "sampling_audit.json")
    assert complete["status"] == "complete" and report["mode"] == "formal"
    assert report["evaluated_stages"] == 300 and report["pending_stages"] == 0
    assert report["status_counts"] == {"complete": 300, "failed": 0}
    index_sha = sha(evaluation / "index.json")
    assert index_sha == pointer["index_sha256"] == report["index_sha256"] == audit["index_sha256"]
    assert audit["status"] == "passed" and sha(dataset / "selection.json") == complete["selection_sha256"]
    assert analysis["ood_summary_sha256"] == sha(evaluation / "summary.json")
    samples = {p.parent.name: read(p) for p in args.experiment.glob("samples/*/input.json")}
    ids = sorted(samples)
    assert len(ids) == 100 and len({s["category"] for s in samples.values()}) == 99
    assert set(ids) == set(read(dataset / "split.json")["splits"]["eval100"])
    records = {}
    for row in index["results"]:
        assert row["seed"] == 42 and row["status"] == "complete"
        assert sha(row["result_path"]) == row["result_sha256"]
        key = (row["sample_id"], row["method"], row["stage"])
        assert key not in records
        records[key] = read(row["result_path"])
    assert set(records) == {(sid, method, stage) for sid in ids for method, stage, _ in STAGES}
    values = {(r["sample_id"], r["method"], r["stage"]): r["values"]["single_seed"] for r in report["assets"]}
    groups = {(g["method"], g["stage"]): g["metrics"] for g in report["groups"] if g["mode"] == "single_seed"}
    for method, stage, _ in STAGES:
        for metric, stats in groups[method, stage].items():
            raw = [values[sid, method, stage][metric] for sid in ids if metric in values[sid, method, stage]]
            assert len(raw) == stats["n"]
            np.testing.assert_allclose(np.mean(raw), stats["mean"], rtol=1e-12, atol=1e-12)
    for metric, _ in PRIMARY:
        diff = np.array([values[sid, "wt", "points"][metric] - values[sid, "trellis2", "decoded"][metric] for sid in ids])
        pair = analysis["paired"]["decoded"][metric]
        np.testing.assert_allclose(diff.mean(), pair["asset_bootstrap"]["mean"], atol=1e-12)
        assert int((diff > 0).sum()) == pair["wt_higher"]
    args.out.mkdir(parents=True, exist_ok=False)
    linkroot = args.local_root.replace("\\", "/").rstrip("/")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    cell, row_height, top = 224, 270, 48

    def paste(sheet, path_or_image, column, y):
        if isinstance(path_or_image, Image.Image):
            img = path_or_image.convert("RGB")
        else:
            with Image.open(path_or_image) as source:
                img = source.convert("RGB")
        sheet.paste(img.resize((cell, cell), Image.Resampling.LANCZOS), (column * cell, y))

    def sheets(subset, prefix):
        normal = Image.new("RGB", (5 * cell, top + len(subset) * row_height), "#eeeeee")
        depth = Image.new("RGB", (6 * cell, top + len(subset) * row_height), "#eeeeee")
        nd, dd = ImageDraw.Draw(normal), ImageDraw.Draw(depth)
        for i, title in enumerate(("Input crop", "GT normal", "WT normal", "T2 decoded normal", "T2 GLB normal")):
            nd.text((i * cell + 6, 14), title, font=font, fill="black")
        for i, title in enumerate(("GT depth", "WT depth", "T2 decoded depth", "WT error", "T2 decoded error", "T2 GLB error")):
            dd.text((i * cell + 6, 14), title, font=font, fill="black")
        for n, sid in enumerate(subset):
            y = top + n * row_height
            sample = samples[sid]
            cy, cx, side = read(Path(sample["evaluation_dir"]) / "camera.json")["crop_y_x_side"]
            with Image.open(sample["image"]) as src:
                rgba = src.convert("RGBA").crop((cx, cy, cx + side, cy + side))
            rgb = Image.new("RGB", rgba.size, "#eeeeee")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
            paste(normal, rgb, 0, y)
            nd.text((6, y + cell + 5), sid.removeprefix("omni_"), font=small, fill="black")
            dd.text((6, y + cell + 5), sid.removeprefix("omni_"), font=small, fill="black")
            for col, (method, stage, _) in enumerate(STAGES, 2):
                rec = records[sid, method, stage]
                render = Path(rec["result_path"]).parent / "renders/surfel/input/000"
                paste(normal, render / "normal.png", col, y)
                mae = values[sid, method, stage]["surfel.input.depth_mae"]
                cd = values[sid, method, stage]["shape.cd_euclidean_mean"]
                nd.text((col * cell + 6, y + cell + 5), f"CD {cd:.4f}D", font=small, fill="black")
                dd.text(((col + 1) * cell + 6, y + cell + 5), f"MAE {mae:.4f}D", font=small, fill="black")
                paste(depth, render / "depth_error.png", col + 1, y)
                if stage == "points":
                    gt = Path(rec["reference"]).parent / "renders/native/input/000"
                    paste(normal, gt / "normal.png", 1, y)
                    paste(depth, gt / "depth.png", 0, y)
                    paste(depth, render / "depth.png", 1, y)
                elif stage == "decoded":
                    paste(depth, render / "depth.png", 2, y)
        normal.save(args.out / f"{prefix}_normal.png")
        depth.save(args.out / f"{prefix}_depth.png")

    page_for = {}
    for n in range(10):
        subset = ids[n * 10:(n + 1) * 10]
        sheets(subset, f"page_{n + 1:02d}")
        page_for.update({sid: n + 1 for sid in subset})
    depth_key = "surfel.input.depth_mae"
    diffs = {sid: values[sid, "wt", "points"][depth_key] - values[sid, "trellis2", "decoded"][depth_key] for sid in ids}
    ordered = sorted(ids, key=lambda sid: (diffs[sid], sid))
    reasons = {}
    def add(sid, reason):
        reasons.setdefault(sid, []).append(reason)
    for sid in ordered[:2]: add(sid, "WT 深度优势最大的两例之一")
    for sid in ordered[-2:]: add(sid, "TRELLIS.2 深度优势最大的两例之一")
    for method, stage, label in STAGES[:2]:
        add(max(ids, key=lambda sid: values[sid, method, stage][depth_key]), label + " 深度 MAE 最大")
    failures = [r for r in l0["records"] if r["l0_ssi"]["status"] != "complete"]
    for row in failures: add(row["sample_id"], "WT 原像素 L0＋SSI 正尺度拟合失败")
    chosen = sorted(reasons)
    sheets(chosen, "review_cases")
    for sid in chosen:
        folder = args.out / "details" / sid
        folder.mkdir(parents=True)
        for method, stage, _ in STAGES:
            src = Path(records[sid, method, stage]["result_path"]).parent / "renders/surfel/input/000/comparison.png"
            dst = folder / f"{method}_{stage}.png"
            shutil.copyfile(src, dst)
            assert sha(src) == sha(dst)
    def fmt(x): return "—" if x is None else f"{x:.6f}"
    def ci(xs): return f"[{xs[0]:+.6f}, {xs[1]:+.6f}]"
    lines = ["# OmniObject3D v2 正式 100 资产评测", "",
             "100 个资产、99 类、seed 42。WT 和 TRELLIS.2 各完成 100 次推理，300 个评估阶段全部成功。",
             "主结果支持 TRELLIS.2 在本次独立扫描样本上的优势。完整训练资产清单、转载与视觉骨干预训练的交集仍未查清，当前实验无法单独识别训练数据拟合的因果作用。", "",
             "## 主要结果", "",
             "所有主表指标均有 100 个有效资产。距离以 GT AABB 对角线 D 为单位，误差越小越好，F-score 与覆盖率越大越好。", ""]
    def table(title, columns):
        lines.extend([f"### {title}", "", "| 方法 | " + " | ".join(label for _, label in columns) + " |",
                      "| --- | " + " | ".join("---:" for _ in columns) + " |"])
        for method, stage, label in STAGES:
            lines.append("| " + label + " | " + " | ".join(fmt(groups[method, stage][key]["mean"]) for key, _ in columns) + " |")
        lines.append("")
    table("几何", [PRIMARY[0], PRIMARY[1], ("shape.f@0.01", "F@0.01 ↑"), ("shape.f@0.05", "F@0.05 ↑")])
    table("输入物理深度", [("surfel.input.depth_mae", "MAE ↓"), ("surfel.input.depth_rmse", "RMSE ↓"), ("surfel.input.depth_absrel", "AbsRel ↓"), ("surfel.input.depth_delta1", "δ1 ↑"), ("surfel.input.depth_delta2", "δ2 ↑"), ("surfel.input.depth_coverage", "覆盖率 ↑")])
    for scope, label in [("input", "输入视角"), ("multiview", "30 视角平均")]:
        table(label + "整图图像指标", [(f"surfel.{scope}.{key}", name) for key, name in
              [("depth_image_rmse", "深度 RMSE ↓"), ("depth_image_psnr", "深度 PSNR ↑"), ("depth_image_lpips", "深度 LPIPS ↓"),
               ("normal_rmse", "法线 RMSE ↓"), ("normal_psnr", "法线 PSNR ↑"), ("normal_lpips", "法线 LPIPS ↓")]])
    lines += ["深度图使用 GT 范围的灰度编码，法线图使用 normal RGB，整图均包含 0.5 背景。30 视角先在资产内平均，再对资产等权平均。主物理深度来自完整形状正 Sim(3) 对齐后的共同 surfel 渲染，在各方法与 GT 的有效像素交集计算，并单列覆盖率。", "",
              "## 配对差异", "", "下表差值为 WT − TRELLIS.2 decoded，正值表示 TRELLIS.2 误差更低。95% 区间为 5,000 次重抽样结果。", "",
              "| 指标 | 平均差值 | 资产 bootstrap 95% 区间 | 类别 cluster 95% 区间 | TRELLIS.2 更低 / 100 | 相对 WT 降幅 |", "| --- | ---: | --- | --- | ---: | ---: |"]
    for key, label in PRIMARY:
        pair = analysis["paired"]["decoded"][key]
        relative = 1 - pair["trellis2_mean"] / pair["wt_mean"]
        lines.append(f"| {label} | {pair['asset_bootstrap']['mean']:+.6f} | {ci(pair['asset_bootstrap']['ci95'])} | {ci(pair['category_cluster_bootstrap']['ci95'])} | {pair['wt_higher']} | {relative:.1%} |")
    lines += ["", "三项差值的两类区间均未跨零。GLB 阶段得到同向结论。区间描述本次冻结样本的不确定性，单次系统抽样的设计方差尚未估计，亦未进行多重比较校正。", "",
              "## WT 原像素 L0＋SSI 补充", "",
              f"有效 {l0['valid_assets']}/{l0['total_assets']}，MAE {l0['metrics']['mae']['mean']:.6f}D，RMSE {l0['metrics']['rmse']['mean']:.6f}D，AbsRel {l0['metrics']['absrel']['mean']:.6f}。该补充路径使用原像素 L0 与正 scale–shift 拟合，支持像素与主评测不同，不能用它直接替换主表中的 WT 行。", "",
              "| 无效样本 | 拟合尺度 | 原因 |", "| --- | ---: | --- |"]
    for row in failures:
        lines.append(f"| {row['sample_id']} | {row['l0_ssi']['scale']:.6f} | 正尺度约束不满足 |")
    lines += ["", "上述 3 个资产均保留在主评测 100 个资产中。历史重渲染 SSI 的有效数为 WT 48、decoded 58、GLB 62，各自有效集合不同。", "",
              "## 与 GSO R2 的历史参考", "", "仅列共同定义的 seed 42 指标。两组资产不配对，数据类别、扫描特征与难度也变化，以下变化不能归因于训练数据重叠。图像编码更新后的指标未与历史结果直接比较。", "",
              "| 方法 | GSO 完整 CD | OOD 完整 CD | GSO 可见 CD | OOD 可见 CD | GSO 输入深度 MAE | OOD 输入深度 MAE |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    gso_groups = {(g["method"], g["stage"]): g["metrics"] for g in analysis["domains"]["gso"]}
    for method, stage, label in STAGES:
        pairs = [fmt(v) for key, _ in PRIMARY for v in (gso_groups[method, stage][key]["mean"], groups[method, stage][key]["mean"])]
        lines.append(f"| {label} | " + " | ".join(pairs) + " |")
    lines += ["", "## 抽样范围与代表性", "",
              "冻结抽样框为 5,085 个资产、206 类，总体参考为 5,911 个资产、216 类。类别分块，类内按五项几何特征的秩做 Morton 排序，固定随机起点系统抽取 100 个资产，每资产纳入概率为 100/5085。模型结果未参与选择。",
              "本次覆盖 99 类，98 类各 1 个资产、doll 类 2 个。类别覆盖显著扩展，但每类样本不足以给出稳定的逐类别排名。",
              "9 个大包类别按冻结时的下载约束排除，package 获取失败，另排除 10 个校准资产和 1 个身份未明确的点云。该范围保留为本次实验定义。现行规则仅限制代理直接下载超过 5GB，后续扩展可重新核查镜像获取条件。",
              "材质与纹理总体分布尚未量化。五项几何特征对完整总体的最大 KS 差异为凸包填充率约 0.140，其下/上 10% 尾部入选 14/5 个，尚不能宣称覆盖整个数据集的全部特征分布。", "",
              "## 完整性与数值验收", "",
              f"- 200 次推理、300 个评价阶段，失败 0。数值 revision `{report['revision']}`。",
              f"- {audit['png_count']} 张 PNG 摘要与像素核验通过；几何、物理深度、mask、法线、覆盖率及像素数已复算。LPIPS 核验覆盖保存值及来源摘要。",
              "- GT mask 重渲染 100/100 一致，首交点异常射线 0。裁剪内参最大误差 5.68e-14，GT 深度重渲染 MAE 最大 8.73e-8D。",
              "- 本次导出再次核对全部 300 份结果摘要、冻结资产集合、所有 single-seed 组均值和主指标配对差值。", "",
              "## 异常与双向优势样本", "",
              "按输入深度差值两端各 2 例、每方法最大误差及 L0 拟合失败规则选择，下图用于定位异常。它们不代表总体频率，也未用于剔除样本。", "",
              "| 样本 | 选择原因 | 详细对照 |", "| --- | --- | --- |"]
    for sid in chosen:
        links = " · ".join(f"[{label}]({linkroot}/details/{sid}/{method}_{stage}.png)" for method, stage, label in STAGES)
        lines.append(f"| {sid} | {'；'.join(reasons[sid])} | {links} |")
    lines += ["", f"![审核样本法线对照]({linkroot}/review_cases_normal.png)", "", f"![审核样本深度对照]({linkroot}/review_cases_depth.png)", "",
              "深度预览为伪彩色可视化，同一资产的 GT 与预测共用 GT 范围；误差色标为 0–0.05D，超出值饱和。它们用于检查，不作为灰度图像指标的输入。", "",
              "## 全部 100 个资产", "", "下表依次为 WT / TRELLIS.2 decoded，完整 GLB 数值及全部组指标见 report_data.json。", "",
              "| 资产 | 完整 CD | 可见 CD | 输入深度 MAE | 深度覆盖率 | 总览 |", "| --- | --- | --- | --- | --- | --- |"]
    for sid in ids:
        pairs = [" / ".join(fmt(values[sid, method, stage][key]) for method, stage in [("wt", "points"), ("trellis2", "decoded")]) for key, _ in PRIMARY]
        cov = " / ".join(f"{values[sid, method, stage]['surfel.input.depth_coverage']:.2%}" for method, stage in [("wt", "points"), ("trellis2", "decoded")])
        page = page_for[sid]
        lines.append(f"| {sid} | " + " | ".join(pairs) + f" | {cov} | [法线]({linkroot}/page_{page:02d}_normal.png) · [深度]({linkroot}/page_{page:02d}_depth.png) |")
    lines += ["", "## 追溯", "", f"远程数值目录 `{evaluation}`。冻结选择 SHA-256 `{complete['selection_sha256']}`。",
              f"权威结果索引 SHA-256 `{index_sha}`。完整文件摘要见 packet_manifest.json。", ""]
    (args.out / "review.md").write_text("\n".join(lines), encoding="utf-8")
    save_json(args.out / "report_data.json", {"groups": [g for g in report["groups"] if g["mode"] == "single_seed"],
        "assets": [{"sample_id": sid, "category": samples[sid]["category"], "method": method, "stage": stage,
                    "metrics": values[sid, method, stage]} for sid in ids for method, stage, _ in STAGES],
        "paired": analysis["paired"], "review_cases": reasons, "l0": {k:v for k,v in l0.items() if k != "records"},
        "l0_failures": failures, "historical_domains": analysis["domains"], "config": report["config"]})
    for name in ["selection.json", "sampling_audit.json", "sampling_report.md"]:
        shutil.copyfile(dataset / name, args.out / name)
    sources = [evaluation / name for name in ["summary.json", "audit.json", "ood_analysis.json", "visible_depth_l0_review.json", "index.json"]]
    sources += [args.experiment / "ood_pipeline_complete.json", dataset / "selection.json", Path(__file__)]
    metadata = {"created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "experiment": str(args.experiment),
        "evaluation": str(evaluation), "revision": report["revision"], "status": "verified", "assets": 100, "categories": 99,
        "inference_runs": 200, "evaluation_stages": 300, "failed_stages": 0, "png_audit_count": audit["png_count"],
        "local_root": linkroot, "source_sha256": {str(p): sha(p) for p in sources},
        "file_sha256": {str(p.relative_to(args.out)): sha(p) for p in sorted(args.out.rglob("*")) if p.is_file()}}
    save_json(args.out / "packet_manifest.json", metadata)
    archive_path = args.out.with_name(args.out.name + "-verified.zip")
    assert not archive_path.exists()
    with atomic_artifact(archive_path) as staged:
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as archive:
            for p in sorted(args.out.rglob("*")):
                if p.is_file(): archive.write(p, str(p.relative_to(args.out)))
    print(json.dumps({"review": str(args.out / "review.md"), "archive": str(archive_path), "bytes": archive_path.stat().st_size,
                      "sha256": sha(archive_path), "review_cases": chosen}, ensure_ascii=False))


if __name__ == "__main__":
    main()
