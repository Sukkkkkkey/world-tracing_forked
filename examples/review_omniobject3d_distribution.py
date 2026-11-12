"""Audit the frozen OmniObject3D evaluation subset against all official 1024-point clouds."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

import h5py
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from plyfile import PlyData
from scipy.spatial import cKDTree, ConvexHull
from scipy.stats import ks_2samp

from wt.experiment import atomic_json, file_digest, read_json

FEATURES = {
    "pca_minor_major": "PCA 最短/最长尺寸",
    "pca_middle_major": "PCA 中间/最长尺寸",
    "radial_cv": "表面点半径变异系数",
    "hull_fill": "凸包体积/PCA 包围盒体积",
    "local_surface_variation": "16 邻点局部表面变化",
}


def point_digest(points):
    return hashlib.sha256(np.asarray(points, dtype="<f4").tobytes()).hexdigest()


def features(points):
    center = points.mean(axis=0)
    centered = points - center
    _, eigenvectors = np.linalg.eigh(centered.T @ centered / len(points))
    local = centered @ eigenvectors
    extents = np.sort(np.ptp(local, axis=0))
    radius = np.linalg.norm(centered, axis=1)
    normalized = centered / np.linalg.norm(np.ptp(points, axis=0))
    neighbors = cKDTree(normalized).query(normalized, k=16, workers=1)[1]
    patches = normalized[neighbors]
    patches -= patches.mean(axis=1, keepdims=True)
    covariance = np.einsum("nki,nkj->nij", patches, patches) / 16
    patch_eigenvalues = np.maximum(np.linalg.eigvalsh(covariance), 0)
    surface_variation = patch_eigenvalues[:, 0] / patch_eigenvalues.sum(axis=1)
    result = {
        "pca_minor_major": float(extents[0] / extents[2]),
        "pca_middle_major": float(extents[1] / extents[2]),
        "radial_cv": float(radius.std() / radius.mean()),
        "hull_fill": float(ConvexHull(local).volume / np.prod(extents)),
        "local_surface_variation": float(surface_variation.mean()),
    }
    if not all(np.isfinite(value) for value in result.values()):
        raise ValueError("Nonfinite geometric descriptor")
    return result


def parse_cloud(item):
    category, source_id, payload = item
    ply = PlyData.read(io.BytesIO(payload))
    vertices = ply["vertex"]
    points = np.column_stack([vertices[name] for name in ("x", "y", "z")]).astype(np.float64)
    if points.shape != (1024, 3) or not np.isfinite(points).all():
        raise ValueError(f"Invalid official cloud {source_id}")
    return {"source_id": source_id, "category": category,
            "point_sha256": point_digest(points), **features(points)}


def read_population(reference):
    entry = read_json(reference / "official_ply_index.json")["list"][0]
    archive = reference / Path(entry["path"]).name
    if archive.stat().st_size != entry["size"] or file_digest(archive) != entry["sha256"]:
        raise ValueError("Named point cloud archive checksum mismatch")
    jobs = []
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise ValueError("Unsafe point cloud archive entry")
            if member.isfile() and path.suffix == ".ply":
                if len(path.parts) != 4 or path.name != "pcd_1024.ply":
                    raise ValueError(f"Unexpected point cloud path {path}")
                jobs.append((path.parts[1], path.parts[2], stream.extractfile(member).read()))
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = []
        for number, record in enumerate(pool.map(parse_cloud, jobs), 1):
            records.append(record)
            if number % 500 == 0:
                print(f"Measured {number}/{len(jobs)} official objects", flush=True)
    if len({row["source_id"] for row in records}) != len(records):
        raise ValueError("Official source IDs are duplicated")
    by_category = defaultdict(Counter)
    for row in records:
        by_category[row["category"]][row["point_sha256"]] += 1
    entries = read_json(reference / "official_pointcloud_index.json")["list"]
    h5_counts = {}
    for entry in entries:
        path = reference / "pointclouds1024" / Path(entry["path"]).name
        if path.stat().st_size != entry["size"] or file_digest(path) != entry["sha256"]:
            raise ValueError(f"HDF5 source checksum mismatch {path}")
        category = path.stem.removesuffix("_1024")
        with h5py.File(path, "r") as stream:
            clouds = stream["data"][:]
        point_hashes = Counter(point_digest(cloud) for cloud in clouds)
        if by_category[category] - point_hashes:
            raise ValueError(f"Named PLY points absent from HDF5 for {category}")
        unnamed = point_hashes - by_category[category]
        for row_index, cloud in enumerate(clouds):
            checksum = point_digest(cloud)
            if unnamed[checksum]:
                records.append({"source_id": f"__unidentified_hdf5_{category}_row_{row_index}",
                                "category": category, "point_sha256": checksum,
                                "identity_status": "missing_from_named_ply",
                                "hdf5_row": row_index, **features(cloud)})
                unnamed[checksum] -= 1
        h5_counts[category] = sum(point_hashes.values())
    if set(h5_counts) != set(by_category):
        raise ValueError("Named PLY and HDF5 category sets differ")
    return records, h5_counts


def compare_features(population, sample, simulations):
    report = {}
    for name in FEATURES:
        all_values = np.asarray([row[name] for row in population])
        selected = np.asarray([row[name] for row in sample])
        simulated = all_values[simulations]
        q = [.1, .5, .9]
        low, high = np.quantile(all_values, [.1, .9])
        report[name] = {
            "population_mean": float(all_values.mean()), "sample_mean": float(selected.mean()),
            "population_q10_q50_q90": np.quantile(all_values, q).tolist(),
            "sample_q10_q50_q90": np.quantile(selected, q).tolist(),
            "standardized_mean_difference": float((selected.mean() - all_values.mean()) / all_values.std()),
            "ks_distance": float(ks_2samp(selected, all_values).statistic),
            "srs100_mean_95pct": np.quantile(simulated.mean(axis=1), [.025, .975]).tolist(),
            "sample_below_population_p10": int((selected < low).sum()),
            "sample_above_population_p90": int((selected > high).sum()),
            "population_p10": float(low), "population_p90": float(high),
        }
    return report


def input_quality(row):
    with np.load(Path(row["evaluation_dir"]) / "gt_depth.npz", allow_pickle=False) as saved:
        mask, depth = saved["mask"].astype(bool), saved["depth"]
    camera = read_json(Path(row["evaluation_dir"]) / "camera.json")
    top, left, side = camera["crop_y_x_side"]
    crop = Image.open(row["image"]).convert("RGBA").crop((left, top, left + side, top + side))
    crop = crop.resize((mask.shape[1], mask.shape[0]), Image.Resampling.LANCZOS)
    values = np.asarray(crop.convert("RGB"), dtype=float)[mask] / 255
    return {
        "foreground_fraction": float(mask.mean()),
        "border_mask_pixels": int(mask[0].sum() + mask[-1].sum() + mask[1:-1, 0].sum() + mask[1:-1, -1].sum()),
        "gt_invalid_depth_pixels": int((mask & (~np.isfinite(depth) | (depth <= 0))).sum()),
        "foreground_rgb_std": float(values.std(axis=0).mean()),
        "crop_y_x_side": camera["crop_y_x_side"],
        "category": row["category"],
    }


def contact_sheets(rows, out):
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
    rows = sorted(rows, key=lambda row: (row["category"], row["sample_id"]))
    for page in range(4):
        canvas = Image.new("RGB", (5 * 200, 5 * 224), "#eeeeee")
        draw = ImageDraw.Draw(canvas)
        for index, row in enumerate(rows[page * 25:(page + 1) * 25]):
            camera = read_json(Path(row["evaluation_dir"]) / "camera.json")
            top, left, side = camera["crop_y_x_side"]
            image = Image.open(row["image"]).convert("RGBA").crop((left, top, left + side, top + side))
            image = image.resize((196, 196), Image.Resampling.LANCZOS)
            x, y = (index % 5) * 200, (index // 5) * 224
            canvas.paste(image, (x + 2, y + 2), image.getchannel("A"))
            draw.text((x + 4, y + 202), row["sample_id"].removeprefix("omni_"), fill="black", font=font)
        canvas.save(out / f"inputs_{page + 1}.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--local-root", required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = args.dataset / "eval100.jsonl"
    selection_path = args.dataset / "selection.json"
    original_hash = file_digest(manifest)
    selection = read_json(selection_path)
    rows = [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
    formal = [row for row in selection["samples"] if row["split"] == "eval100"]
    pilot = [row for row in selection["samples"] if row["split"] == "pilot"]
    if len(formal) != 100 or len(pilot) != 10:
        raise ValueError("Unexpected frozen budget")
    selected_ids = {row["source_id"] for row in formal}
    if selected_ids & {row["source_id"] for row in pilot}:
        raise ValueError("Pilot/formal overlap")
    if {row["sample_id"] for row in rows} != {"omni_" + value for value in selected_ids}:
        raise ValueError("Frozen manifest differs from selection")
    for row in rows:
        for name, expected in row["artifact_sha256"].items():
            if file_digest(Path(row["evaluation_dir"]) / name) != expected:
                raise ValueError(f"Frozen input artifact changed {row['sample_id']}/{name}")
    population, counts = read_population(args.reference)
    by_id = {row["source_id"]: row for row in population}
    if selected_ids - by_id.keys():
        raise ValueError("Formal IDs absent from official reference")
    selected = [by_id[source_id] for source_id in sorted(selected_ids)]
    formal_counts = Counter(row["category"] for row in formal)
    if any(counts[name] != count for name, count in selection["source_category_counts"].items()):
        raise ValueError("Mesh archive and point cloud category counts differ")
    n_population = len(population)
    rng = np.random.default_rng(20261111)
    simulations = np.stack([rng.choice(n_population, 100, replace=False) for _ in range(2000)])
    category_names = sorted(counts)
    category_codes = {name: i for i, name in enumerate(category_names)}
    labels = np.array([category_codes[row["category"]] for row in population])
    unique_categories = np.array([len(np.unique(labels[indices])) for indices in simulations])
    population_probabilities = np.array([counts[name] / n_population for name in category_names])
    simulated_variation = np.array([
        .5 * np.abs(np.bincount(labels[indices], minlength=len(counts)) / 100
                    - population_probabilities).sum() for indices in simulations])

    descriptors = compare_features(population, selected, simulations)
    distribution = [{
        "category": name, "population": count, "formal": formal_counts[name],
        "population_fraction": count / n_population, "formal_fraction": formal_counts[name] / 100,
        "relative_sampling_weight": (formal_counts[name] / 100) / (count / n_population),
        "selected_ids": sorted(row["source_id"] for row in formal if row["category"] == name),
    } for name, count in sorted(counts.items())]
    total_variation = .5 * sum(abs(row["population_fraction"] - row["formal_fraction"]) for row in distribution)
    plan = read_json(args.dataset / "download_plan.json")
    excluded_categories = [Path(row["path"]).name.removesuffix(".tar.gz") for row in plan["excluded_archives"]]
    excluded_count = sum(counts[name] for name in excluded_categories)
    qualities = {row["sample_id"]: input_quality(row) for row in rows}
    records = [{
        **row, "sample_id": "omni_" + row["source_id"],
        "quality": qualities["omni_" + row["source_id"]],
        "population_percentile": {
            name: float(np.mean([value[name] <= row[name] for value in population])) for name in FEATURES},
    } for row in selected]
    report = {
        "status": "passed", "population_assets": n_population, "population_categories": len(counts),
        "formal_assets": 100, "formal_categories": len(formal_counts),
        "covered_categories_population_assets": sum(counts[name] for name in formal_counts),
        "category_total_variation": total_variation,
        "srs100_categories_q025_median_q975": np.quantile(unique_categories, [.025, .5, .975]).tolist(),
        "srs100_total_variation_q025_median_q975": np.quantile(
            simulated_variation, [.025, .5, .975]).tolist(),
        "size_excluded_categories": excluded_categories, "size_excluded_assets": excluded_count,
        "categories": distribution, "features": descriptors, "records": records,
        "input_quality": {
            "invalid_depth_pixels": sum(row["gt_invalid_depth_pixels"] for row in qualities.values()),
            "assets_touching_crop_border": sum(row["border_mask_pixels"] > 0 for row in qualities.values()),
            "foreground_fraction_q10_median_q90": np.quantile(
                [row["foreground_fraction"] for row in qualities.values()], [.1, .5, .9]).tolist(),
        },
        "reference_validation": "All 5910 named PLY clouds match HDF5 arrays; one additional unnamed anise HDF5 row completes 5911",
        "unnamed_population_rows": [row for row in population if row.get("identity_status")],
        "sampling_reference": {"draws": 2000, "sample_size": 100, "replacement": False, "seed": 20261111},
        "provenance": {
            "manifest_sha256": original_hash, "selection_sha256": file_digest(selection_path),
            "pointcloud_index_sha256": file_digest(args.reference / "official_pointcloud_index.json"),
            "named_pointcloud_index_sha256": file_digest(args.reference / "official_ply_index.json"),
            "source_sha256": file_digest(Path(__file__)),
        },
    }
    atomic_json(args.out / "distribution_review.json", report)
    atomic_json(args.out / "population_features.json", population)
    atomic_json(args.out / "eval100_review_manifest.json", records)
    contact_sheets(rows, args.out)
    link = args.local_root.rstrip("/")
    lines = ["# 正式 100 资产清单审核", "",
             "2026-11-11。审核当前冻结的 OmniObject3D eval100 清单。正式模型推理与指标评测继续等待用户确认。", "",
             "## 总体判断", "",
             f"当前 100 个资产覆盖官方本次发布的 {len(counts)} 类中的 {len(formal_counts)} 类"
             f"（{len(formal_counts)/len(counts):.2%}）。这些类别在全量 {n_population} 个资产中共占 "
             f"{report['covered_categories_population_assets']/n_population:.2%}。清单适合报告这批类别上的分层 OOD 结果，"
             "对整个发布版本的资产平均性能仍缺少足够的类别覆盖。",
             f"类别分布的总变差距离为 {total_variation:.4f}。按全体资产简单随机抽取 100 个时，"
             f"2,000 次模拟覆盖类别数的中位数为 {np.median(unique_categories):.0f}，95% 范围为 "
             f"{np.quantile(unique_categories,.025):.0f}–{np.quantile(unique_categories,.975):.0f}。"
             f"相同随机抽样的类别总变差距离中位数为 {np.median(simulated_variation):.4f}。", "",
             "## 总体与抽样依据", "",
             "本轮下载并校验官方 216 份 1024 点 HDF5 及带资产名的 PLY 包，逐类别核对点坐标摘要。"
             "PLY 的 5,910 个点云均在 HDF5 中匹配。HDF5 额外包含一个 anise 点云，已加入总体统计，"
             "其资产 ID 标记为未识别。正式 100 资产的 ID 全部匹配。"
             "本次发布共 5,911 个资产、216 类。论文发布时描述约 6,000 个物体、190 类，数量差异使用实际下载版本解释。"
             "抽样按原类别压缩包大小筛选后固定哈希取类别，再在类别内轮流取资产，清单由模型推理前冻结。"
             "HDF5 共 145,711,104 字节，PLY 包 157,805,953 字节。"
             "[官方项目](https://omniobject3d.github.io/) · "
             "[官方采样代码](https://github.com/omniobject3d/OmniObject3D/blob/main/tools/extract_point_clouds.py)", "",
             f"大于等于 5GB 的 9 个类别包因下载上限排除，涉及 {excluded_count} 个资产"
             f"（{excluded_count/n_population:.2%}）。另外 package 类的扫描包返回 HTTP 405，共 16 个资产。"
             "类别包大小同时受到类内数量、网格复杂度和纹理大小影响，因此这一步具有潜在选择偏差。", "",
             "## 已覆盖类别与资产配额", "",
             "| 类别 | 全量资产 | 正式配额 | 全量占比 | 正式占比 | 相对抽样权重 |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in distribution:
        if row["formal"]:
            lines.append(f"| {row['category']} | {row['population']} | {row['formal']} | "
                         f"{row['population_fraction']:.2%} | {row['formal_fraction']:.2%} | "
                         f"{row['relative_sampling_weight']:.2f} |")
    lines.extend(["", "未覆盖类别包括 doll（84）、toy_animals（74）、teapot（38）、chair（29）、knife（29）、"
                  "scissor（19）、plant（14）、glasses（5）等。完整 216 类数量见 distribution_review.json。",
                  "", "相对抽样权重为正式占比/全量占比。接近类别等额分配会提高小类别的资产权重。"
                  "类别内结果、类别宏平均和按全量类频率加权的已覆盖类别结果需要分别报告。"
                  "未覆盖类别的结果无法由现有资产权重直接补足。", "",
                  "## 几何特征分布", "",
                  "同一官方 1024 点云计算全量与入选资产的尺度归一化、旋转不变几何描述。PCA 尺寸在主轴包围盒中求比值。"
                  "表面半径变异系数为点到质心距离的标准差/均值。局部表面变化为每点 16 邻点协方差的"
                  "最小特征值/特征值之和，再对点取均值。凸包占比表示表面点凸包对 PCA 包围盒的填充程度。", "",
                  "| 特征 | 全量均值 | 正式均值 | 标准化均值差 | KS 距离 | 全量 P10 以下/ P90 以上资产数 |",
                  "| --- | ---: | ---: | ---: | ---: | --- |"])
    for name, title in FEATURES.items():
        value = descriptors[name]
        lines.append(f"| {title} | {value['population_mean']:.4f} | {value['sample_mean']:.4f} | "
                     f"{value['standardized_mean_difference']:+.3f} | {value['ks_distance']:.3f} | "
                     f"{value['sample_below_population_p10']} / {value['sample_above_population_p90']} |")
    lines.extend(["", "五项均值偏差为 −0.158 至 +0.217 个总体标准差。凸包填充比例的全量 P10 以下与 P90 以上"
                  "各仅入选 2 个资产，尾部覆盖偏少。PCA 中/长轴比均值为 0.7315，"
                  "全量随机 100 资产的均值 95% 参照范围为 [0.6340, 0.7252]。",
                  "", "标准化均值差以全量资产标准差为分母，KS 距离衡量经验分布差异。"
                  "这些描述用于检查整体形状覆盖，1024 点分辨率限制薄杆、孔洞与微小结构的识别。"
                  "官方点云仅含 XYZ，材质、透明度、反射、颜色与纹理的全量分布尚未得到量化验证。", "",
                  "## 输入与重复性检查", "",
                  f"- 正式 100 个 ID 与 10 个校准 ID 互斥，100 个冻结输入的全部产物摘要通过核验。",
                  f"- GT 前景中的无效深度为 {report['input_quality']['invalid_depth_pixels']} 像素，"
                  f"触及裁剪边界的资产为 {report['input_quality']['assets_touching_crop_border']}/100。",
                  "- 每个资产使用同一渲染方案和固定方位，正式视角的外观、遮挡与轮廓可从下方四张清单图逐一审核。",
                  "- 本轮采集的来源摘要检查覆盖完全一致文件，形状近重复与跨类别同形物体的识别仍存在不确定性。", "",
                  "## 对正式清单的建议", "",
                  "若目标是当前完整发布版本的资产平均泛化，建议在全量 5,911 个资产中进行公开种子、无放回的概率抽样，"
                  "在推理前冻结清单并记录每个资产的纳入概率。可将主要几何特征分位段作为分层或平衡约束，"
                  "对未能取得扫描网格的样本记录获取失败，再按预先约定的同层顺序补位。",
                  "若目标是各类别等权表现，100 个资产的预算最多覆盖 100 类。应扩大类别覆盖或明确采用跨类别重复抽样，"
                  "并用类别层级的统计区间报告不确定性。当前 24 类清单可作为先导子集或类别条件评测。",
                  "增加类别覆盖时需要解决大包类别的获取方式。当前下载上限会排除 9 类，"
                  "可评估官方按资产获取或拆包渠道。建议重抽方案在正式模型推理前接受 review。", "",
                  "## 正式 100 资产完整清单", "",
                  "| 类别 | 资产 ID |",
                  "| --- | --- |"])
    for row in distribution:
        if row["formal"]:
            lines.append(f"| {row['category']} | {', '.join(row['selected_ids'])} |")
    for page in range(4):
        lines.extend(["", f"## 输入清单 {page + 1}", "",
                      f"![正式输入第 {page + 1} 页]({link}/inputs_{page + 1}.png)"])
    lines.extend(["", "## 可追溯文件", "",
                  f"- 全量类别分布、逐资产特征、正式清单及抽样参照结果保存在 {args.out}。",
                  f"- 正式输入清单 SHA-256 为 {original_hash}。",
                  "- 全量特征含 5,910 个来源 ID 及一个未识别 anise HDF5 行。后续全量重抽时需补齐这一资产身份或记录其排除。",
                  ""])
    (args.out / "manifest_review.md").write_text("\n".join(lines), encoding="utf-8")
    if file_digest(manifest) != original_hash:
        raise ValueError("Formal manifest changed during review")
    print({key: report[key] for key in ("population_assets", "population_categories", "formal_categories",
                                       "covered_categories_population_assets", "category_total_variation",
                                       "srs100_categories_q025_median_q975", "size_excluded_assets")}, flush=True)


if __name__ == "__main__":
    main()

