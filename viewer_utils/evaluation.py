"""Read frozen evaluation scalars for the viewer, without loading geometry or arrays."""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path

from wt.experiment import file_digest, resolve_reference

IDENTITY = ("sample_id", "method", "config_id", "seed", "stage")
IMAGE_ERRORS = {"depth_image_rmse", "depth_image_psnr", "normal_rmse", "normal_psnr"}
DEPTH_NAMES = {"depth_mae", "depth_rmse", "depth_absrel", "depth_delta1", "depth_delta2"}
STATUS = {
    "failed": "评测失败", "pending": "待评测", "not_applicable": "不适用",
    "empty_prediction": "预测区域为空", "invalid_visibility": "GT 可见性无效",
}


def identity(row):
    return tuple(row[name] for name in IDENTITY)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_document(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


@dataclass
class SampleMetrics:
    source: Path
    status: str
    reason: str = ""
    values: dict = field(default_factory=dict)
    reasons: dict = field(default_factory=dict)

    def put(self, key, value, reason="无有效比较"):
        if finite(value):
            self.values[key] = float(value)
            self.reasons.pop(key, None)
        else:
            self.values.pop(key, None)
            self.reasons[key] = reason


@dataclass
class EvaluationSnapshot:
    directory: Path
    dataset: str
    mode: str
    revision: str
    index_sha256: str
    planned: dict
    records: dict
    warnings: list
    means: dict = field(default_factory=dict)

    def __post_init__(self):
        buckets = defaultdict(lambda: defaultdict(list))
        for key, record in self.records.items():
            if record.status == "complete":
                for metric, value in record.values.items():
                    buckets[key[1:]][metric].append(value)
        self.means = {
            group: {metric: (math.fsum(values) / len(values), len(values))
                    for metric, values in metrics.items()}
            for group, metrics in buckets.items()
        }

    @property
    def evaluated(self):
        return len(self.records)

    @property
    def total(self):
        return sum(len(samples) for samples in self.planned.values())

    def cell(self, key, source, metric):
        record = self.records.get(key)
        total = len(self.planned.get(key[1:], ()))
        mean, count = self.means.get(key[1:], {}).get(metric, (None, 0))
        if record is None:
            return None, mean, count, total, "待评测"
        if record.source != Path(source):
            return None, None, 0, total, "预测来源目录不匹配"
        if record.status != "complete":
            return None, mean, count, total, record.reason or STATUS.get(record.status, record.status)
        value = record.values.get(metric)
        reason = record.reasons.get(metric)
        if reason is None:
            # Region/representation/SSI failures apply to every metric in that group.
            prefix = metric.rsplit(".", 1)[0]
            reason = record.reasons.get(prefix, "未记录或待补算")
        if metric.startswith("native.") and key[1] == "wt":
            reason = "WT 点云不适用 Native mesh"
        return value, mean, count, total, "" if value is not None else reason


def add_comparisons(target, comparisons, allowed=None):
    for representation in ("surfel", "native"):
        comparison = comparisons.get(representation, {})
        frame = comparison.get("input", {})
        full_frame = frame.get("image_metric_region") == "full_frame"
        for name, value in frame.get("metrics", {}).items():
            if allowed is not None and name not in allowed:
                continue
            key = f"{representation}.input.{name}"
            if name in IMAGE_ERRORS and not full_frame:
                target.put(key, None, "旧交集口径，待整图补算")
            else:
                target.put(key, value)
        multiview = comparison.get("multiview", {})
        views = multiview.get("views", [])
        full_frame = len(views) == 30 and all(
            view.get("image_metric_region") == "full_frame" for view in views)
        for row in multiview.get("metrics", []):
            name = row["metric"]
            if allowed is not None and name not in allowed:
                continue
            key = f"{representation}.multiview.{name}"
            complete = (row.get("status") == "complete"
                        and row.get("valid_views") == row.get("total_views") == 30)
            if name in IMAGE_ERRORS and not full_frame:
                target.put(key, None, "旧交集口径，待整图补算")
            elif not complete:
                target.put(key, None, f"有效视角 {row.get('valid_views', 0)}/30")
            else:
                target.put(key, row.get("value"))


def extract_record(record, source=None):
    result = SampleMetrics(source or Path(record["source_directory"]).resolve(), record["status"],
                           record.get("reason") or record.get("failure_phase", ""))
    if result.status != "complete":
        return result
    for name, value in record.get("shape", {}).items():
        result.put(f"shape.{name}", value)
    region = record.get("regions", {}).get("visible", {})
    reason = STATUS.get(region.get("status"), "无有效比较")
    result.reasons["regions.visible"] = reason
    for name, value in region.get("metrics", {}).items():
        result.put(f"regions.visible.{name}", value, reason)
    add_comparisons(result, record.get("comparisons", {}))
    rgb = record.get("input_rgb", {})
    for name in ("psnr", "lpips"):
        result.put(f"input_rgb.{name}", rgb.get(name), "RGB 外观不适用或无有效结果")
    return result


def apply_review(path, index, index_sha, entries, records, check_cancel):
    report, checksum = read_document(path)
    if (report.get("status") != "passed"
            or report.get("evaluation_revision") != index["revision"]
            or report.get("index_sha256") != index_sha):
        raise ValueError(f"{path.name} 的版本或索引摘要不匹配")
    if path.name == "render_image_fullframe_review.json":
        if report.get("config", {}).get("image_metric_region") != "full_frame":
            raise ValueError(f"{path.name} 缺少整图口径")
        allowed = None
    else:
        allowed = DEPTH_NAMES | {"silhouette_iou", "depth_coverage"}
    # Validate every row before updating any scalars.
    updates = []
    seen = set()
    for row in report.get("records", []):
        check_cancel()
        key = identity(row)
        entry = entries.get(key)
        if entry is None or key in seen:
            raise ValueError(f"{path.name} 包含重复或未知候选")
        seen.add(key)
        result_path = entry["result_path"]
        if (row.get("result_path") != result_path
                or row.get("source_files", {}).get(result_path) != entry["result_sha256"]):
            raise ValueError(f"{path.name} 的结果来源摘要不匹配")
        updates.append((key, row["comparisons"]))
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError(f"{path.name} 读取期间发生变化，请刷新")
    for key, comparisons in updates:
        if records[key].status == "complete":
            add_comparisons(records[key], comparisons, allowed)


def apply_l0(path, index, index_sha, entries, records, inputs):
    report, checksum = read_document(path)
    if report.get("status") != "passed":
        raise ValueError(f"{path.name} 复核未通过")
    for name, expected in (("evaluation_revision", index["revision"]), ("index_sha256", index_sha)):
        if name in report and report[name] != expected:
            raise ValueError(f"{path.name} 的 {name} 不匹配")
    updates = []
    seen = set()
    for row in report.get("records", []):
        candidates = [key for key, entry in entries.items()
                      if key[0] == row["sample_id"] and key[1] == "wt"
                      and (not row.get("result_path") or row["result_path"] == entry["result_path"])]
        matched = []
        for key in candidates:
            entry = entries[key]
            if row.get("result_path"):
                valid = row.get("result_sha256") == entry["result_sha256"]
                fit_path = records[key].source / "depth_fit.json"
                valid = valid and fit_path.is_file() and row.get("l0_source_sha256") == file_digest(fit_path)
            else:
                sources = row.get("source_files", {})
                prediction = str(records[key].source / "prediction.npz")
                gt_paths = [p for p in inputs[key] if Path(p).name == "gt_depth.npz"]
                valid = (prediction in sources and sources[prediction] == inputs[key].get(prediction)
                         and len(gt_paths) == 1 and sources.get(gt_paths[0]) == inputs[key][gt_paths[0]])
            if valid:
                matched.append(key)
        if len(matched) != 1 or matched[0] in seen:
            raise ValueError(f"{path.name} 的 WT 来源摘要或候选关联不匹配")
        key = matched[0]
        seen.add(key)
        updates.append((key, row["l0_ssi"]))
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError(f"{path.name} 读取期间发生变化，请刷新")
    for key, fit in updates:
        target = records[key]
        if target.status != "complete":
            continue
        reason = fit.get("reason") or STATUS.get(fit.get("status"), "无有效比较")
        target.reasons["l0_ssi"] = reason
        for name in ("mae", "rmse", "absrel", "delta1", "delta2"):
            target.put(f"l0_ssi.{name}", fit.get(name) if fit.get("status") == "complete" else None, reason)


def load_evaluation(root, evaluation=None, review=None, check_cancel=lambda: None):
    """Return an immutable-by-convention scalar snapshot, or None for unbound experiments."""
    root = Path(root).resolve()
    pointer_path = root / "baseline_evaluation.json"
    pointer = None
    if evaluation is None:
        if not pointer_path.is_file():
            return None
        pointer, _ = read_document(pointer_path)
        evaluation = resolve_reference(root, pointer["directory"])
    directory = Path(evaluation).resolve()
    index_path = directory / "index.json"
    index, index_sha = read_document(index_path)
    if pointer and (pointer.get("revision") != index["revision"]
                    or pointer.get("index_sha256") != index_sha):
        raise ValueError("评测指针与索引暂未同步，请刷新")
    plan_path = directory / "plan.json"
    plan, plan_sha = read_document(plan_path)
    seeds = plan.get("selected_seeds", plan["config"]["seeds"])
    candidates = [row for row in plan["candidates"] if row["seed"] in seeds]
    planned = defaultdict(set)
    planned_entries = {}
    sources = {}
    for row in candidates:
        check_cancel()
        key = identity(row)
        if key in planned_entries:
            raise ValueError("评测计划包含重复候选")
        planned_entries[key] = row
        planned[key[1:]].add(key[0])
        source_path = row["source_directory"]
        if source_path not in sources:
            sources[source_path] = Path(source_path).resolve()
        source = sources[source_path]
        if not source.is_relative_to(root / "samples"):
            raise ValueError("评测计划的预测来源与当前实验不匹配")
    entries, records, inputs = {}, {}, {}
    selected = [row for row in index["results"] if row["seed"] in seeds]
    # Four bounded readers overlap small JSON reads on object storage.
    def read_entry(row):
        check_cancel()
        return row, read_document(row["result_path"])

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="viewer-metric-read") as pool:
        for row, (record, checksum) in pool.map(read_entry, selected):
            check_cancel()
            key = identity(row)
            if key not in planned_entries or key in entries:
                raise ValueError("评测索引包含重复或计划外候选")
            if row["source_directory"] != planned_entries[key]["source_directory"]:
                raise ValueError("评测索引与计划的预测来源不匹配")
            if checksum != row["result_sha256"] or identity(record) != key or record["revision"] != index["revision"]:
                raise ValueError("评测结果摘要、候选身份或版本不匹配")
            if record["source_directory"] != row["source_directory"] or record["status"] != row["status"]:
                raise ValueError("评测结果与索引的来源或状态不匹配")
            entries[key] = row
            records[key] = extract_record(record, sources[row["source_directory"]])
            inputs[key] = record.get("inputs", {})
    warnings = []
    review_dir = Path(review).resolve() if review else directory
    if review and not review_dir.is_dir():
        warnings.append("复核目录不存在")
    for name in ("render_image_fullframe_review.json", "visible_depth_direct_review.json"):
        path = review_dir / name
        if path.is_file():
            try:
                apply_review(path, index, index_sha, entries, records, check_cancel)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append(str(exc))
    l0_paths = [review_dir / "visible_depth_l0_review.json", review_dir / "visible_depth_review.json"]
    if review_dir != directory:
        l0_paths.append(directory / "visible_depth_l0_review.json")
    l0_path = next((path for path in l0_paths if path.is_file()), None)
    if l0_path:
        try:
            apply_l0(l0_path, index, index_sha, entries, records, inputs)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(str(exc))
    check_cancel()
    if (hashlib.sha256(index_path.read_bytes()).hexdigest() != index_sha
            or hashlib.sha256(plan_path.read_bytes()).hexdigest() != plan_sha):
        raise ValueError("评测快照读取期间发生变化，请刷新")
    config = index["config"]
    return EvaluationSnapshot(directory, config.get("dataset", root.name),
                              plan.get("mode", "formal"), index["revision"], index_sha,
                              dict(planned), records, warnings)
