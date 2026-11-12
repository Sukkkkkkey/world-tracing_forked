"""Evaluate frozen baseline candidates at decoded and exported stages."""
import argparse
import gc
import importlib.metadata
import json
from pathlib import Path
import time
import traceback

import numpy as np
import trimesh

from evaluation.baseline import load_stage_mesh, point_samples, register_shape, shape_metrics
from evaluation.visibility import gt_visibility, region_metrics, paired_export_geometry
from evaluation.render_artifacts import export_render_images, load_render_groups
from evaluation.geometry import chamfer, depth_metrics, surface_points, transform_points
from evaluation.multiview import compare_views, frame_metrics, prepare_surfels, render_views, sample_mesh
from examples.evaluate_multiview import Evaluator as MultiviewEvaluator
from examples.evaluate_multiview import result_lock, save_maps, valid_result
from examples.prepare_gso_inventory import asset_seed
from wt.artifacts import save_npz
from wt.experiment import atomic_json, digest, file_digest, read_json, run_directory
from wt.intrinsics import solve_intrinsics_from_xyz
from wt.paths import OUTPUT_ROOT, REPO_ROOT
from wt.textured_mesh.canon import CanonicalTransform, canon_inverse

SOURCES = ("evaluation/baseline.py", "examples/evaluate_baseline_v2.py",
           "wt/intrinsics.py", "wt/textured_mesh/canon.py",
           "evaluation/visibility.py", "evaluation/render_artifacts.py",
           "examples/summarize_baseline_v2.py")


def sliced_maps(maps, index):
    return {name: values[index] for name, values in maps.items()}


def input_camera(camera):
    return {**camera, "K": camera["K_crop"], "resolution": 504}


def render_groups(renderer, geometry, cameras, config, *, surfel=False):
    return {
        "input": render_views(renderer, geometry, cameras[:1], config, surfel=surfel),
        "multiview": render_views(renderer, geometry, cameras[1:], config, surfel=surfel),
    }


def save_render_groups(destination, name, groups):
    arrays = {f"{group}_{key}": value
              for group, maps in groups.items() for key, value in maps.items()}
    return save_maps(destination, name, arrays)


def summarize_render(maps, reference, config, lpips_model):
    prediction = sliced_maps(maps["input"], 0)
    truth = sliced_maps(reference["input"], 0)
    return {
        "input": frame_metrics(prediction, truth, config, lpips_model),
        "input_ssi": depth_metrics(prediction["depth"], truth["depth"],
                                   prediction["mask"], truth["mask"]),
        "multiview": compare_views(maps["multiview"], reference["multiview"], config, lpips_model),
    }


def wt_camera_diagnostics(xyz, mask, saved_intrinsics, dataset, evaluation_points):
    camera = read_json(dataset / "camera.json")
    with np.load(dataset / "gt_depth.npz", allow_pickle=False) as truth:
        depth = truth["depth"].astype(np.float64)
        gt_mask = truth["mask"]
        intrinsics = truth["K"].astype(np.float64)
    valid = mask & gt_mask & np.isfinite(xyz).all(axis=-1) & (xyz[..., 2] > 0)
    valid &= np.isfinite(depth) & (depth > 0)
    if valid.sum() < 10:
        return {"status": "failed", "reason": "Too few paired L0 pixels"}
    v, u = np.nonzero(valid)
    pixels = np.stack([u + .5, v + .5, np.ones(len(u))], axis=-1)
    predicted = xyz[valid].astype(np.float64)
    target = (pixels @ np.linalg.inv(intrinsics).T) * depth[valid, None]
    scale = float(np.sum(predicted * target) / np.sum(predicted * predicted))
    centered = predicted - predicted.mean(axis=0)
    variance = float(np.sum(centered * centered))
    if variance < 1e-12 or scale <= 0:
        return {"status": "failed", "reason": "Degenerate or nonpositive camera scale fit"}
    scale_translation = float(np.sum(centered * (target - target.mean(axis=0))) / variance)
    translation = target.mean(axis=0) - scale_translation * predicted.mean(axis=0)
    fitted, _ = solve_intrinsics_from_xyz(xyz, mask)
    projections = {}
    for name, matrix in (("gt", intrinsics), ("saved_default", saved_intrinsics), ("fitted", fitted)):
        if matrix is None:
            projections[name] = {"status": "failed"}
            continue
        projected = predicted @ matrix.T
        error = np.linalg.norm(projected[:, :2] / projected[:, 2, None] - pixels[:, :2], axis=-1)
        projections[name] = {"status": "complete", "K": np.asarray(matrix).tolist(),
                             "mean_pixels": float(error.mean()),
                             "p95_pixels": float(np.quantile(error, .95))}
    with np.load(dataset / "gt_points.npz", allow_pickle=False) as truth:
        gt_camera = transform_points(truth["evaluation"], np.asarray(camera["T_world_to_camera"]))
    return {
        "status": "complete", "paired_pixels": int(valid.sum()),
        "scale_about_camera_origin": scale, "scale_with_translation": scale_translation,
        "translation": translation.tolist(),
        "l0_xyz_rmse": float(np.sqrt(np.mean(np.sum((predicted - target) ** 2, axis=-1)))),
        "l0_scale_rmse": float(np.sqrt(np.mean(np.sum((scale * predicted - target) ** 2, axis=-1)))),
        "l0_scale_translation_rmse": float(np.sqrt(np.mean(np.sum(
            (scale_translation * predicted + translation - target) ** 2, axis=-1)))),
        "native_shape": chamfer(evaluation_points, gt_camera),
        "scale_only_shape": chamfer(evaluation_points * scale, gt_camera),
        "projections": projections,
    }


def rgb_metrics(renderer, lpips_model, mesh, camera, sample, reference_mask):
    import cv2
    from PIL import Image
    rgba, _, predicted_mask, _ = renderer.render(
        [mesh], camera["K"], camera["T_world_to_camera"], camera["resolution"],
        near=camera["near"], far=camera["far"], texture=True, normal_mode="face")
    source = Image.open(sample["image"]).convert("RGBA")
    y, x, side = camera["crop_y_x_side"]
    crop = np.asarray(source.crop((x, y, x + side, y + side)))
    reference = cv2.resize(crop[..., :3], (504, 504), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255
    prediction = rgba[..., :3].astype(np.float32) / 255
    prediction = np.where(predicted_mask[..., None], prediction, .5)
    reference = np.where(reference_mask[..., None], reference, .5)
    mse = float(np.mean((prediction.astype(float) - reference) ** 2))
    return {"status": "complete", "psnr": float(-10 * np.log10(max(mse, 1e-12))),
            "lpips": lpips_model(prediction * 2 - 1, reference * 2 - 1),
            "background": "neutral-gray-0.5", "lighting": "unlit-base-color",
            "reference": "cropped-input-rgb-with-rendered-gt-mask"}, {
                "prediction_rgb": prediction, "reference_rgb": reference,
                "prediction_mask": predicted_mask, "reference_mask": reference_mask}


class BaselineEvaluator:
    def __init__(self, config_path, *, save_multiview_renders=False):
        self.config = read_json(config_path)
        if save_multiview_renders:
            self.config["render_artifacts"]["save_multiview"] = True
        self.multiview = MultiviewEvaluator(REPO_ROOT / self.config["multiview_config"])
        self.visibility_environment = {
            "rtree": importlib.metadata.version("rtree"),
            "trimesh": importlib.metadata.version("trimesh"),
            "numpy": importlib.metadata.version("numpy"),
            "pillow": importlib.metadata.version("pillow"),
            "opencv-python": importlib.metadata.version("opencv-python"),
        }
        if self.visibility_environment["rtree"] != self.config["visibility"]["rtree_version"]:
            raise ValueError("Visibility dependency version differs from the frozen config")
        self.sources = {name: file_digest(REPO_ROOT / name) for name in SOURCES}
        self.revision = digest({"config": self.config, "sources": self.sources,
                                "multiview_revision": self.multiview.revision,
                                "visibility_environment": self.visibility_environment})[:20]
        self.root = OUTPUT_ROOT / self.config["output_root"] / self.revision
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_json(self.root / "profile.json", {
            "revision": self.revision, "config": self.config, "sources": self.sources,
            "visibility_environment": self.visibility_environment,
            "multiview_profile": str(self.multiview.root / "profile.json"),
            "selection": "GT-assisted full-shape CD, one seed per asset-method-stage",
        })
        source_directory = self.root / "sources"
        for name in SOURCES:
            destination = source_directory / name
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((REPO_ROOT / name).read_bytes())
        self.reference_key = None
        self.wt_parent_cache = {}
        self.index_updates = []

    def reference(self, sample):
        base_record, base_maps = self.multiview.reference(sample)
        dataset = Path(sample["evaluation_dir"])
        points_digest = file_digest(dataset / "gt_points.npz")
        if points_digest != sample["artifact_sha256"]["gt_points.npz"]:
            raise ValueError("Frozen GT evaluation samples changed")
        signature = digest({"base": base_record["signature"], "points": points_digest,
                            "revision": self.revision})
        if self.reference_key == signature:
            return self.cameras, self.reference_maps, self.reference_record
        camera = input_camera(read_json(dataset / "camera.json"))
        cameras = [camera, *base_record["cameras"]]
        destination = self.root / "gt" / sample["asset_id"] / signature[:20]
        with result_lock(destination):
            record = valid_result(destination, signature, status_key="numerical_status")
            if record is None:
                mesh = trimesh.load(dataset / "gt_world.ply", force="mesh", process=False)
                front = render_views(self.multiview.renderer, mesh, [camera], self.multiview.config)
                maps = {"input": front, "multiview": base_maps}
                with np.load(dataset / "gt_points.npz", allow_pickle=False) as truth:
                    visibility, visibility_arrays = gt_visibility(
                        mesh, truth["evaluation"], camera,
                        tolerance=self.config["visibility"]["tolerance"],
                        batch_size=self.config["visibility"]["batch_size"],
                        surface_tolerance=self.config["visibility"]["surface_tolerance"],
                        parallel_epsilon=self.config["visibility"]["parallel_epsilon"])
                surfels = prepare_surfels(
                    sample_mesh(mesh, sample["asset_id"], self.multiview.config), self.multiview.config)
                with np.load(Path(base_record["directory"]) / "surfel.npz", allow_pickle=False) as saved:
                    surfel_views = {name: saved[name] for name in saved.files}
                surfel_maps = {"input": render_views(self.multiview.renderer, surfels, [camera],
                                                   self.multiview.config, surfel=True),
                               "multiview": surfel_views}
                files = {
                    "geometry.npz": save_render_groups(destination, "geometry.npz", maps),
                    "surfel.npz": save_render_groups(destination, "surfel.npz", surfel_maps),
                    "visibility.npz": save_maps(destination, "visibility.npz", visibility_arrays),
                }
                record = {"signature": signature, "revision": self.revision,
                          "numerical_status": "complete", "files": files,
                          "source": str(Path(base_record["directory"]) / "result.json"),
                          "evaluation_points_sha256": points_digest, "cameras": cameras,
                          "visibility": visibility, "mesh_area": float(mesh.area),
                          "surfel_vs_native": summarize_render(
                              surfel_maps, maps, self.multiview.config, self.multiview.lpips)}
                atomic_json(destination / "result.json", record)
            else:
                maps = load_render_groups(destination / "geometry.npz")
                surfel_maps = load_render_groups(destination / "surfel.npz")
            with np.load(destination / "visibility.npz", allow_pickle=False) as saved:
                self.gt_labels = saved["labels"]
            record["artifacts"] = export_render_images(
                destination, {"native": maps, "surfel": surfel_maps}, maps, cameras,
                {"kind": "gt", "asset_id": sample["asset_id"], "revision": self.revision,
                 "source_arrays": record["files"]}, self.config["render_artifacts"],
                reference_only=True)
            record["status"] = "complete"
            atomic_json(destination / "result.json", record)
        record = dict(record, directory=str(destination))
        self.reference_key = signature
        self.cameras, self.reference_maps, self.reference_record = cameras, maps, record
        return cameras, maps, record

    def ensure_images(self, result, destination, reference, cameras):
        representations = {
            name: load_render_groups(destination / f"{name}.npz")
            for name in ("surfel", "native") if f"{name}.npz" in result["files"]}
        metadata = {key: result[key] for key in
                    ("sample_id", "method", "stage", "seed", "revision", "registration",
                     "sampling_seeds", "result_path")}
        metadata.update(
            source_arrays=result["files"],
            metrics_sha256=digest({key: result.get(key) for key in ("shape", "regions", "comparisons")}),
            gt_manifest=self.reference_record["artifacts"])
        return export_render_images(destination, representations, reference, cameras,
                                    metadata, self.config["render_artifacts"])

    def evaluate(self, directory, stage, experiment_name):
        directory = Path(directory)
        state = read_json(directory / "run.json")
        sample_path = directory.parents[2] / "input.json"
        sample = read_json(sample_path)
        if state["status"] != "complete" or state["input_sha256"] != sample["sha256"]:
            raise ValueError("Inference state or input provenance is inconsistent")
        if state["method"] == "wt" and stage != "points":
            raise ValueError("WT has a points stage")
        artifact = {"points": "prediction.npz", "decoded": "decoded_mesh.ply", "glb": "mesh.glb"}[stage]
        watched = [directory / name for name in ("run.json", "config.json", artifact)]
        if stage != "points":
            watched.append(directory / "mesh.json")
        watched.extend([sample_path, Path(sample["image"])])
        dataset = Path(sample["evaluation_dir"])
        watched.extend(dataset / name for name in ("gt_points.npz", "gt_depth.npz"))
        if state["method"] == "wt_trellis2":
            parent_metadata = directory / "wt_parent.json"
            parent = (directory / read_json(parent_metadata)["path"]).resolve()
            watched.extend([parent_metadata, parent])
        sources = {str(path): file_digest(path) for path in watched}
        if sources[str(Path(sample["image"]))] != sample["sha256"]:
            raise ValueError("Frozen input image changed")
        for name in ("gt_points.npz", "gt_depth.npz"):
            if sources[str(dataset / name)] != sample["artifact_sha256"][name]:
                raise ValueError(f"Frozen GT artifact changed: {name}")
        before = [(path.stat().st_size, path.stat().st_mtime_ns) for path in watched]
        decoded_record = None
        if stage == "glb":
            decoded_record = self.evaluate(directory, "decoded", experiment_name)
            sources[decoded_record["result_path"]] = file_digest(Path(decoded_record["result_path"]))
        cameras, reference, gt_record = self.reference(sample)
        signature = digest({"inputs": sources, "reference": gt_record["signature"],
                            "stage": stage, "revision": self.revision})
        destination = (self.root / experiment_name / "samples" / sample["sample_id"] /
                       state["method"] / state["config_id"] / f"seed-{state['seed']:04d}" /
                       stage / signature[:20])
        with result_lock(destination):
            previous = valid_result(destination, signature, status_key="numerical_status")
            if previous is not None:
                previous["artifacts"] = self.ensure_images(previous, destination, reference, cameras)
                previous["status"] = "complete"
                previous.pop("error", None)
                atomic_json(destination / "result.json", previous)
                self.index_updates.append(previous)
                return previous
            result = {"revision": self.revision, "signature": signature,
                      "sample_id": sample["sample_id"], "method": state["method"],
                      "config_id": state["config_id"], "seed": state["seed"], "stage": stage,
                      "source_directory": str(directory), "inputs": sources,
                      "result_path": str(destination / "result.json"), "files": {},
                      "reference": str(Path(gt_record["directory"]) / "result.json"),
                      "protocol_version": self.config["protocol_version"]}
            started = time.monotonic()
            try:
                result.update(self.compute(directory, state, stage, sample, cameras, reference,
                                           destination, decoded_record))
                result["numerical_status"] = "complete"
                atomic_json(destination / "result.json", result)
                result["artifacts"] = self.ensure_images(result, destination, reference, cameras)
                after = [(path.stat().st_size, path.stat().st_mtime_ns) for path in watched]
                if before != after:
                    raise RuntimeError("Evaluation inputs changed during execution")
                result["status"] = "complete"
            except Exception:
                result.update(status="failed", error=traceback.format_exc())
            result["seconds"] = time.monotonic() - started
            atomic_json(destination / "result.json", result)
        gc.collect()
        self.index_updates.append(result)
        return result

    def failed_candidate(self, candidate, experiment_name, error, phase):
        directory = Path(candidate["source_directory"])
        sources = {str(directory / name): file_digest(directory / name)
                   for name in ("run.json", "terminal_failure.json")
                   if (directory / name).is_file()}
        signature = digest({"candidate": candidate, "sources": sources,
                            "revision": self.revision, "phase": phase, "error": error})
        destination = (self.root / experiment_name / "samples" / candidate["sample_id"] /
                       candidate["method"] / candidate["config_id"] /
                       f"seed-{candidate['seed']:04d}" / candidate["stage"] / signature[:20])
        result = {**candidate, "revision": self.revision, "signature": signature,
                  "status": "failed", "failure_phase": phase, "error": error,
                  "inputs": sources, "result_path": str(destination / "result.json"),
                  "files": {}}
        atomic_json(destination / "result.json", result)
        return result

    def compute(self, directory, state, stage, sample, cameras, reference, destination,
                decoded_record=None):
        dataset = Path(sample["evaluation_dir"])
        with np.load(dataset / "gt_points.npz", allow_pickle=False) as truth:
            gt_registration, gt_evaluation = truth["registration"], truth["evaluation"]
        registration_seed = asset_seed("pred_reg", sample["asset_id"])
        evaluation_seed = asset_seed("pred_eval", sample["asset_id"])
        mesh = None
        geometry = {}
        if stage == "points":
            with np.load(directory / "prediction.npz", allow_pickle=False) as prediction:
                xyz, mask = prediction["xyz"], prediction["mask"].astype(bool)
                saved_intrinsics = prediction["intrinsics"]
            points, registration, evaluation = point_samples(
                xyz[mask], registration_seed, evaluation_seed)
        else:
            mesh = load_stage_mesh(directory, stage)
            registration = surface_points(mesh, 10000, registration_seed)
            evaluation = surface_points(mesh, 100000, evaluation_seed)
            points = sample_mesh(mesh, sample["asset_id"], self.multiview.config)
            geometry = {"vertices": len(mesh.vertices), "faces": len(mesh.faces),
                        "native_area": float(mesh.area), "source_bytes": (directory /
                        ("decoded_mesh.ply" if stage == "decoded" else "mesh.glb")).stat().st_size}
        matrix, registration_info = register_shape(registration, gt_registration[:len(registration)], self.config["registration_workers"])
        aligned = transform_points(evaluation, matrix)
        shape, forward, backward = shape_metrics(aligned, gt_evaluation, return_distances=True)
        regions, distances = region_metrics(aligned, gt_evaluation, self.gt_labels)
        distances.update(full_pred_to_gt=forward, full_gt_to_pred=backward)
        sampled_path = destination / "sampled_points.npz"
        save_npz(sampled_path, registration=registration, evaluation=evaluation)
        files = {"sampled_points.npz": file_digest(sampled_path),
                 "distances.npz": save_maps(destination, "distances.npz", distances)}
        result = {"shape": shape, "regions": regions,
                  "visibility": self.reference_record["visibility"], "registration": {"matrix": matrix.tolist(), **registration_info},
                  "sampling_seeds": {"registration": registration_seed, "evaluation": evaluation_seed},
                  "geometry": geometry, "files": files}
        if stage == "glb":
            result["export_pair"] = {"status": "failed", "reason": "Decoded evaluation unavailable"}
            if decoded_record and decoded_record.get("numerical_status") == "complete":
                pair, pair_distances = paired_export_geometry(
                    evaluation, gt_evaluation, self.gt_labels, decoded_record,
                    geometry["native_area"], self.reference_record["mesh_area"])
                files["export_pair_distances.npz"] = save_maps(
                    destination, "export_pair_distances.npz", pair_distances)
                result["export_pair"] = {
                    **pair, "status": "complete", "seed": state["seed"],
                    "decoded_result": decoded_record["result_path"],
                    "decoded_result_sha256": file_digest(Path(decoded_record["result_path"]))}
        if stage == "points":
            result["camera_diagnostics"] = wt_camera_diagnostics(
                xyz[0], mask[0], saved_intrinsics, dataset, evaluation)
        elif state["method"] == "wt_trellis2":
            metadata = read_json(directory / "mesh.json")
            transform = CanonicalTransform(**metadata["canonical_transform"])
            native_points = canon_inverse(evaluation, transform)
            gt_camera = transform_points(gt_evaluation, np.asarray(cameras[0]["T_world_to_camera"]))
            result["native_camera_shape"] = chamfer(native_points, gt_camera)
            parent_metadata = read_json(directory / "wt_parent.json")
            parent_path = (directory / parent_metadata["path"]).resolve()
            if file_digest(parent_path) != parent_metadata["sha256"]:
                raise ValueError("Hybrid WT parent has changed")
            cache_key = (parent_metadata["sha256"], sample["asset_id"])
            if cache_key not in self.wt_parent_cache:
                with np.load(parent_path, allow_pickle=False) as parent:
                    parent_points = parent["xyz"][parent["mask"].astype(bool)]
                _, parent_registration, parent_evaluation = point_samples(
                    parent_points, registration_seed, evaluation_seed)
                parent_matrix, _ = register_shape(parent_registration, gt_registration[:len(parent_registration)], self.config["registration_workers"])
                self.wt_parent_cache[cache_key] = {
                    "path": str(parent_path), "sha256": parent_metadata["sha256"],
                    "shape": shape_metrics(transform_points(parent_evaluation, parent_matrix), gt_evaluation),
                    "matrix": parent_matrix.tolist(), "settings": parent_metadata["settings"]}
            result["wt_parent"] = self.wt_parent_cache[cache_key]
        points = transform_points(points, matrix)
        comparisons = {}
        if mesh is not None:
            scale = float(np.cbrt(np.linalg.det(matrix[:3, :3])))
            gt_mesh = trimesh.load(dataset / "gt_world.ply", force="mesh", process=False)
            geometry.update(sim3_scale=scale, aligned_area=geometry["native_area"] * scale ** 2,
                            area_gt_ratio=geometry["native_area"] * scale ** 2 / float(gt_mesh.area))
            mesh.vertices = transform_points(mesh.vertices, matrix)
            native = render_groups(self.multiview.renderer, mesh, cameras, self.multiview.config)
            comparisons["native"] = summarize_render(
                native, reference, self.multiview.config, self.multiview.lpips)
            files["native.npz"] = save_render_groups(destination, "native.npz", native)
            if stage == "glb" and self.config["input_view"]["rgb_glb"]:
                try:
                    result["input_rgb"], rgb_arrays = rgb_metrics(
                        self.multiview.renderer, self.multiview.lpips, mesh, cameras[0],
                        sample, reference["input"]["mask"][0])
                    files["input_rgb.npz"] = save_maps(destination, "input_rgb.npz", rgb_arrays)
                except Exception:
                    result["input_rgb"] = {"status": "failed", "error": traceback.format_exc()}
            del mesh
        surfels = prepare_surfels(points, self.multiview.config)
        rendered = render_groups(self.multiview.renderer, surfels, cameras,
                                self.multiview.config, surfel=True)
        comparisons["surfel"] = summarize_render(
            rendered, reference, self.multiview.config, self.multiview.lpips)
        if stage != "points":
            comparisons["surfel_vs_native"] = summarize_render(
                rendered, native, self.multiview.config, self.multiview.lpips)
        files["surfel.npz"] = save_render_groups(destination, "surfel.npz", rendered)
        result.update(comparisons=comparisons, surfel_diagnostics=surfels["diagnostics"])
        return result


def candidate_plan(experiment, source_experiment, config, seeds, sample_ids=None):
    inputs = {path.parent.name: path for path in sorted((source_experiment / "samples").glob("*/input.json"))}
    selected = sorted(inputs) if sample_ids is None else sample_ids
    if len(set(selected)) != len(selected) or set(selected) - set(inputs):
        raise ValueError("Sample subset must contain distinct frozen sample IDs")
    plan = []
    for sample in selected:
        for seed in seeds:
            root = source_experiment if seed == config["report_single_seed"] else experiment
            for method, configuration in config["methods"].items():
                directory = run_directory(root, sample, method, configuration, seed)
                stages = ["points"] if method == "wt" else config["mesh_stages"]
                for stage in stages:
                    plan.append({"sample_id": sample, "method": method, "config_id": configuration,
                                 "seed": seed, "stage": stage, "source_directory": str(directory)})
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--source-experiment", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs/baseline_v2.json")
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--sample-ids", nargs="+")
    parser.add_argument("--save-multiview-renders", action="store_true",
                        help="Also export all 30 multi-view PNG sets; all views always retain metrics and NPZ")
    parser.add_argument("--calibration", action="store_true",
                        help="Evaluate only the selected single-seed calibration budget")
    args = parser.parse_args()
    config = read_json(args.config)
    seeds = config["seeds"] if args.seeds is None else args.seeds
    if len(set(seeds)) != len(seeds) or set(seeds) - set(config["seeds"]):
        parser.error("Requested seeds must be distinct members of the frozen budget")
    if args.calibration and seeds != [config["report_single_seed"]]:
        parser.error("Calibration requires the fixed single seed")
    evaluator = BaselineEvaluator(args.config, save_multiview_renders=args.save_multiview_renders)
    config = evaluator.config
    plan = candidate_plan(args.experiment, args.source_experiment, config, seeds, args.sample_ids)
    output = evaluator.root / args.experiment.name
    complete_plan = plan if args.calibration else candidate_plan(
        args.experiment, args.source_experiment, config, config["seeds"])
    mode = "calibration" if args.calibration else "formal"
    plan_record = {"config": config, "selected_seeds": seeds, "candidates": complete_plan, "mode": mode}
    if (output / "plan.json").exists():
        old = read_json(output / "plan.json")
        if old["candidates"] != complete_plan or old.get("mode", "formal") != mode:
            raise ValueError("Existing evaluation has a different frozen plan")
    atomic_json(output / "plan.json", plan_record)
    print(json.dumps({"revision": evaluator.revision, "evaluation": str(output),
                      "planned": len(plan), "mode": mode}), flush=True)
    index_path = output / "index.json"
    previous = read_json(index_path)["results"] if index_path.exists() else []
    results = {(row["sample_id"], row["method"], row["seed"], row["stage"]): row for row in previous}
    atomic_json(index_path, {"revision": evaluator.revision, "config": config,
                            "results": list(results.values())})
    for position, candidate in enumerate(plan):
        directory = Path(candidate["source_directory"])
        state_path = directory / "run.json"
        state = read_json(state_path) if state_path.exists() else {}
        terminal_path = directory / "terminal_failure.json"
        if state.get("status") != "complete":
            if not terminal_path.is_file():
                continue
            terminal = read_json(terminal_path)
            if terminal.get("run_sha256") != (file_digest(state_path) if state_path.exists() else None):
                raise ValueError(f"Terminal inference state changed: {directory}")
            result = evaluator.failed_candidate(candidate, args.experiment.name, terminal, "inference")
        else:
            try:
                result = evaluator.evaluate(directory, candidate["stage"], args.experiment.name)
            except Exception:
                result = evaluator.failed_candidate(
                    candidate, args.experiment.name, traceback.format_exc(), "evaluation")
        for updated in [*evaluator.index_updates, result]:
            key = (updated["sample_id"], updated["method"], updated["seed"], updated["stage"])
            results[key] = {
                **{name: updated[name] for name in
                   ("sample_id", "method", "config_id", "seed", "stage", "source_directory", "status", "result_path")},
                "result_sha256": file_digest(Path(updated["result_path"]))}
        evaluator.index_updates.clear()
        atomic_json(index_path, {"revision": evaluator.revision, "config": config,
                                "results": list(results.values())})
        print(f"{position + 1}/{len(plan)} {candidate['sample_id']} {candidate['method']} "
              f"seed={candidate['seed']} {candidate['stage']} {result['status']}", flush=True)
    failures = [row["result_path"] for row in results.values() if row["status"] == "failed"]
    atomic_json(output / "last_evaluation.json", {"failures": failures, "index": str(index_path),
                                               "evaluated": len(results), "planned": len(plan)})
    from examples.summarize_baseline_v2 import markdown, summary, write_render_index
    report = summary(output)
    atomic_json(output / "summary.json", report)
    (output / "summary.md").write_text(markdown(report))
    write_render_index(output, report)
    atomic_json(args.experiment / "baseline_evaluation.json", {
        "revision": evaluator.revision, "directory": str(output),
        "index_sha256": file_digest(index_path), "summary": str(output / "summary.json")})
    evaluation_failures = [path for path in failures
                           if read_json(Path(path)).get("failure_phase") != "inference"]
    return int(bool(evaluation_failures))


if __name__ == "__main__":
    raise SystemExit(main())
