"""Viser metric tables and background snapshot loading."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import html
import threading

from .evaluation import load_evaluation


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    unit: str = ""
    direction: str = "↓"


GEOMETRY = (
    Metric("cd_euclidean_mean", "CD-L1", "D"),
    Metric("cd_squared_mean", "CD-L2", "D²"),
    Metric("pred_to_gt_mean", "Pred→GT", "D"),
    Metric("gt_to_pred_mean", "GT→Pred", "D"),
    Metric("precision@0.01", "P@0.01", "%", "↑"),
    Metric("precision@0.05", "P@0.05", "%", "↑"),
    Metric("recall@0.01", "R@0.01", "%", "↑"),
    Metric("recall@0.05", "R@0.05", "%", "↑"),
    Metric("f@0.01", "F@0.01", "%", "↑"),
    Metric("f@0.05", "F@0.05", "%", "↑"),
)
DEPTH = (
    Metric("mae", "MAE", "D"), Metric("rmse", "RMSE", "D"),
    Metric("absrel", "AbsRel"),
    Metric("delta1", "δ1", "%", "↑"), Metric("delta2", "δ2", "%", "↑"),
)
IMAGES = (
    Metric("depth_image_rmse", "深度 RMSE"),
    Metric("depth_image_psnr", "深度 PSNR", "dB", "↑"),
    Metric("depth_image_lpips", "深度 LPIPS"),
    Metric("normal_rmse", "法线 RMSE"),
    Metric("normal_psnr", "法线 PSNR", "dB", "↑"),
    Metric("normal_lpips", "法线 LPIPS"),
    Metric("silhouette_iou", "轮廓 IoU", "%", "↑"),
    Metric("depth_coverage", "深度覆盖", "%", "↑"),
    Metric("normal_mean_angle", "法线角误差", "°"),
    Metric("normal_coverage", "法线覆盖", "%", "↑"),
)
RGB = (Metric("psnr", "RGB PSNR", "dB", "↑"), Metric("lpips", "RGB LPIPS"))
METHODS = {"wt": "WT", "trellis2": "TRELLIS.2", "wt_trellis2": "Hybrid", "pixal3d": "Pixal3D"}


def escaped(text):
    return html.escape(str(text)).replace("|", "&#124;").replace("\n", " ")


def number(value, unit="", *, difference=False):
    if value is None:
        return "—"
    sign = "+" if difference else ""
    if unit == "%":
        suffix = "pp" if difference else "%"
        return f"{value * 100:{sign}.2f}{suffix}"
    return f"{value:{sign}.4g}"


@dataclass(frozen=True)
class Comparison:
    key: tuple
    source: Path
    label: str


def comparisons_for(sample_id, runs, selected_stage):
    counts = Counter(run.method for run in runs)
    order = {method: index for index, method in enumerate(METHODS)}
    comparisons = []
    for run in sorted(runs, key=lambda item: (
            order.get(item.method, len(order)), item.config_id, str(item.seed))):
        stage = "points" if run.method == "wt" else selected_stage
        label = f"{METHODS.get(run.method, run.method)} · {stage}"
        if counts[run.method] > 1:
            label += f" / {run.config_id} / seed {run.seed}"
        key = (sample_id, run.method, run.config_id, run.seed, stage)
        comparisons.append(Comparison(key, run.directory.resolve(), label))
    return comparisons


def metric_table(snapshot, comparisons, prefix, metric):
    lines = ["| 方法 | 本样本 | 均值 | Δ | n/N |",
             "| --- | ---: | ---: | ---: | ---: |"]
    reasons = {}
    for comparison in comparisons:
        value, mean, count, total, reason = snapshot.cell(
            comparison.key, comparison.source, prefix + metric.name)
        delta = value - mean if value is not None and mean is not None else None
        cells = [escaped(comparison.label), number(value, metric.unit), number(mean, metric.unit),
                 number(delta, metric.unit, difference=True), f"{count}/{total}"]
        lines.append("| " + " | ".join(cells) + " |")
        if reason:
            reasons.setdefault(reason, []).append(comparison.label)
    for reason, labels in reasons.items():
        lines.extend(["", f"{escaped('、'.join(labels))} — {escaped(reason)}"])
    return "\n".join(lines)


class Superseded(Exception):
    """A newer refresh or close superseded a snapshot load."""


class EvaluationPanel:
    def __init__(self, gui, tab, root, lock, evaluation=None, review=None):
        self.gui, self.tab, self.root = gui, tab, root
        self.lock = lock
        self.condition = threading.Condition(lock)
        self.evaluation, self.review = evaluation, review
        self.snapshot = None
        self.version = 0
        self.pending = None
        self.closed = False
        self.selection = ("", (), "glb")
        self.categories = {}
        self.tables = {}
        with tab:
            self.header = gui.add_markdown("正在读取评测索引…")
            self.representation = gui.add_dropdown(
                "评测表示", ("Surfel（共同评测）", "Native mesh（补充）"))
            self.help = gui.add_markdown(
                "Δ = 本样本 − 数据集均值。↑/↓ 表示指标优劣方向，pp 为百分点，n/N 为有效资产数/计划资产数。")
            self.sample_label = gui.add_markdown("请选择样本。")
            with gui.add_folder("配置与 seed", expand_by_default=False):
                self.selection_details = gui.add_markdown("")
        self.representation.on_update(self.draw)
        self.worker = threading.Thread(target=self._worker, name="viewer-metrics", daemon=True)
        self.worker.start()
        self.refresh()

    def refresh(self):
        with self.condition:
            if self.closed:
                return
            self.version += 1
            self.pending = self.version
            self.snapshot = None
            self.header.content = "正在读取评测指标…"
            self.draw()
            self.condition.notify()

    def close(self):
        with self.condition:
            self.closed = True
            self.version += 1
            self.condition.notify_all()
        self.worker.join(timeout=2)

    def _worker(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                version, self.pending = self.pending, None

            def check_cancel():
                with self.lock:
                    if self.closed or version != self.version:
                        raise Superseded()

            try:
                snapshot = load_evaluation(self.root, self.evaluation, self.review, check_cancel)
                error = None
            except Superseded:
                continue
            except Exception as exc:
                snapshot, error = None, str(exc)
            with self.lock:
                if self.closed or version != self.version:
                    continue
                self.snapshot = snapshot
                if error:
                    self.header.content = f"评测读取失败 — {escaped(error)}"
                elif snapshot is None:
                    self.header.content = "未关联评测。实验模式可用 --evaluation 指定评测目录。"
                else:
                    self.header.content = self.description(snapshot)
                self.draw()

    @staticmethod
    def description(snapshot):
        mode = "校准集" if snapshot.mode == "calibration" else "正式集"
        complete = sum(row.status == "complete" for row in snapshot.records.values())
        failed = sum(row.status == "failed" for row in snapshot.records.values())
        mean_label = "当前有效样本均值" if snapshot.evaluated < snapshot.total else "数据集均值"
        lines = [
            f"**{escaped(snapshot.dataset)} · {mode}**",
            f"Sim(3) · D=1 · {mean_label}",
            f"阶段 {snapshot.evaluated}/{snapshot.total} · 成功 {complete} · 失败 {failed}",
            f"评测版本 {escaped(snapshot.revision)}",
        ]
        if snapshot.warnings:
            lines.extend(f"复核提示 — {escaped(message)}" for message in snapshot.warnings)
        return "\n\n".join(lines)

    def select(self, sample_id, runs, stage):
        with self.lock:
            self.selection = (sample_id, tuple(runs), stage)
            self.draw()

    def _metric(self, category, context, metric, expand=False):
        key = (category, context, metric.name)
        if key in self.tables:
            return self.tables[key]
        if category not in self.categories:
            with self.tab:
                self.categories[category] = self.gui.add_folder(
                    category, expand_by_default=category.startswith("Geometry"))
        label = f"{context} · {metric.label} {metric.direction}"
        if metric.unit and metric.unit != "%":
            label += f" ({metric.unit})"
        with self.categories[category]:
            folder = self.gui.add_folder(label, expand_by_default=expand)
            with folder:
                content = self.gui.add_markdown("")
        self.tables[key] = (folder, content)
        return folder, content

    def draw(self, _=None):
        with self.lock:
            if self.closed:
                return
            sample_id, runs, selected_stage = self.selection
            self.sample_label.content = f"**样本 {escaped(sample_id)}**" if sample_id else "请选择样本。"
            for folder in self.categories.values():
                folder.visible = bool(sample_id and runs)
            if not runs:
                self.selection_details.content = ""
                if sample_id:
                    self.sample_label.content += "\n\n当前筛选无方法结果。"
                return
            comparisons = comparisons_for(sample_id, runs, selected_stage)
            self.selection_details.content = "\n\n".join(
                f"{escaped(METHODS.get(row.key[1], row.key[1]))} · {escaped(row.key[4])}"
                f" — {escaped(row.key[2])} / seed {escaped(row.key[3])}"
                for row in comparisons)
            if self.snapshot is None or not sample_id:
                for _, content in self.tables.values():
                    content.content = "正在读取评测指标…"
                return
            representation = "surfel" if self.representation.value.startswith("Surfel") else "native"
            wt = [row for row in comparisons if row.key[1] == "wt"]
            glb = [row for row in comparisons if row.key[4] == "glb"]
            direct = tuple(Metric("depth_" + m.name, m.label, m.unit, m.direction) for m in DEPTH)
            sections = (
                ("Geometry（whole & visible）", "Whole", "shape.", GEOMETRY, comparisons),
                ("Geometry（whole & visible）", "Visible", "regions.visible.", GEOMETRY, comparisons),
                ("Visible depth", "Sim(3) 重渲染", f"{representation}.input.", direct, comparisons),
                ("Visible depth", "WT L0＋SSI 补充", "l0_ssi.", DEPTH, wt),
                ("Input view & multi-view", "Input view", f"{representation}.input.", IMAGES, comparisons),
                ("Input view & multi-view", "30-view", f"{representation}.multiview.", IMAGES, comparisons),
                ("Input view & multi-view", "GLB 输入 RGB", "input_rgb.", RGB, glb),
            )
            for category, context, prefix, metrics, rows in sections:
                for index, metric in enumerate(metrics):
                    folder, content = self._metric(category, context, metric, expand=index == 0)
                    folder.visible = bool(rows)
                    content.content = metric_table(self.snapshot, rows, prefix, metric)
