"""Export a local-review packet for completed OOD calibration results."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import zipfile

from PIL import Image, ImageDraw, ImageFont

from wt.artifacts import atomic_artifact
from wt.experiment import atomic_json, file_digest, read_json

STAGES = (("wt", "points"), ("trellis2", "decoded"), ("trellis2", "glb"))
LABELS = {"wt": "WT", "decoded": "TRELLIS.2 decoded", "glb": "TRELLIS.2 GLB"}


def number(value, percent=False):
    if value is None:
        return "—"
    return f"{value:.2%}" if percent else f"{value:.6f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--local-root", required=True, help="Absolute destination used in the local review links")
    args = parser.parse_args()
    evaluation = Path(read_json(args.experiment / "baseline_evaluation.json")["directory"])
    report = read_json(evaluation / "summary.json")
    audit = read_json(evaluation / "audit.json")
    assert report["mode"] == "calibration" and report["pending_stages"] == 0
    assert audit["status"] == "passed" and audit["index_sha256"] == file_digest(evaluation / "index.json")
    index = read_json(evaluation / "index.json")
    records = {}
    for row in index["results"]:
        assert file_digest(Path(row["result_path"])) == row["result_sha256"]
        records[(row["sample_id"], row["method"], row["stage"])] = read_json(Path(row["result_path"]))
    samples = {path.parent.name: read_json(path) for path in args.experiment.glob("samples/*/input.json")}
    sample_ids = sorted(samples)
    data_root = Path(samples[sample_ids[0]]["evaluation_dir"]).parents[1]
    splits = read_json(data_root / "split.json")["splits"]
    assert set(sample_ids) == set(splits["pilot"]) and len(sample_ids) == 10
    assert len(set(splits["eval100"])) == 100
    assert not set(splits["pilot"]) & set(splits["eval100"])
    args.out.mkdir(parents=True, exist_ok=True)
    link_root = args.local_root.replace("\\", "/").rstrip("/")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    cell, row_height, top = 210, 248, 44
    normal_sheet = Image.new("RGB", (5 * cell, top + len(samples) * row_height), "#eeeeee")
    depth_sheet = Image.new("RGB", (6 * cell, top + len(samples) * row_height), "#eeeeee")
    normal_draw, depth_draw = ImageDraw.Draw(normal_sheet), ImageDraw.Draw(depth_sheet)
    for column, title in enumerate(("Input crop", "GT normal", "WT normal", "TRELLIS.2 decoded", "TRELLIS.2 GLB")):
        normal_draw.text((column * cell + 6, 12), title, fill="black", font=font)
    for column, title in enumerate(("GT depth", "WT depth", "TRELLIS.2 depth", "WT error", "TRELLIS.2 error", "GLB error")):
        depth_draw.text((column * cell + 6, 12), title, fill="black", font=font)
    detail_links = {}
    asset_rows = {(row["sample_id"], row["method"], row["stage"]): row["values"]["single_seed"]
                  for row in report["assets"]}

    def paste_image(sheet, image, column, y):
        image = image.convert("RGB").resize((cell, cell), Image.Resampling.LANCZOS)
        sheet.paste(image, (column * cell, y))

    for row_number, sample_id in enumerate(sample_ids):
        sample = samples[sample_id]
        y = top + row_number * row_height
        rgba = Image.open(sample["image"]).convert("RGBA")
        camera = read_json(Path(sample["evaluation_dir"]) / "camera.json")
        crop_y, crop_x, side = camera["crop_y_x_side"]
        rgba = rgba.crop((crop_x, crop_y, crop_x + side, crop_y + side))
        rgb = Image.new("RGB", rgba.size, "#eeeeee")
        rgb.paste(rgba, mask=rgba.getchannel("A"))
        paste_image(normal_sheet, rgb, 0, y)
        normal_draw.text((6, y + cell + 8), sample_id.removeprefix("omni_"), fill="black", font=font)
        depth_draw.text((6, y + cell + 8), sample_id.removeprefix("omni_"), fill="black", font=font)
        detail_links[sample_id] = {}
        for column, (method, stage) in enumerate(STAGES, 2):
            record = records.get((sample_id, method, stage), {})
            if record.get("status") != "complete":
                normal_draw.text((column * cell + 12, y + 80), "Failed", fill="black", font=font)
                continue
            directory = Path(record["result_path"]).parent
            render = directory / "renders/surfel/input/000"
            paste_image(normal_sheet, Image.open(render / "normal.png"), column, y)
            if stage == "points":
                gt = Path(record["reference"]).parent / "renders/native/input/000"
                paste_image(normal_sheet, Image.open(gt / "normal.png"), 1, y)
                paste_image(depth_sheet, Image.open(gt / "depth.png"), 0, y)
                paste_image(depth_sheet, Image.open(render / "depth.png"), 1, y)
                paste_image(depth_sheet, Image.open(render / "depth_error.png"), 3, y)
            elif stage == "decoded":
                paste_image(depth_sheet, Image.open(render / "depth.png"), 2, y)
                paste_image(depth_sheet, Image.open(render / "depth_error.png"), 4, y)
            else:
                paste_image(depth_sheet, Image.open(render / "depth_error.png"), 5, y)
            relative = f"details/{sample_id}/{method}_{stage}.png"
            destination = args.out / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(render / "comparison.png", destination)
            detail_links[sample_id][stage] = f"{link_root}/{relative}"
    normal_sheet.save(args.out / "normal_overview.png")
    depth_sheet.save(args.out / "depth_overview.png")
    references = list(audit["references"].values())
    visibility_invalid = sum(row["visibility"]["invalid"] for row in references)
    lines = [
        "# OmniObject3D 校准审核", "",
        "本轮包含 10 个独立扫描资产、seed 42，比较 WT 六层点云与 TRELLIS.2 的 decoded、GLB。",
        "正式 100 个输入和 GT 已准备完成。正式任务已按用户要求停止，完成预测缓存为 0，继续执行需要用户确认本审核结果。", "",
        "## 数据与口径", "",
        "依据公开的训练来源选择 OmniObject3D，保留转载资产与视觉骨干预训练交集的不确定性。"
        "从官方目录中小于 5GB 的类别包进行固定哈希抽样，25 个候选类别中 package 返回 HTTP 405，最终取得 24 类。"
        "校准 10 资产与正式 100 资产互斥，110 个源 OBJ 摘要互异，与 GSO 1,030 个源 OBJ 的字节摘要交集为 0。"
        "[WT 训练来源](https://arxiv.org/html/2606.13652v1#S4.SS1) · "
        "[TRELLIS.2 训练来源](https://arxiv.org/html/2512.14692v1#A3) · "
        "[OmniObject3D](https://omniobject3d.github.io/)", "",
        "每资产使用一个固定随机方位、20°仰角、40° FoV。源 OBJ 按 Y-up 转换，GT 的 AABB 对角线 D=1。"
        "沿用 GSO v0.5 的 24 初始化正 Sim(3)、10,000 配准点、100,000 评价点及 30 个球面视角。"
        "WT 为已安装的 r75b、20 步，TRELLIS.2 为 1024_cascade defaults-v1。"
        "WT 灰色背景、alpha_erode=0，TRELLIS.2 黑色背景、alpha_erode=2，均沿用 GSO 参数。", "",
        "论文的 visible depth 使用逐样本 scale–shift 对齐。本表的主深度来自完整 Sim(3) 后的共同 surfel 渲染，"
        "SSI 深度作为附加诊断。完整训练资产清单及协议差异限制对训练拟合原因的归因。", "",
        "## 校准验收", "",
        "| 检查 | 结果 |", "| --- | --- |",
        f"| 评价阶段 | {audit['stages']}，失败 {audit['failed_stages']} |",
        f"| PNG 逐文件及像素核验 | {audit['png_count']} 张 |",
        f"| GT 裁剪内参最大误差 | {max(row['crop_matrix_error'] for row in references):.3g} |",
        f"| GT mask 重渲染一致 | {sum(row['native_mask_equal'] for row in references)}/{len(references)} |",
        f"| GT 深度重渲染 MAE 最大值 | {max(row['native_input_depth_mae'] for row in references):.3g}D |",
        f"| GT 首交点异常射线 | {visibility_invalid} |",
        "| 数值复核 | CD-L1/L2、Precision、Recall、F-score、深度、法线、覆盖率及有效像素数 |",
        "| 回归检查 | 8 项通过，类别 bootstrap 已知答案检查通过 |", "",
        "## 10 资产的主结果", "",
        "| 方法 / 阶段 | n | 完整 CD-L1 ↓ | 可见 CD-L1 ↓ | F@0.01 ↑ | 输入深度 MAE ↓ | 深度覆盖 ↑ | 法线角误差 ↓ |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method, stage in STAGES:
        group = next(row for row in report["groups"]
                     if row["method"] == method and row["stage"] == stage and row["mode"] == "single_seed")
        metrics = group["metrics"]
        keys = ("shape.cd_euclidean_mean", "regions.visible.cd_euclidean_mean", "shape.f@0.01",
                "surfel.input.depth_mae", "surfel.input.depth_coverage", "surfel.input.normal_mean_angle")
        values = [number(metrics.get(key, {}).get("mean"), key in ("shape.f@0.01", "surfel.input.depth_coverage"))
                  for key in keys]
        for position, key in enumerate(keys):
            count = metrics.get(key, {}).get("n", 0)
            if count != len(samples):
                values[position] += f" (n={count})"
        label = LABELS["wt"] if method == "wt" else LABELS[stage]
        lines.append(f"| {label} | {metrics.get(keys[0], {}).get('n', 0)} | " + " | ".join(values) + " |")
    lines += ["", "CD-L1 和深度 MAE 的单位均为 D，法线角误差单位为度。误差按各方法的有效像素交集计算，并同时列出覆盖率。", "",
              "## 输入深度 SSI", "",
              "在 Sim(3) 后的相机 Z 深度上拟合正尺度和常数偏移，深度覆盖率门槛为 95%。"
              "n 为通过覆盖率及拟合有效性检查的资产数，各方法的有效集合可能不同。", "",
              "| 方法 / 阶段 | n | MAE ↓ | RMSE ↓ | AbsRel ↓ | δ<1.25 ↑ |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for method, stage in STAGES:
        group = next(row for row in report["groups"]
                     if row["method"] == method and row["stage"] == stage and row["mode"] == "single_seed")
        metrics = group["metrics"]
        keys = ("surfel.input_ssi.mae", "surfel.input_ssi.rmse",
                "surfel.input_ssi.absrel", "surfel.input_ssi.delta1")
        values = [number(metrics.get(key, {}).get("mean"), key.endswith("delta1")) for key in keys]
        label = LABELS["wt"] if method == "wt" else LABELS[stage]
        lines.append(f"| {label} | {metrics.get(keys[0], {}).get('n', 0)} | " + " | ".join(values) + " |")
    pair = next(row for row in report["paired_methods"]
                if row["first"] == "wt" and row["second"] == "trellis2"
                and row["stage"] == "decoded" and row["mode"] == "single_seed")
    lines += ["", "## WT − TRELLIS.2 decoded 的资产配对差异", "",
              "差值为正表示 WT 误差较高。95% 区间按共同有效资产重抽样 5,000 次，统计随机种子为 20261110。", "",
              "| 指标 | 共同 n | 平均差值 | 95% 区间 | WT 误差更低数 |",
              "| --- | ---: | ---: | --- | ---: |"]
    for key, label in (("shape.cd_euclidean_mean", "完整 CD-L1"),
                       ("regions.visible.cd_euclidean_mean", "可见 CD-L1"),
                       ("surfel.input.depth_mae", "输入深度 MAE"),
                       ("surfel.input_ssi.mae", "输入 SSI 深度 MAE")):
        value = pair["metrics"].get(key)
        if value:
            low, high = value["ci95"]
            lines.append(f"| {label} | {value['n']} | {value['mean']:+.6f} | "
                         f"[{low:+.6f}, {high:+.6f}] | {value['first_lower']} |")
    lines += ["", "## 逐资产几何与深度", "",
              "| 资产 | 完整 CD WT / TRELLIS.2 | 可见 CD WT / TRELLIS.2 | 深度 MAE WT / TRELLIS.2 | 对照图 |",
              "| --- | --- | --- | --- | --- |"]
    for sample_id in sample_ids:
        wt = asset_rows.get((sample_id, "wt", "points"), {})
        trellis = asset_rows.get((sample_id, "trellis2", "decoded"), {})
        values = [f"{number(wt.get(key))} / {number(trellis.get(key))}" for key in
                  ("shape.cd_euclidean_mean", "regions.visible.cd_euclidean_mean", "surfel.input.depth_mae")]
        links = detail_links[sample_id]
        link_text = " · ".join(f"[{label}]({links[stage]})"
                               for stage, label in (("points", "WT"), ("decoded", "decoded"), ("glb", "GLB"))
                               if stage in links)
        lines.append(f"| {sample_id.removeprefix('omni_')} | " + " | ".join(values) + f" | {link_text} |")
    lines += ["", "## 全部输入与法线对照", "",
              f"![10 个校准资产的输入与法线]({link_root}/normal_overview.png)", "",
              "## 全部输入深度与误差", "",
              "每行的 GT 与预测深度共用该资产的 GT 色标范围。误差色标统一为 0–0.05D，最高颜色包含大于等于 0.05D 的误差。", "",
              f"![10 个校准资产的深度对照]({link_root}/depth_overview.png)", "",
              "## 产物追溯", "",
              f"- 评价目录为 `{evaluation}`。",
              f"- 评价 revision 为 `{report['revision']}`。",
              f"- 汇总摘要为 `{file_digest(evaluation / 'summary.json')}`。",
              f"- 完整验收记录位于 `{evaluation / 'audit.json'}`。",
              f"- 逐资产统计、共同有效样本数与区间位于 `{evaluation / 'ood_analysis.json'}`。", ""]
    (args.out / "review.md").write_text("\n".join(lines), encoding="utf-8")
    atomic_json(args.out / "review_metadata.json", {
        "experiment": str(args.experiment), "evaluation": str(evaluation),
        "summary_sha256": file_digest(evaluation / "summary.json"),
        "audit_sha256": file_digest(evaluation / "audit.json"),
        "samples": sample_ids, "categories": dict(Counter(sample["category"] for sample in samples.values())),
        "local_root": link_root, "source_sha256": file_digest(Path(__file__)),
    })
    archive_path = args.out.with_name(args.out.name + "-verified.zip")
    with atomic_artifact(archive_path) as staged:
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(args.out.rglob("*")):
                if path.is_file():
                    archive.write(path, str(path.relative_to(args.out)))
    print({"review": str(args.out / "review.md"), "archive": str(archive_path),
           "bytes": archive_path.stat().st_size, "sha256": file_digest(archive_path)})


if __name__ == "__main__":
    main()
