"""Prepare independently versioned input cameras for the approved GSO/OOD ablation."""
import argparse
import copy
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
import trimesh

from evaluation.camera_ablation import (
    camera_match, crop_transform, fixed_crop_intrinsics, framed_camera,
    frozen_spatial_spec,
)
from evaluation.render import Rasterizer, load_mesh_parts
from wt.artifacts import save_npz
from wt.data import compute_object_crop
from wt.experiment import atomic_json, digest, file_digest, read_json
from wt.paths import PROCESSED_ROOT, REPO_ROOT


def prepare_asset(sample, inventory, destination, condition, renderer):
    old = Path(sample["evaluation_dir"])
    baseline_camera = read_json(old / "camera.json")
    with Image.open(sample["image"]) as image:
        baseline_rgba = np.array(image.convert("RGBA"))
    spatial = frozen_spatial_spec(baseline_rgba)
    config = {
        "version": "camera-ablation-v1", "condition": condition,
        "source_input_sha256": file_digest(old / "input.json"),
        "source_camera_sha256": file_digest(old / "camera.json"),
        "spatial": spatial if condition.startswith("B") else None,
        "sources": {name: file_digest(REPO_ROOT / name) for name in (
            "examples/prepare_camera_ablation.py", "evaluation/camera_ablation.py",
            "evaluation/render.py", "wt/data.py")},
    }
    signature = digest(config)
    entry = destination / "input.json"
    if entry.exists():
        previous = read_json(entry)
        if previous["render_config_hash"] != signature:
            raise ValueError(f"Prepared input changed: {destination}")
        for name, expected in previous["artifact_sha256"].items():
            if file_digest(destination / name) != expected:
                raise ValueError(f"Prepared artifact changed: {destination / name}")
        return previous
    destination.mkdir(parents=True, exist_ok=True)
    parts = load_mesh_parts(inventory[sample["asset_id"]]["mesh"])
    asset_transform = np.asarray(baseline_camera["T_asset_to_world"])
    for part in parts:
        part.apply_transform(asset_transform)
    camera = copy.deepcopy(baseline_camera)
    diagnostics = {}
    if condition == "A1":
        vertices = np.concatenate([part.vertices for part in parts])
        camera, diagnostics = framed_camera(vertices, baseline_camera)
    elif condition == "B1":
        camera["K"] = fixed_crop_intrinsics(baseline_camera, spatial).tolist()
        camera["horizontal_fov_degrees"] = float(np.rad2deg(
            2 * np.arctan(1024 / (2 * camera["K"][0][0]))))
    elif condition != "B0":
        raise ValueError(f"Unsupported condition {condition}")
    K = np.asarray(camera["K"])
    T = np.asarray(camera["T_world_to_camera"])
    if condition == "B0":
        rgba = baseline_rgba
        shutil.copy2(old / "input.png", destination / "input.png")
        shutil.copy2(old / "gt_depth_original.npz", destination / "gt_depth_original.npz")
    else:
        rgba, depth, mask, _ = renderer.render(parts, K, T, 1024)
        if not mask.any():
            raise ValueError("Empty input view")
        Image.fromarray(rgba).save(destination / "input.png")
        save_npz(destination / "gt_depth_original.npz", depth=depth, mask=mask)
    crop = spatial["wt_crop_y_x_side"] if condition.startswith("B") else list(compute_object_crop(rgba))
    cropped_K = crop_transform(crop) @ K
    _, depth, mask, normals = renderer.render(parts, cropped_K, T, 504, texture=False)
    save_npz(destination / "gt_depth.npz", depth=depth, mask=mask, K=cropped_K, normals=normals)
    if condition in ("A1", "B1"):
        diagnostics["intrinsic_match"] = camera_match(cropped_K)
        if not diagnostics["intrinsic_match"]["passed"]:
            raise ValueError(f"Target intrinsic calibration failed: {sample['sample_id']} {diagnostics}")
    foreground = rgba[..., 3] > 127
    rows, columns = np.where(foreground)
    diagnostics.update(
        foreground_pixels=int(foreground.sum()),
        longest_occupancy=float(max(np.ptp(rows) + 1, np.ptp(columns) + 1) / 1024),
        touches_canvas=bool(foreground[0].any() or foreground[-1].any()
                            or foreground[:, 0].any() or foreground[:, -1].any()),
    )
    for name in ("gt_world.ply", "gt_points.npz"):
        shutil.copy2(old / name, destination / name)
    mesh = trimesh.load(destination / "gt_world.ply", force="mesh", process=False)
    mesh.apply_transform(T)
    mesh.export(destination / "gt_camera.ply")
    camera.update(K_crop=cropped_K.tolist(), crop_y_x_side=list(map(int, crop)),
                  ablation_condition=condition, baseline_camera=str(old / "camera.json"))
    atomic_json(destination / "camera.json", camera)
    atomic_json(destination / "render_config.json", config)
    atomic_json(destination / "spatial.json", {
        "condition": condition, "frozen": condition.startswith("B"),
        "spatial": spatial, "diagnostics": diagnostics,
        "source_input_sha256": file_digest(Path(sample["image"])),
    })
    files = ("input.png", "gt_depth_original.npz", "gt_depth.npz", "gt_world.ply",
             "gt_camera.ply", "gt_points.npz", "camera.json", "render_config.json", "spatial.json")
    result = dict(sample, image=str(destination / "input.png"), evaluation_dir=str(destination),
                  dataset=sample["dataset"] + "-camera-" + condition,
                  ground_truth={"path": str(destination / "gt_camera.ply"),
                                "kind": "mesh", "frame": "camera_rdf"},
                  render_config_hash=signature,
                  artifact_sha256={name: file_digest(destination / name) for name in files},
                  camera_ablation={"condition": condition, "source": str(old),
                                   "spatial": str(destination / "spatial.json")})
    atomic_json(entry, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--condition", choices=("A1", "B0", "B1"), required=True)
    parser.add_argument("--split", default="eval100")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids-path", type=Path)
    parser.add_argument("--batch")
    args = parser.parse_args()
    destination = args.destination.resolve()
    if not destination.is_relative_to(PROCESSED_ROOT.resolve()):
        parser.error("Destination must be under project processed data")
    inputs = [json.loads(line) for line in (args.source / f"{args.split}.jsonl").read_text().splitlines()]
    full_inputs = inputs
    if args.ids_path:
        if not args.batch or args.limit:
            parser.error("--ids-path requires --batch and excludes --limit")
        selected = read_json(args.ids_path)
        if len(selected) != len(set(selected)):
            parser.error("Duplicate selected asset")
        inputs = [row for row in inputs if row["sample_id"] in set(selected)]
        if len(inputs) != len(selected):
            parser.error("Selected asset is outside source split")
    if args.limit:
        inputs = inputs[:args.limit]
    inventory = {row["asset_id"]: row for row in (
        json.loads(line) for line in (args.source / "inventory.jsonl").read_text().splitlines())}
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.source / "inventory.jsonl", destination / "inventory.jsonl")
    atomic_json(destination / "split.json", {"splits": {args.split: [row["sample_id"] for row in (full_inputs if args.batch else inputs)]}})
    renderer = Rasterizer()
    rows = []
    for sample in inputs:
        row = prepare_asset(sample, inventory, destination / "samples" / sample["sample_id"],
                            args.condition, renderer)
        rows.append(row)
        print(f"{args.condition} {len(rows)}/{len(inputs)} {sample['sample_id']}", flush=True)
    path = destination / f"{args.batch or args.split}.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    atomic_json(destination / (f"{args.batch}.ready.json" if args.batch else "complete.json"), {
        "status": "complete", "condition": args.condition, "assets": len(rows),
        "inputs_sha256": file_digest(path), "source": str(args.source)})


if __name__ == "__main__":
    main()
