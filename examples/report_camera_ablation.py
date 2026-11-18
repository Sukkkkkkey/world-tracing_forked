"""Write the approved camera-ablation document from audited, complete results."""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from wt.experiment import atomic_json, file_digest, read_json

PRIMARY = ("shape.cd_euclidean_mean", "common_visible.cd_euclidean_mean")
LABELS = {
    ("wt", "defaults-v1"): "WT",
    ("trellis2", "defaults-v1"): "TRELLIS.2",
    ("wt_trellis2", "defaults-v1"): "Hybrid",
    ("wt_trellis2", "shared-wt-v1"): "Hybrid shared-WT",
    ("pixal3d", "resolution1024-v1"): "Pixal3D",
}


def number(value):
    return "—" if value is None else f"{value:.6f}"


def delta_cell(stat):
    if not stat or not stat["delta"]["n"]:
        return "—"
    value = stat["delta"]
    lo, hi = value["ci95"]
    return f"{value['mean']:+.6f} [{lo:+.6f}, {hi:+.6f}] (n={value['n']})"


def direction(stat):
    if not stat or not stat["delta"]["n"]:
        return "没有足够有效配对"
    lo, hi = stat["delta"]["ci95"]
    if hi < 0:
        return "下降，95% 配对区间完全小于零"
    if lo > 0:
        return "上升，95% 配对区间完全大于零"
    return "变化的95%配对区间包含零"


def label(row):
    return LABELS[row["method"], row["config_id"]] + " " + row["stage"]


def metric(row, name):
    return row["metrics"].get(name)


def verify_complete(report, state):
    if report["status"] != "complete" or state["status"] != "complete":
        raise ValueError("Only complete audited results can replace the document results")
    if not report.get("include_runtime_control"):
        raise ValueError("Same-runtime sensitivity is required")
    if report["seed"] != 42 or report["source_revision"] != state["source_revision"]:
        raise ValueError("Seed or numerical source differs")
    expected = {f"{d}/{c}" for d in ("GSO", "OOD") for c in ("A0", "A1", "B0", "B1")}
    if set(report["sources"]) != expected or set(state["experiments"]) != expected:
        raise ValueError("Missing camera condition")
    for condition in sorted(expected):
        entry, source = state["experiments"][condition], report["sources"][condition]
        if entry["evaluated_stages"] != 900 or entry["pending_stages"] != 0:
            raise ValueError("Incomplete 900-stage condition")
        if entry["status_counts"] != {"complete": 900, "failed": 0}:
            raise ValueError("Unresolved stage failure")
        evaluation = Path(entry["evaluation"])
        if source["evaluation"] != str(evaluation) or source["total"] != 900 or source["complete"] != 900:
            raise ValueError("Analysis coverage differs")
        if source["index_sha256"] != file_digest(evaluation / "index.json"):
            raise ValueError("Analysis index changed")
        for name in ("index.json", "summary.json", "audit.json", "visible_depth_l0_review.json"):
            if file_digest(evaluation / name) != entry[name + "_sha256"]:
                raise ValueError("Final audited artifact changed")
        if read_json(evaluation / "audit.json")["status"] != "passed":
            raise ValueError("Artifact audit failed")
    expected_methods = {("wt", "defaults-v1", "points")} | {
        (method, config, stage) for method, config in LABELS if method != "wt"
        for stage in ("decoded", "glb")}
    expected_groups = {(d, g) for d in ("GSO", "OOD")
                       for g in ("A", "B", "implementation_control", "A_same_runtime")}
    for dataset, group in expected_groups:
        rows = [r for r in report["pairs"] if (r["dataset"], r["group"]) == (dataset, group)]
        if len(rows) != 9 or any(row["paired_assets"] != 100 for row in rows):
            raise ValueError("Missing method/configuration/stage pair")
        keys = {(r["method"], r["config_id"], r["stage"]) for r in rows}
        if keys != expected_methods:
            raise ValueError("Method/configuration/stage plan differs")
        for row in rows:
            if row["metrics"].get(PRIMARY[0], {}).get("delta", {}).get("n") != 100:
                raise ValueError("Incomplete whole-geometry metric")


def markdown(report, state, analysis_path):
    lines = ["## 结果与分析", "",
             "正式结果已完成。GSO R2 100 资产与 OmniObject3D ood-v2 100 资产，"
             "四个相机条件、五个方法配置、单 seed 42，共 7,200/7,200 个评价阶段通过审核。"
             "其中复用既有 600 份预测，新增方法配置输出 3,400 份；A0 已有阶段也按当前实现重新评测。", "",
             "以下均为资产等权统计。差值定义为匹配条件减控制条件；距离以 GT AABB 对角线 D 为单位。"
             "95% 区间由同资产配对差值的 5,000 次 bootstrap 得到，统计 seed 20261110。"
             "各指标的有效配对分母独立计算；未通过 SSI 或渲染有效性检查的项不进入对应均值。"
             "OOD 类别重抽样区间保存在分析 JSON。", "",
             f"完整逐资产指标、区间、样本列表和来源摘要见 [分析 JSON]({analysis_path})。"
             "本页突出预先确定的完整与共同可见 CD-L1；完整指标表保存在各条件 summary.json。", ""]
    for dataset in ("GSO", "OOD"):
        lines += [f"### {dataset}：完整与共同可见几何", ""]
        for group, title in (("A", "A1−A0：参考相机与构图联合变化"),
                             ("B", "B1−B0：固定外参与裁剪的内参变化")):
            rows = [r for r in report["pairs"] if (r["dataset"], r["group"]) == (dataset, group)]
            lines += [f"**{title}**", "",
                      "| 方法 / 阶段 | 完整 CD 控制→匹配 | Δ完整 CD [95% CI] | 共同可见 CD 控制→匹配 | Δ共同可见 CD [95% CI] |",
                      "| --- | --- | --- | --- | --- |"]
            for row in rows:
                cells = []
                for name in PRIMARY:
                    stat = metric(row, name)
                    cells += [f"{number(stat['control']['mean'])}→{number(stat['matched']['mean'])}"
                              if stat else "—", delta_cell(stat)]
                lines.append("| " + label(row) + " | " + " | ".join(cells) + " |")
            lines.append("")
            wt = next(row for row in rows if row["method"] == "wt")
            lines.append(f"WT 的完整 CD-L1 {direction(metric(wt, PRIMARY[0]))}；"
                         f"共同可见 CD-L1 {direction(metric(wt, PRIMARY[1]))}。")
            for stage in ("decoded", "glb"):
                gap = next(row for row in report["method_gap_pairs"] if
                           (row["dataset"], row["group"], row["stage"]) == (dataset, group, stage))
                stat = gap["metrics"].get(PRIMARY[0])
                if stat:
                    lines.append(
                        f"相对 TRELLIS.2 {stage}，完整 CD 的 WT−TRELLIS.2 差距由 "
                        f"{number(stat['control']['mean'])} 变为 {number(stat['matched']['mean'])}；"
                        f"差距变化 {delta_cell(stat)}。负的差距变化表示 WT 的相对误差降低，"
                        "是否超过 TRELLIS.2 仍由匹配条件下的差值判断。")
            lines.append("")
        lines += [f"### {dataset}：输入深度与渲染对照", "",
                  "下表列变化均为匹配减控制。物理深度 MAE 来自 Sim(3) 后输入重渲染的有效 mask 交集；"
                  "图像 LPIPS 对含中性灰背景的整图计算。IoU 与覆盖率上升较好，误差下降较好。"
                  "其余 RMSE、PSNR、AbsRel、δ1、δ2 和法线角误差均保留于分析 JSON。", "",
                  "| 组 / 方法 | Δ物理 MAE | Δ输入深度 LPIPS | Δ输入法线 LPIPS | Δ输入 IoU | Δ输入深度覆盖率 | Δ30-view 深度 LPIPS | Δ30-view IoU |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for group in ("A", "B"):
            for row in report["pairs"]:
                if (row["dataset"], row["group"]) != (dataset, group) or row["stage"] == "glb":
                    continue
                names = ["surfel.input.depth_mae", "surfel.input.depth_image_lpips",
                         "surfel.input.normal_lpips", "surfel.input.silhouette_iou",
                         "surfel.input.depth_coverage", "surfel.multiview.depth_image_lpips",
                         "surfel.multiview.silhouette_iou"]
                lines.append("| " + group + " / " + label(row) + " | " +
                             " | ".join(delta_cell(metric(row, name)) for name in names) + " |")
        lines.append("")
    lines += ["### WT 相机、原像素深度与解释", "",
              "| 数据 / 组 | Δ拟合 fx 相对误差绝对值 | Δ拟合 fy 相对误差绝对值 | Δ真实 K 重投影 P95 (px) | L0＋SSI MAE 控制→匹配 | ΔL0＋SSI MAE |",
              "| --- | --- | --- | --- | --- | --- |"]
    for row in report["pairs"]:
        if row["group"] not in ("A", "B") or row["method"] != "wt":
            continue
        names = ["camera.fx_absolute_relative_error", "camera.fy_absolute_relative_error",
                 "camera.gt_reprojection_p95"]
        ssi = metric(row, "wt_l0_ssi.mae")
        cells = [delta_cell(metric(row, name)) for name in names]
        cells += [f"{number(ssi['control']['mean'])}→{number(ssi['matched']['mean'])}" if ssi else "—",
                  delta_cell(ssi)]
        lines.append("| " + row["dataset"] + " / " + row["group"] + " | " + " | ".join(cells) + " |")
    lines += ["",
              "实际输入 K 匹配训练参考值，并不保证 WT 输出隐含的拟合 K 自动匹配真实 K。"
              "需要结合上表的拟合内参、重投影误差和三维指标共同判断。若内参误差与完整/共同可见误差同时降低，"
              "结果支持相机或射线标定误差参与了原有差距；单独图像或 SSI 改善不足以确认这一原因。",
              "",
              "L0＋SSI 保持原像素对应并允许 z′=az+b。即使 K 一致，深度平移 b 在三维中产生 "
              "b·K⁻¹[u,v,1] 的逐射线位移，一般不能被一个全局三维平移代替。"
              "因此较好的 SSI 相对深度与残留的 Sim(3) 形状误差仍可同时存在。", "",
              "### Hybrid 与实际 WT parent", "",
              "parent 使用实际推理缓存，并分别进行完整形状 Sim(3)。正的 Hybrid−parent CD 表示"
              " Hybrid 的完整几何误差更大；Δ表示这种损失在相机干预后增加或减少。", "",
              "| 数据 / 组 / 配置 / 阶段 | Hybrid−parent CD 控制→匹配 | Δ差距 [95% CI] |",
              "| --- | --- | --- |"]
    for row in report["pairs"]:
        if row["group"] not in ("A", "B") or row["method"] != "wt_trellis2":
            continue
        stat = metric(row, "hybrid_minus_parent.cd")
        if stat:
            lines.append(f"| {row['dataset']} / {row['group']} / {label(row)} | "
                         f"{number(stat['control']['mean'])}→{number(stat['matched']['mean'])} | {delta_cell(stat)} |")
    lines += ["",
              "defaults-v1 的黑背景、腐蚀 mask parent 与独立灰背景 WT 不同；shared-wt-v1 才复用同条件独立 WT。"
              "两个配置分别解释。若 parent 改善而 Hybrid 误差未相应下降，结构转换或生成补全过程仍是候选原因，"
              "当前消融不能单独定位其中某个模块。",
              "",
              "### 重跑控制与适用范围", "",
              "| 数据 / 方法 / 阶段 | B0−A0 完整 CD | A1−B0 完整 CD |",
              "| --- | --- | --- |"]
    lookup={(r["dataset"],r["group"],r["method"],r["config_id"],r["stage"]):r for r in report["pairs"]}
    for row in report["pairs"]:
        if row["group"] != "implementation_control":
            continue
        other=lookup[(row["dataset"],"A_same_runtime",row["method"],row["config_id"],row["stage"])]
        lines.append(f"| {row['dataset']} / {label(row)} | {delta_cell(metric(row, PRIMARY[0]))} | "
                     f"{delta_cell(metric(other, PRIMARY[0]))} |")
    lines += ["",
              "B0−A0反映复用基线与当前执行环境、预处理适配和重跑的综合差异。"
              "A1−B0补充同执行环境对照，不增加推理预算。若它与A1−A0方向不一致，"
              "应优先报告这一不一致，不能把复用基线的全部差距归因于相机。",
              "",
              "A同时改变相机距离、平移构图、透视和可见区域，光轴旋转与roll固定。"
              "B固定外参和各模型裁剪，但物体投影占幅、像素密度及视锥范围随K改变。"
              "B1更大的背景比例可能降低整图误差；须结合IoU、覆盖率和三维主指标解释。"
              "WT点数量与法线估计也可能随投影占幅改变。共同可见几何使用两条件相同的GT点集，"
              "30-view使用同一组世界相机。",
              "",
              "本实验限于固定seed42和所选100+100资产。GT规范化、扫描差异、surfel转换和ICP局部最优"
              "仍会影响指标。训练参考K来自公开默认配置，完整训练相机分布及检查点对应关系未确定。"
              "多项指标区间是描述性配对区间，没有进行多重比较校正；主要结局预先指定为完整和共同可见CD-L1。",
              "",
              "### 审计与产物", "",
              f"- 已发布基线：06e2335490c6b734fa854de0c53f05d873260105，"
              "提交说明 hybrid baseline on evaluation protocol v0.5；docs仅推送v0.5协议。",
              f"- 数值源码：{report['source_revision']}；分析revision：{report['revision']}。",
              "- 每候选保留31视角NPZ，默认仅input-view PNG；文件摘要、相机、配准变换和两Hybrid配置均独立核验。",
              "- 60组相机校准通过；最大焦距相对偏差0.195695%，最大主点偏差0.493151px。"
              "正式准备过程对每个A1/B1输入继续检查同一容差。",
              "- 一次Pixal3D Git可信目录环境启动错误已保存并以同seed恢复，"
              "未更换样本或择优重试。其余技术事件见运行控制目录与原始日志。",
              "",
              "| 条件 | 评测revision | 完成/计划 | 产物索引 |",
              "| --- | --- | ---: | --- |"]
    for condition, entry in sorted(state["experiments"].items()):
        source=report["sources"][condition]
        root=Path(entry["evaluation"])
        lines.append(f"| {condition} | {source['revision']} | 900/900 | [summary]({root/'summary.json'}) · "
                     f"[audit]({root/'audit.json'}) · [render index]({root/'render_index.md'}) |")
    lines += ["", f"完整结果写入时间（UTC）：{datetime.now(timezone.utc).isoformat()}。", ""]
    return "\n".join(lines)


def write_report(analysis_path, state_path, document, output):
    report, state = read_json(analysis_path), read_json(state_path)
    verify_complete(report, state)
    if document.name != "20261112_hybrid-baseline_camera-ablation.md" or document.parent.name != "docs":
        raise ValueError("Unexpected target document")
    before = document.read_text()
    if "## 结果与分析\n" not in before:
        raise ValueError("Approved document results section missing")
    protocols = [document.parent/"evaluation_protocol_v0.5.md",
                 document.parent/"archived/evaluation_protocol_v0.md"]
    checksums = {str(p):file_digest(p) for p in protocols}
    text = before.split("## 结果与分析\n", 1)[0] + markdown(report, state, analysis_path)
    output.mkdir(parents=True, exist_ok=True)
    backup = output / (document.name + ".before")
    if not backup.exists():
        backup.write_text(before)
    temporary = document.with_name(document.name + ".camera-results.tmp")
    temporary.write_text(text)
    if not text.endswith("\n") or any(line.rstrip() != line for line in text.splitlines()):
        raise ValueError("Document whitespace check failed")
    os.replace(temporary, document)
    if checksums != {str(p):file_digest(p) for p in protocols}:
        raise ValueError("Protocol changed while writing report")
    verification = dict(status="passed", document=str(document), document_sha256=file_digest(document),
                        analysis=str(analysis_path), analysis_sha256=file_digest(analysis_path),
                        state_sha256=file_digest(state_path), source_sha256=file_digest(Path(__file__)),
                        protocol_sha256=checksums, evaluated_stages=7200)
    atomic_json(output/"document-verification.json", verification)
    return verification


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args=parser.parse_args()
    print(write_report(args.analysis,args.state,args.document,args.output))


if __name__ == "__main__":
    main()
