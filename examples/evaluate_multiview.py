"""Evaluate frozen GSO runs with native-mesh and shared-surfel geometry metrics."""
import argparse
from collections import defaultdict
from contextlib import contextmanager
import fcntl
import gc
import importlib.metadata
import json
from pathlib import Path
import time
import traceback
import zipfile

import numpy as np
import trimesh

from evaluation.geometry import transform_points
from evaluation.multiview import (
    NormalLPIPS, cameras, compare_views, multiview_metric_units, prepare_surfels, render_views, sample_mesh,
)
from evaluation.render import Rasterizer
from wt.artifacts import atomic_artifact, save_npz
from wt.experiment import atomic_json, digest, file_digest, read_json
from wt.paths import CACHE_ROOT, OUTPUT_ROOT, REPO_ROOT, WEIGHTS_ROOT, configure_cache_paths

SOURCES = (
    "examples/evaluate_multiview.py", "evaluation/multiview.py", "evaluation/render.py",
    "evaluation/render_artifacts.py",
    "evaluation/geometry.py", "examples/prepare_gso_inventory.py",
    "wt/artifacts.py", "wt/experiment.py", "wt/paths.py",
    "scripts/setup_multiview.py", "requirements.recovery.txt", "requirements.lock.txt",
)


@contextmanager
def result_lock(path):
    lock_path = CACHE_ROOT / "multiview_locks" / (digest(str(path.resolve())) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def valid_result(directory, signature, *, status_key="status"):
    path = directory / "result.json"
    if not path.exists():
        return None
    try:
        record = read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(record.get("files"), dict):
        return None
    if record.get("signature") != signature or record.get(status_key) != "complete":
        return None
    for name, expected in record["files"].items():
        artifact = directory / name
        if not artifact.is_file() or file_digest(artifact) != expected:
            return None
    return record


def load_maps(path):
    with np.load(path, allow_pickle=False) as arrays:
        return {name: arrays[name] for name in arrays.files}


def save_maps(directory, name, maps):
    path = directory / name
    save_npz(path, **maps)
    return file_digest(path)


def verify_similarity(matrix):
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("Invalid registration matrix")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-9):
        raise ValueError("Invalid homogeneous row")
    singular = np.linalg.svd(matrix[:3, :3], compute_uv=False)
    if singular[-1] <= 0 or np.linalg.det(matrix[:3, :3]) <= 0:
        raise ValueError("Registration must be a positive-scale proper similarity")
    if not np.allclose(singular, singular.mean(), rtol=1e-5, atol=1e-9):
        raise ValueError("Registration has nonuniform scale")
    return matrix


class Evaluator:
    def __init__(self, config_path):
        configure_cache_paths()
        self.config = read_json(config_path)
        fixed = {"lpips_net": "alex", "lpips_version": "0.1",
                 "reference": "native_gt_face_normals", "normal_orientation": "toward_camera"}
        for name, expected in fixed.items():
            if self.config[name] != expected:
                raise ValueError(f"Unsupported multiview setting: {name}={self.config[name]}")
        if self.config["normal_max_neighbors"] < self.config["normal_min_neighbors"]:
            raise ValueError("Normal neighborhood bounds are inconsistent")
        self.source_hashes = {name: file_digest(REPO_ROOT / name) for name in SOURCES}
        self.environment = read_json(CACHE_ROOT / "multiview_environment.json")
        installed = {name: importlib.metadata.version(name) for name in self.environment["versions"]}
        if installed != self.environment["versions"]:
            raise ValueError("Environment changed; rerun python -m scripts.setup_multiview")
        expected = {
            WEIGHTS_ROOT / "torch/hub/checkpoints/alexnet-owt-7be5be79.pth": self.config["alexnet_sha256"],
            Path(self.environment["lpips_linear"]["path"]): self.config["lpips_linear_sha256"],
        }
        for path, checksum in expected.items():
            if file_digest(path) != checksum:
                raise ValueError(f"LPIPS weight checksum mismatch: {path}")
        self.revision = digest({
            "config": self.config, "sources": self.source_hashes, "environment": self.environment,
        })[:20]
        self.root = OUTPUT_ROOT / "evaluation/multiview" / self.revision
        self.root.mkdir(parents=True, exist_ok=True)
        archive = self.root / "sources.zip"
        if not archive.exists():
            with atomic_artifact(archive) as temporary:
                with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                    for name in SOURCES:
                        if file_digest(REPO_ROOT / name) != self.source_hashes[name]:
                            raise RuntimeError("Evaluator source changed during initialization")
                        bundle.write(REPO_ROOT / name, name)
        atomic_json(self.root / "profile.json", {
            "revision": self.revision, "config": self.config, "sources": self.source_hashes,
            "environment": self.environment, "sources_archive_sha256": file_digest(archive),
        })
        import torch
        torch.set_num_threads(4)
        self.renderer = Rasterizer()
        self.lpips = NormalLPIPS()
        self.gt_key = self.gt_record = self.gt_maps = None

    def reference(self, sample):
        dataset = Path(sample["evaluation_dir"])
        files = {name: file_digest(dataset / name) for name in ("gt_world.ply", "camera.json")}
        for name, checksum in files.items():
            if sample["artifact_sha256"][name] != checksum:
                raise ValueError(f"GT provenance mismatch: {name}")
        signature = digest({"asset": sample["asset_id"], "files": files, "revision": self.revision})
        if self.gt_key == signature:
            return self.gt_record, self.gt_maps
        directory = self.root / "gt" / sample["asset_id"] / signature[:20]
        with result_lock(directory):
            result = valid_result(directory, signature)
            if result is None:
                started = time.monotonic()
                mesh = trimesh.load(dataset / "gt_world.ply", process=False, force="mesh")
                views = cameras(read_json(dataset / "camera.json"), self.config)
                native = render_views(self.renderer, mesh, views, self.config)
                surfels = prepare_surfels(sample_mesh(mesh, sample["asset_id"], self.config), self.config)
                rendered = render_views(self.renderer, surfels, views, self.config, surfel=True)
                hashes = {
                    "native.npz": save_maps(directory, "native.npz", native),
                    "surfel.npz": save_maps(directory, "surfel.npz", rendered),
                }
                result = {
                    "status": "complete", "signature": signature, "revision": self.revision,
                    "asset_id": sample["asset_id"], "inputs": files, "cameras": views, "files": hashes,
                    "surfel_diagnostics": surfels["diagnostics"],
                    "surfel_vs_native": compare_views(rendered, native, self.config, self.lpips),
                    "seconds": time.monotonic() - started,
                }
                atomic_json(directory / "result.json", result)
            else:
                native = load_maps(directory / "native.npz")
        result = dict(result, directory=str(directory))
        self.gt_key, self.gt_record, self.gt_maps = signature, result, native
        return result, native

    def evaluate_run(self, directory, *, publish=True):
        started = time.monotonic()
        state = read_json(directory / "run.json")
        if state["status"] != "complete":
            raise ValueError("Inference is incomplete")
        sample_path = directory.parents[2] / "input.json"
        sample = read_json(sample_path)
        if sample["sample_id"] != state["sample_id"] or sample["sha256"] != state["input_sha256"]:
            raise ValueError("Run metadata and sample provenance disagree")
        legacy = read_json(directory / "metrics.json")
        if legacy.get("source_run_hash") != file_digest(directory / "run.json"):
            raise ValueError("Registration evaluation does not match current run metadata")
        if legacy.get("evaluation_status") != "complete":
            raise ValueError("Registration evaluation is incomplete")
        matrix = verify_similarity(read_json(directory / "registration.json")["matrix"])
        prediction_name = "prediction.npz" if state["method"] == "wt" else "decoded_mesh.ply"
        inputs = {name: file_digest(directory / name)
                  for name in ("run.json", "registration.json", "metrics.json", prediction_name)}
        inputs["input.json"] = file_digest(sample_path)
        watched = [directory / name for name in inputs if name != "input.json"] + [sample_path]
        before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in watched]
        gt, reference = self.reference(sample)
        signature = digest({"inputs": inputs, "gt": gt["signature"], "revision": self.revision})
        destination = directory / "multiview" / self.revision / signature[:20]
        with result_lock(directory / "multiview"):
            result = valid_result(destination, signature)
            if result is None:
                records, artifacts = {}, {}
                mesh = None
                if state["method"] == "wt":
                    with np.load(directory / prediction_name, allow_pickle=False) as data:
                        points = data["xyz"][data["mask"].astype(bool)]
                    points = np.unique(points[np.isfinite(points).all(axis=1)], axis=0)
                    points = transform_points(points, matrix)
                else:
                    mesh = trimesh.load(directory / prediction_name, process=False, force="mesh")
                    mesh.vertices = transform_points(mesh.vertices, matrix)
                    native = render_views(self.renderer, mesh, gt["cameras"], self.config)
                    records["native"] = compare_views(native, reference, self.config, self.lpips)
                    artifacts["native.npz"] = save_maps(destination, "native.npz", native)
                    points = sample_mesh(mesh, sample["asset_id"], self.config)
                    del mesh
                surfels = prepare_surfels(points, self.config)
                rendered = render_views(self.renderer, surfels, gt["cameras"], self.config, surfel=True)
                records["surfel"] = compare_views(rendered, reference, self.config, self.lpips)
                artifacts["surfel.npz"] = save_maps(destination, "surfel.npz", rendered)
                if state["method"] != "wt":
                    records["surfel_vs_native"] = compare_views(rendered, native, self.config, self.lpips)
                rows = []
                for route, protocol in (("native", self.config["mesh_protocol"]),
                                        ("surfel", self.config["surfel_protocol"])):
                    if route in records:
                        rows.extend(dict(row, protocol_id=protocol) for row in records[route]["metrics"])
                    else:
                        rows.extend({
                            "protocol_id": protocol, "metric": name, "value": None, "unit": unit,
                            "status": "N/A", "reason": "WT provides raw points", "valid_views": 0, "total_views": len(gt["cameras"]),
                        } for name, unit in multiview_metric_units(self.config).items())
                result = {
                    "status": "complete", "signature": signature, "revision": self.revision,
                    "run_directory": str(directory), "sample_id": sample["sample_id"], "method": state["method"],
                    "config_id": state["config_id"], "config_hash": state["config_hash"],
                    "seed": state["seed"], "inputs": inputs,
                    "gt_signature": gt["signature"], "gt_directory": gt["directory"],
                    "registration_matrix": matrix.tolist(), "files": artifacts, "metrics": rows,
                    "comparisons": records, "surfel_diagnostics": surfels["diagnostics"],
                    "seconds": time.monotonic() - started,
                }
                after = [(p.stat().st_size, p.stat().st_mtime_ns) for p in watched]
                if before != after:
                    raise RuntimeError("Evaluation input changed during rendering")
                atomic_json(destination / "result.json", result)
            if publish:
                atomic_json(directory / "multiview.json", {
                    "revision": self.revision, "result": str((destination / "result.json").relative_to(directory)),
                    "sha256": file_digest(destination / "result.json"),
                })
        gc.collect()
        return result, destination / "result.json"


def summary_run(path):
    state = read_json(path)
    configuration_path = path.parent / "config.json"
    configuration = read_json(configuration_path)
    fingerprint = (configuration if state["method"] == "pixal3d"
                   else {"config": configuration["parameters"], "provenance": configuration["provenance"]})
    if digest(fingerprint) != state["config_hash"]:
        raise ValueError(f"Configuration provenance mismatch: {configuration_path}")
    return dict(state, parameter_hash=digest(configuration["parameters"]),
                configuration_path=str(configuration_path),
                configuration_sha256=file_digest(configuration_path))


def save_summary(path, summary, planned_runs):
    sources = (*SOURCES, "examples/summarize_multiview.py")
    hashes = {name: file_digest(REPO_ROOT / name) for name in sources}
    archive = path.parent.parent / "aggregation_sources" / (digest(hashes)[:20] + ".zip")
    if not archive.exists():
        with atomic_artifact(archive) as temporary:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for name in sources:
                    bundle.write(REPO_ROOT / name, name)
    summary["aggregation"] = {
        "grouping": "method-config_id-seed-parameters",
        "sources": hashes, "archive": str(archive), "archive_sha256": file_digest(archive),
        "configurations": {r["configuration_path"]: r["configuration_sha256"] for r in planned_runs},
    }
    atomic_json(path, summary)


def summarize(records, planned_runs, config):
    """Retain every registered run in denominators, including complete failures."""
    def identity(record):
        return tuple(record[field] for field in ("sample_id", "method", "config_id", "seed"))

    parameters = {identity(record): record["parameter_hash"] for record in planned_runs}

    def key(record):
        return (record["method"], record["config_id"], record["seed"], parameters[identity(record)])

    groups, totals, source_hashes = defaultdict(list), defaultdict(int), defaultdict(set)
    for record in planned_runs:
        totals[key(record)] += 1
        groups[key(record)]
        source_hashes[key(record)].add(record["config_hash"])
    for record in records:
        groups[key(record)].append(record)
    rows, common, common_rows, paired = [], {}, [], []
    protocols = [config["mesh_protocol"], config["surfel_protocol"]]
    for protocol in protocols:
        applicable = {k: items for k, items in groups.items()
                      if not (protocol == config["mesh_protocol"] and k[0] == "wt")}
        sets = [{item["sample_id"] for item in items
                 if all(m["status"] == "complete" for m in item["metrics"] if m["protocol_id"] == protocol)}
                for items in applicable.values()]
        common[protocol] = sorted(set.intersection(*sets)) if sets else []
        for group, items in sorted(groups.items()):
            metadata = dict(zip(("method", "config_id", "seed", "parameter_hash"), group))
            metadata["source_config_hashes"] = sorted(source_hashes[group])
            for name in multiview_metric_units(config):
                selected = [(item["sample_id"], m) for item in items for m in item["metrics"]
                            if (m["protocol_id"], m["metric"]) == (protocol, name)]
                values = [m["value"] for _, m in selected if m["status"] == "complete"]
                na = totals[group] if protocol == config["mesh_protocol"] and group[0] == "wt" else 0
                rows.append({
                    **metadata, "protocol_id": protocol, "metric": name,
                    "mean": float(np.mean(values)) if values else None,
                    "std": float(np.std(values)) if values else None, "valid": len(values),
                    "N/A": na, "failed": totals[group] - len(values) - na, "total": totals[group],
                })
                if group in applicable:
                    matched = [m["value"] for asset, m in selected
                               if asset in common[protocol] and m["status"] == "complete"]
                    common_rows.append({
                        **metadata, "protocol_id": protocol, "metric": name, "valid": len(matched),
                        "mean": float(np.mean(matched)) if matched else None,
                    })
    for group, items in sorted(groups.items()):
        if group[0] == "wt":
            continue
        meshes = [item for item in items if "native" in item["comparisons"]]
        for name in multiview_metric_units(config):
            differences, image_errors = [], []
            for item in meshes:
                values = {route: {m["metric"]: m for m in comparison["metrics"]}
                          for route, comparison in item["comparisons"].items()}
                native, surfel = values["native"][name], values["surfel"][name]
                if native["status"] == surfel["status"] == "complete":
                    differences.append(surfel["value"] - native["value"])
                own = values["surfel_vs_native"][name]
                if own["status"] == "complete":
                    image_errors.append(own["value"])
            paired.append({
                **dict(zip(("method", "config_id", "seed", "parameter_hash"), group)),
                "source_config_hashes": sorted(source_hashes[group]),
                "metric": name, "valid_pairs": len(differences), "total": totals[group],
                "mean_surfel_minus_native": float(np.mean(differences)) if differences else None,
                "std_surfel_minus_native": float(np.std(differences)) if differences else None,
                "mean_self_render_metric": float(np.mean(image_errors)) if image_errors else None,
                "self_render_valid": len(image_errors),
            })
    return {
        "expected_runs": len(planned_runs), "complete_runs": len(records),
        "failed_metrics": sum(row["failed"] for row in rows), "summary": rows,
        "paired_mesh_comparisons": paired, "common_valid_assets": common,
        "common_valid_summary": common_rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs/multiview.json")
    parser.add_argument("--sample")
    parser.add_argument("--method")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-publish", action="store_true")
    args = parser.parse_args()
    evaluator = Evaluator(args.config)
    runs = sorted(args.experiment.glob("samples/*/*/*/seed-*/run.json"))
    runs = [path for path in runs if (not args.sample or path.parents[3].name == args.sample)
            and (not args.method or read_json(path)["method"] == args.method)]
    if args.limit:
        runs = runs[:args.limit]
    if not runs:
        raise ValueError("No matching runs")
    print(json.dumps({"revision": evaluator.revision, "runs": len(runs)}), flush=True)
    planned_runs = [summary_run(path) for path in runs]
    records, results, errors = [], [], []
    destination = evaluator.root / args.experiment.name
    for index, path in enumerate(runs, 1):
        try:
            result, result_path = evaluator.evaluate_run(path.parent, publish=not args.no_publish)
            records.append(result)
            results.append({"path": str(result_path), "sha256": file_digest(result_path)})
            print(json.dumps({"done": index, "total": len(runs), "sample": result["sample_id"],
                              "method": result["method"], "seconds": result["seconds"]}), flush=True)
        except Exception:
            error = {"run": str(path.parent), "traceback": traceback.format_exc()}
            errors.append(error)
            print(json.dumps(error), flush=True)
        atomic_json(destination / "progress.json", {"done": index, "total": len(runs), "errors": errors})
    summary = summarize(records, planned_runs, evaluator.config)
    summary.update(revision=evaluator.revision, results=results, errors=errors,
                   selection={"sample": args.sample, "method": args.method, "limit": args.limit},
                   status="complete" if len(records) == len(runs) and not summary["failed_metrics"] else "failed")
    output = destination / ("summary.json" if not any((args.sample, args.method, args.limit)) else "selected_summary.json")
    save_summary(output, summary, planned_runs)
    print(json.dumps({"summary": str(output), "status": summary["status"]}), flush=True)
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
