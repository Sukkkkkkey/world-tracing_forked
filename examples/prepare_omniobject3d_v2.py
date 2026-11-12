"""Freeze and prepare a category-proportional, geometry-ordered OmniObject3D sample."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import ks_2samp, rankdata

from examples.download_omniobject3d import download
from examples.prepare_gso_views import prepare
from examples.prepare_omniobject3d import extract_selected, inspect_archive
from wt.artifacts import atomic_artifact
from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import OUTPUT_ROOT, PROCESSED_ROOT

FEATURES = ("pca_minor_major", "pca_middle_major", "radial_cv",
            "hull_fill", "local_surface_variation")
SEED = 20261111


def write_jsonl(path, rows):
    with atomic_artifact(path) as staged:
        staged.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def systematic_sample(population, count=100):
    rows = [dict(row) for row in population]
    coordinates = np.column_stack([
        rankdata([row[name] for row in rows], method="average") / len(rows)
        for name in FEATURES])
    coordinates = np.minimum((coordinates * 256).astype(int), 255)
    for row, values in zip(rows, coordinates):
        morton = 0
        for bit in range(8):
            for dimension, value in enumerate(values):
                morton |= int((value >> bit) & 1) << (bit * len(FEATURES) + dimension)
        row["geometry_order"] = morton
    rows.sort(key=lambda row: (
        hashlib.sha256(("20261111-v2:category:" + row["category"]).encode()).hexdigest(),
        row["geometry_order"], row["source_id"]))
    interval = len(rows) / count
    start = float(np.random.default_rng(SEED).uniform(0, interval))
    selected = [rows[int(start + index * interval)] for index in range(count)]
    if len({row["source_id"] for row in selected}) != count:
        raise ValueError("Systematic sample contains duplicate assets")
    category_counts = Counter(row["category"] for row in rows)
    selected_counts = Counter(row["category"] for row in selected)
    for category, size in category_counts.items():
        expected = count * size / len(rows)
        if selected_counts[category] not in (int(np.floor(expected)), int(np.ceil(expected))):
            raise ValueError("Category allocation exceeds proportional rounding")
    return selected, start, interval


def freeze(root):
    old = PROCESSED_ROOT / "omniobject3d/ood-v1"
    features_path = OUTPUT_ROOT / "validation/ood-manifest-review-20261111/population_features.json"
    if (root / "selection.json").exists():
        return read_json(root / "selection.json")
    population = read_json(features_path)
    old_selection = read_json(old / "selection.json")
    pilot = {row["source_id"] for row in old_selection["samples"] if row["split"] == "pilot"}
    entries = {Path(row["path"]).name.removesuffix(".tar.gz"): row
               for row in read_json(old / "official_index.json")["list"] if row["schema"] == "file"}
    oversized = {name for name, row in entries.items() if row["size"] >= 5_000_000_000}
    unavailable = {"package"}
    frame = [row for row in population if row["source_id"] not in pilot
             and not row.get("identity_status") and row["category"] not in oversized | unavailable]
    selected, start, interval = systematic_sample(frame)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source_archives").mkdir(exist_ok=True)
    for row in selected:
        category = row["category"]
        entry = entries[category]
        row.update(asset_id="omni_" + row["source_id"], split="eval100",
                   archive=str(root / "source_archives" / Path(entry["path"]).name),
                   archive_sha256=entry["sha256"], inclusion_probability=100 / len(frame))
    def preparation_order(row):
        archive = old / "source_archives" / Path(row["archive"]).name
        cached = archive.exists()
        already_extracted = (old / "source_scans" / row["category"] /
                             row["source_id"] / "Scan" / "Scan.obj").exists()
        return not already_extracted, not cached, entries[row["category"]]["size"], row["source_id"]
    ordered = sorted(selected, key=preparation_order)
    batches = [ordered[:1], ordered[1:10]]
    batches.extend(ordered[index:index + 10] for index in range(10, 100, 10))
    split = {"dataset": "omniobject3d-ood-v2", "splits": {
        "eval100": [row["asset_id"] for row in selected],
        **{f"batch{index:02d}": [row["asset_id"] for row in batch] for index, batch in enumerate(batches)}}}
    selection = {
        "dataset": "omniobject3d-ood-v2", "seed": SEED,
        "design": "Equal-probability systematic sampling over category blocks and 5-D geometry Morton ordering",
        "category_order": "SHA256('20261111-v2:category:' + category)",
        "geometry_features": FEATURES, "geometry_rank_bits": 8,
        "start": start, "interval": interval, "inclusion_probability": 100 / len(frame),
        "frame_assets": len(frame), "frame_categories": len({row["category"] for row in frame}),
        "population_assets": len(population), "population_categories": len(entries),
        "excluded_large_categories": sorted(oversized),
        "acquisition_exclusions": [{"category": "package", "status": 405,
                                    "rechecked": "2026-11-11", "source": "official OpenXLab resolve"}],
        "excluded_pilot_ids": sorted(pilot),
        "excluded_unidentified_rows": [row["source_id"] for row in population if row.get("identity_status")],
        "selection_uses_model_outputs": False,
        "source_features": str(features_path), "source_features_sha256": file_digest(features_path),
        "official_index_sha256": file_digest(old / "official_index.json"),
        "source_sha256": file_digest(Path(__file__)), "samples": selected,
        "batch_order": [f"batch{index:02d}" for index in range(len(batches))],
        "inference_seed": 42, "uncertainty": "Asset/category bootstrap is descriptive for this frozen sample; design variance is not estimated.",
    }
    categories = Counter(row["category"] for row in selected)
    archives = [entries[category] for category in categories]
    plan = {"source": "official OpenXLab raw scans", "archives": archives,
            "file_limit_bytes": 5_000_000_000,
            "download_bytes": sum(row["size"] for row in archives),
            "new_download_bytes": sum(row["size"] for row in archives
                                      if not (old / "source_archives" / Path(row["path"]).name).exists())}
    diagnostics = {}
    for name in FEATURES:
        reference = np.array([row[name] for row in population])
        values = np.array([row[name] for row in selected])
        low, high = np.quantile(reference, [.1, .9])
        diagnostics[name] = {
            "population_mean": float(reference.mean()), "selected_mean": float(values.mean()),
            "ks_distance": float(ks_2samp(values, reference).statistic),
            "below_population_p10": int((values < low).sum()),
            "above_population_p90": int((values > high).sum())}
    audit = {"assets": len(selected), "categories": len(categories), "category_counts": dict(categories),
             "source_covered_assets": sum(row["category"] in categories for row in population),
             "features": diagnostics, "new_download_bytes": plan["new_download_bytes"],
             "pilot_overlap": sorted(pilot & {row["source_id"] for row in selected})}
    atomic_json(root / "selection.json", selection)
    atomic_json(root / "split.json", split)
    atomic_json(root / "download_plan.json", plan)
    atomic_json(root / "sampling_audit.json", audit)
    lines = ["# OmniObject3D 正式抽样 v2", "",
             f"冻结 100 个资产，覆盖 {len(categories)} 类。推理使用 seed 42。", "",
             f"从有明确 ID、可下载原始扫描的 {len(frame)} 个资产、{selection['frame_categories']} 类中等概率系统抽样。"
             "按类别分块，类别内依五项几何特征的秩进行空间排序，使用固定随机起点等间距取样。"
             "每类配额为其总体频率对应期望值的向上或向下取整，各资产纳入概率相同。", "",
             "类别目录顺序和几何排序均在模型推理前确定。单文件下载限制排除 9 个大包类别，"
             "package 的官方入口复核仍为 HTTP 405。10 个校准资产和一个身份未确定的 anise 点云单独记录。"
             "材质、纹理分布与转载资产重叠风险继续保留在结果解释中。", "",
             "| 类别 | 正式资产 |", "| --- | --- |"]
    for category in sorted(categories):
        ids = [row["source_id"] for row in selected if row["category"] == category]
        lines.append(f"| {category} | {', '.join(ids)} |")
    lines += ["", f"随机起点为 {start:.9f}，步长为 {interval:.6f}，纳入概率为 {100/len(frame):.9f}。",
              "资产和类别 bootstrap 用于描述本次冻结样本的不确定性，单次系统抽样的设计方差尚未估计。", ""]
    (root / "sampling_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(audit, flush=True)
    return selection


def acquire_category(root, category, samples, entry):
    old = PROCESSED_ROOT / "omniobject3d/ood-v1"
    output = root / "category_inventory" / f"{category}.json"
    if output.exists():
        rows = read_json(output)
        if {row["asset_id"] for row in rows} != {row["asset_id"] for row in samples}:
            raise ValueError("Frozen category membership changed")
        for row in rows:
            if file_digest(Path(row["mesh"])) != row["source_mesh_sha256"]:
                raise ValueError("Extracted source mesh changed")
        return rows
    target = root / "source_archives" / Path(entry["path"]).name
    previous = old / "source_archives" / target.name
    archive_directory = previous.parent if previous.exists() else target.parent
    download(entry, archive_directory)
    archive_path = archive_directory / target.name
    index = inspect_archive(root, entry, archive_path=archive_path)
    members = {row["source_id"]: row["mesh_member"] for row in index["assets"]}
    enriched = [{**row, "mesh_member": members[row["source_id"]], "archive": str(archive_path)}
                for row in samples]
    rows = extract_selected(root, index, enriched)
    atomic_json(output, rows)
    return rows


def prepare_batches(root, workers):
    selection = read_json(root / "selection.json")
    plan = read_json(root / "download_plan.json")
    split = read_json(root / "split.json")["splits"]
    (root / "category_inventory").mkdir(exist_ok=True)
    (root / "ready").mkdir(exist_ok=True)
    by_category = defaultdict(list)
    by_id = {row["asset_id"]: row for row in selection["samples"]}
    for row in selection["samples"]:
        by_category[row["category"]].append(row)
    entries = {Path(row["path"]).name.removesuffix(".tar.gz"): row for row in plan["archives"]}
    category_order = list(dict.fromkeys(by_id[asset]["category"] for batch in selection["batch_order"]
                                        for asset in split[batch]))
    inventory = {}
    all_inputs = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {category: pool.submit(acquire_category, root, category, by_category[category], entries[category])
                   for category in category_order}
        for batch in selection["batch_order"]:
            ids = split[batch]
            for category in {by_id[asset]["category"] for asset in ids}:
                for row in futures[category].result():
                    inventory[row["asset_id"]] = row
            write_jsonl(root / "inventory.jsonl", sorted(inventory.values(), key=lambda row: row["asset_id"]))
            path = prepare(root, batch, "y", dataset_name="omniobject3d-ood-v2",
                           render_protocol="omniobject3d-render-v1")
            inputs = [json.loads(line) for line in path.read_text().splitlines()]
            for sample in inputs:
                sample["split"] = "eval100"
                atomic_json(root / "samples" / sample["sample_id"] / "input.json", sample)
                all_inputs[sample["sample_id"]] = sample
            write_jsonl(path, inputs)
            atomic_json(root / (batch + ".manifest.json"), {
                "sha256": file_digest(path), "samples": len(inputs),
                "config_hash": inputs[0]["render_config_hash"]})
            atomic_json(root / "ready" / (batch + ".json"), {
                "batch": batch, "samples": len(inputs), "inputs": str(path),
                "inputs_sha256": file_digest(path), "selection_sha256": file_digest(root / "selection.json")})
            print(f"BATCH READY {batch} {len(inputs)} cumulative={len(all_inputs)}", flush=True)
    write_jsonl(root / "eval100.jsonl", [all_inputs[asset] for asset in split["eval100"]])
    atomic_json(root / "assets_complete.json", {
        "asset_count": len(all_inputs), "selection_sha256": file_digest(root / "selection.json"),
        "inventory_sha256": file_digest(root / "inventory.jsonl"),
        "inputs_sha256": file_digest(root / "eval100.jsonl")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=PROCESSED_ROOT / "omniobject3d/ood-v2")
    parser.add_argument("--stage", choices=("plan", "prepare"), required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    root = args.dataset.resolve()
    if not root.is_relative_to(PROCESSED_ROOT.resolve()) or args.workers < 1:
        parser.error("Expected a processed-data destination and positive worker count")
    if args.stage == "plan":
        freeze(root)
    else:
        prepare_batches(root, args.workers)


if __name__ == "__main__":
    main()

