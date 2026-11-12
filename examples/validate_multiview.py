"""Calibrate the multiview protocol on P0 with source-linked image panels."""
import argparse
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw
import trimesh

from evaluation.geometry import transform_points
from evaluation.multiview import compare_views, prepare_surfels, render_views, sample_mesh
from examples.evaluate_multiview import Evaluator, load_maps
from wt.experiment import atomic_json, read_json, file_digest
from wt.paths import REPO_ROOT


def panel(destination, columns):
    """Four camera rows, with paired normal and depth images for every representation."""
    size = 256
    names = list(columns)
    image = Image.new("RGB", (len(names) * size * 2, 4 * (size + 28) + 35), "white")
    draw = ImageDraw.Draw(image)
    foreground = [maps["depth"][maps["mask"]] for maps in columns.values()]
    positive = np.concatenate([values for values in foreground if len(values)])
    lower, upper = np.quantile(positive, [.01, .99])
    for index, (name, maps) in enumerate(columns.items()):
        draw.text((index * size * 2 + 8, 8), name + " / normals + depth", fill="black")
        for view in range(4):
            normal = np.clip((maps["normals"][view] + 1) * 127.5, 0, 255).astype(np.uint8)
            normal[~maps["normal_valid"][view]] = 128
            depth = np.clip((maps["depth"][view] - lower) / max(upper - lower, 1e-9), 0, 1)
            shade = np.asarray(depth * 255, dtype=np.uint8)
            depth_image = np.stack([shade] * 3, axis=-1)
            depth_image[~maps["mask"][view]] = 255
            top = 35 + view * (size + 28)
            draw.text((index * size * 2 + 8, top), f"view {view}", fill="black")
            image.paste(Image.fromarray(normal).resize((size, size)), (index * size * 2, top + 24))
            image.paste(Image.fromarray(depth_image).resize((size, size)), (index * size * 2 + size, top + 24))
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)



def calibrate_predictions(evaluator, experiment, sample_ids):
    records = []
    output = evaluator.root / "p0_calibration/predictions"
    for asset in sample_ids:
        sample = read_json(experiment / "samples" / asset / "input.json")
        gt, reference = evaluator.reference(sample)
        for run_path in sorted((experiment / "samples" / asset).glob("*/*/seed-*/run.json")):
            directory = run_path.parent
            state = read_json(run_path)
            pointer = read_json(directory / "multiview.json")
            nominal_path = directory / pointer["result"]
            nominal_record = read_json(nominal_path)
            if file_digest(nominal_path) != pointer["sha256"]:
                raise ValueError("Prediction result checksum mismatch")
            nominal = load_maps(nominal_path.parent / "surfel.npz")
            matrix = np.asarray(read_json(directory / "registration.json")["matrix"])
            mesh = None
            if state["method"] == "wt":
                with np.load(directory / "prediction.npz", allow_pickle=False) as data:
                    points = data["xyz"][data["mask"].astype(bool)]
                points = np.unique(points[np.isfinite(points).all(axis=1)], axis=0)
                points = transform_points(points, matrix)
                changes = []
            else:
                mesh = trimesh.load(directory / "decoded_mesh.ply", process=False, force="mesh")
                mesh.vertices = transform_points(mesh.vertices, matrix)
                changes = [
                    ("double_samples", {"mesh_sample_count": evaluator.config["mesh_sample_count"] * 2}),
                    ("quadruple_samples", {"mesh_sample_count": evaluator.config["mesh_sample_count"] * 4}),
                ]
            changes += [
                ("smaller_radius", {"surfel_radius": evaluator.config["voxel_size"]}),
                ("larger_radius", {"surfel_radius": evaluator.config["voxel_size"] * 2}),
            ]
            variants = {}
            for label, override in changes:
                config = dict(evaluator.config, **override)
                if mesh is not None:
                    points = sample_mesh(mesh, asset, config)
                surfels = prepare_surfels(points, config)
                rendered = render_views(evaluator.renderer, surfels, gt["cameras"], config, surfel=True)
                variants[label] = {
                    "changes": override, "surfel_diagnostics": surfels["diagnostics"],
                    "vs_gt": compare_views(rendered, reference, config, evaluator.lpips),
                    "vs_nominal": compare_views(rendered, nominal, config, evaluator.lpips),
                }
                if label == "double_samples" and asset == "Schleich_Hereford_Bull":
                    panel(output / asset / state["method"] / state["config_id"] / "sampling.png",
                          {"GT native": reference, "nominal": nominal, "double samples": rendered})
            record = {
                "sample_id": asset, "method": state["method"], "config_id": state["config_id"],
                "source_result": str(nominal_path), "source_sha256": file_digest(nominal_path),
                "nominal": nominal_record["comparisons"]["surfel"], "variants": variants,
            }
            atomic_json(output / asset / state["method"] / state["config_id"] / "calibration.json", record)
            records.append(record)
            print(asset, state["method"], state["config_id"], "prediction calibrated", flush=True)
    atomic_json(output / "summary.json", {
        "status": "complete", "revision": evaluator.revision, "records": records,
        "validator_sha256": file_digest(Path(__file__)),
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs/multiview.json")
    parser.add_argument("--prediction-samples", nargs="+")
    args = parser.parse_args()
    evaluator = Evaluator(args.config)
    if args.prediction_samples:
        calibrate_predictions(evaluator, args.experiment, args.prediction_samples)
        return
    output = evaluator.root / "p0_calibration"
    records = []
    for path in sorted(args.experiment.glob("samples/*/input.json")):
        sample = read_json(path)
        asset = sample["asset_id"]
        gt, native = evaluator.reference(sample)
        nominal = load_maps(Path(gt["directory"]) / "surfel.npz")
        self_comparison = compare_views(native, native, evaluator.config, evaluator.lpips)
        self_values = {row["metric"]: row["value"] for row in self_comparison["metrics"]}
        for name in ("depth_mae", "depth_rmse", "normal_mean_angle", "normal_mse", "normal_lpips"):
            if self_values[name] is None or abs(self_values[name]) > 1e-6:
                raise ValueError(f"Self-comparison failed: {asset}, {name}, {self_values[name]}")
        mesh = trimesh.load(Path(sample["evaluation_dir"]) / "gt_world.ply", process=False, force="mesh")
        variants = {}
        for label, changes in (
            ("double_samples", {"mesh_sample_count": evaluator.config["mesh_sample_count"] * 2}),
            ("smaller_radius", {"surfel_radius": evaluator.config["voxel_size"]}),
            ("larger_radius", {"surfel_radius": evaluator.config["voxel_size"] * 2}),
        ):
            started = time.monotonic()
            config = dict(evaluator.config, **changes)
            surfels = prepare_surfels(sample_mesh(mesh, asset, config), config)
            rendered = render_views(evaluator.renderer, surfels, gt["cameras"], config, surfel=True)
            variants[label] = {
                "changes": changes, "surfel_diagnostics": surfels["diagnostics"],
                "vs_native": compare_views(rendered, native, config, evaluator.lpips),
                "vs_nominal": compare_views(rendered, nominal, config, evaluator.lpips),
                "seconds": time.monotonic() - started,
            }
        record = {
            "asset_id": asset, "gt_signature": gt["signature"],
            "self_comparison": self_comparison, "nominal": gt["surfel_vs_native"],
            "variants": variants,
        }
        atomic_json(output / asset / "calibration.json", record)
        panel(output / asset / "gt.png", {"GT native": native, "GT surfel": nominal})
        records.append(record)
        print(asset, "calibrated", flush=True)
    summary = {"revision": evaluator.revision, "assets": len(records), "records": records,
               "validator_sha256": file_digest(Path(__file__)), "status": "complete"}
    atomic_json(output / "summary.json", summary)
    print(output / "summary.json", flush=True)


if __name__ == "__main__":
    main()
