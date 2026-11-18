"""Plan, run, or evaluate the Hybrid pilot; GPU work requires --execute-gpu."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
import fcntl
import os
from pathlib import Path
import time
import traceback

from wt.experiment import SCHEMA_VERSION, atomic_json, digest, file_digest, read_json
from wt.hybrid_ablation import (assert_camera_idle, build_plan, evaluation_candidates,
                               resolved_job, save_plan, validate_plan, validate_sources, validate_backend_provenance)


def completed_job(directory, config_hash, input_hash):
    path = directory / "run.json"
    if not path.exists():
        if directory.exists() and any(directory.iterdir()):
            raise ValueError(f"Untracked partial output; use a new run root: {directory}")
        return False
    state = read_json(path)
    if state.get("config_hash") != config_hash or state.get("input_sha256") != input_hash:
        raise ValueError(f"Existing ablation identity changed: {directory}")
    if state.get("status") != "complete":
        raise ValueError(f"Prior incomplete/failed output preserved: {directory}")
    for relative in ("config.json", "wt_parent.json", "../../../input.json"):
        checksum = state.get("provenance_sha256", {}).get(relative)
        if not checksum or file_digest(directory / relative) != checksum:
            raise ValueError(f"Completed ablation provenance changed: {directory / relative}")
    for artifact in state["artifacts"].values():
        path = directory / artifact["path"]
        if not artifact.get("sha256") or file_digest(path) != artifact["sha256"]:
            raise ValueError(f"Completed ablation artifact changed: {path}")
        if artifact.get("metadata"):
            metadata = directory / artifact["metadata"]
            if file_digest(metadata) != artifact.get("metadata_sha256"):
                raise ValueError(f"Completed ablation metadata changed: {metadata}")
    return True


def execute_plan(plan, backend_factory=None, idle_check=assert_camera_idle):
    """Serial mesh-only execution. Injectable backend is used by CPU smoke tests."""
    root = validate_plan(plan)
    validate_sources(plan)
    idle_check()
    if backend_factory is None:
        os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("No visible CUDA device; plan/check remain CPU-only")
        from wt.hybrid_ablation_backend import HybridAblationBackend
        from wt.paths import WEIGHTS_ROOT
        backend_factory = lambda: HybridAblationBackend(
            None, WEIGHTS_ROOT / "local-pipelines/TRELLIS.2")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".hybrid.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / "plan.json").exists() and read_json(root / "plan.json") != plan:
            raise ValueError("Existing output root belongs to another frozen plan")
        backend = backend_factory()
        for source in plan["sources"].values():
            validate_backend_provenance(source, backend.provenance)
        pending = []
        # Validate every destination before loading models or writing outputs.
        for row in plan["jobs"]:
            if row["strategy"] == "fill":
                continue
            job = resolved_job(plan, row)
            identity = digest(dict(parameters=job["parameters"], strategy=job["strategy"],
                source_pins=job["pins"], transform=job["canonical_transform"],
                provenance=backend.provenance, executor_sha256=file_digest(Path(__file__))))
            directory = Path(job["destination"])
            if not completed_job(directory, identity, job["input"]["sha256"]):
                pending.append((job, directory, identity))
        if not pending:
            return 0
        save_plan(root / "plan.json", plan)
        failures = 0
        try:
            idle_check()
            backend.load_trellis(include_stage1=False, modes={"1024_cascade"})
            for job, directory, identity in pending:
                idle_check()
                # Recheck this parent's pins in case a long-running plan's inputs changed.
                validate_sources({"sources": {job["source_key"]: job}})
                experiment = Path(job["experiment_root"])
                header = dict(schema_version=SCHEMA_VERSION, experiment_id=experiment.name)
                save_plan(experiment / "experiment.json", header)
                save_plan(experiment / "samples" / job["sample_id"] / "input.json", job["input"])
                directory.mkdir(parents=True, exist_ok=True)
                atomic_json(directory / "config.json", dict(
                    parameters=job["parameters"], provenance=backend.provenance,
                    hybrid_ablation=dict(strategy=job["strategy"], condition=job["condition"],
                        preprocessing=job["preprocessing"], source=job["source_directory"],
                        source_pins=job["pins"], plan_hash=plan["plan_hash"])))
                parent = Path(job["parent_directory"])
                atomic_json(directory / "wt_parent.json", dict(job["parent_reference"],
                    path=os.path.relpath(parent / "prediction.npz", directory)))
                state = dict(schema_version=SCHEMA_VERSION, sample_id=job["sample_id"],
                    method="wt_trellis2", config_id=job["config_id"], seed=42,
                    config_hash=identity, input_sha256=job["input"]["sha256"],
                    provenance_sha256={name: file_digest(directory / name) for name in
                        ("config.json", "wt_parent.json", "../../../input.json")})
                atomic_json(directory / "run.json", dict(state, status="running"))
                started = time.monotonic()
                try:
                    backend.configure_job(job)
                    with (directory / "run.log").open("w") as log, redirect_stdout(log), redirect_stderr(log):
                        artifacts = backend.generate_mesh(
                            Path(job["input"]["image"]), job["parameters"], 42, directory, parent)
                    if not {"mesh", "decoded_mesh"} <= set(artifacts):
                        raise ValueError("Both decoded mesh and GLB are required")
                    for artifact in artifacts.values():
                        artifact["sha256"] = file_digest(directory / artifact["path"])
                        if artifact.get("metadata"):
                            artifact["metadata_sha256"] = file_digest(directory / artifact["metadata"])
                    atomic_json(directory / "runtime.json", dict(
                        mesh_seconds=time.monotonic()-started, wt_seconds=0,
                        wt_reused=True, total_inference_seconds=time.monotonic()-started))
                    atomic_json(directory / "run.json", dict(state, status="complete", artifacts=artifacts))
                except Exception:
                    failures += 1
                    atomic_json(directory / "run.json", dict(state, status="failed",
                        error=traceback.format_exc()))
                    backend.recover()
                    # Stop rather than repeatedly stressing the card after an unknown failure.
                    break
        finally:
            backend.unload_trellis()
        return failures


def reuse_official_result(job, stage, revision):
    """Reference a compatible existing official metric; never recompute H-fill."""
    for experiment in job["evaluation_roots"]:
        pointer = Path(experiment) / "baseline_evaluation.json"
        if not pointer.exists():
            continue
        index = read_json(Path(read_json(pointer)["directory"]) / "index.json")
        if index["revision"] != revision:
            continue
        for row in index["results"]:
            if (row.get("sample_id"), row.get("method"), row.get("config_id"),
                row.get("seed"), row.get("stage")) != (
                    job["sample_id"], "wt_trellis2", job["config_id"], 42, stage):
                continue
            if row.get("status") != "complete":
                continue
            path = Path(row["result_path"])
            if row.get("result_sha256") and file_digest(path) != row["result_sha256"]:
                raise ValueError(f"Official evaluation result changed: {path}")
            result = read_json(path)
            if (result.get("revision") != revision or result.get("status") != "complete"
                    or Path(result["source_directory"]).resolve()
                    != Path(job["source_directory"]).resolve()):
                continue
            if not result.get("inputs"):
                raise ValueError("Official evaluation lacks input provenance")
            for name, checksum in result["inputs"].items():
                if file_digest(Path(name)) != checksum:
                    raise ValueError(f"Official evaluation input changed: {name}")
            return result
    raise ValueError(f"No compatible official {stage} result; wait for camera evaluation: "
                     f"{job['dataset']}/{job['condition']}/{job['sample_id']}/{job['preprocessing']}")


def evaluate_plan(plan, evaluation_config, idle_check=assert_camera_idle):
    """Separate evaluation products; official inference artifacts remain read-only."""
    validate_plan(plan)
    validate_sources(plan)
    idle_check()
    from examples.evaluate_baseline_v2 import BaselineEvaluator
    from scripts.run_ood_evaluation import index_row
    evaluator = BaselineEvaluator(Path(evaluation_config))
    failures = 0
    for (dataset, condition), candidates in evaluation_candidates(plan).items():
        name = f"{Path(plan['root']).name}-{dataset}-{condition}"
        output = evaluator.root / name
        output.mkdir(parents=True, exist_ok=True)
        report = {"config": evaluator.config, "selected_seeds": [42],
                  "candidates": candidates, "mode": "fixed_seed", "plan_hash": plan["plan_hash"]}
        save_plan(output / "plan.json", report)
        rows = {}
        for candidate in candidates:
            idle_check()
            directory = Path(candidate["source_directory"])
            if read_json(directory / "run.json").get("status") != "complete":
                raise ValueError(f"Finish mesh inference before evaluation: {directory}")
            if candidate["strategy"] == "fill":
                job = next(j for j in plan["jobs"] if
                           (j["dataset"], j["condition"], j["sample_id"], j["config_id"], j["strategy"])
                           == (dataset, condition, candidate["sample_id"], candidate["config_id"], "fill"))
                result = reuse_official_result(resolved_job(plan, job), candidate["stage"], evaluator.revision)
            else:
                result = evaluator.evaluate(directory, candidate["stage"], name)
            for value in [*evaluator.index_updates, result]:
                row = index_row(value)
                key = tuple(row[k] for k in ("sample_id", "method", "config_id", "seed", "stage"))
                rows[key] = row
            evaluator.index_updates.clear()
            failures += result["status"] != "complete"
            atomic_json(output / "index.json", dict(revision=evaluator.revision,
                config=evaluator.config, results=list(rows.values()), plan_hash=plan["plan_hash"]))
        atomic_json(output / "ablation_groups.json", dict(dataset=dataset, condition=condition,
            candidates=candidates, selection=plan["selection"], plan_hash=plan["plan_hash"]))
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("plan", help="CPU-only: freeze selected sources and 720 logical outputs")
    p.add_argument("--camera-plan", type=Path, required=True)
    p.add_argument("--selection", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("check", help="CPU-only: validate plan and source checksums")
    p.add_argument("--plan", type=Path, required=True)
    for name in ("run", "evaluate"):
        p = commands.add_parser(name)
        p.add_argument("--plan", type=Path, required=True)
        p.add_argument("--execute-gpu", action="store_true")
        if name == "evaluate":
            p.add_argument("--evaluation-config", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        plan = build_plan(args.camera_plan, args.selection, args.root)
        save_plan(args.out, plan)
        print(plan["budget"])
        return 0
    if args.command in ("run", "evaluate") and not args.execute_gpu:
        parser.error("GPU execution is disabled; use --execute-gpu only after camera_ablation finishes")
    plan = read_json(args.plan)
    if args.command == "check":
        validate_plan(plan)
        validate_sources(plan)
        print("Plan and source checksums valid; no models loaded")
        return 0
    # No dependency download, camera preparation, or WT inference is performed here.
    if args.command == "run":
        return int(execute_plan(plan) != 0)
    return int(evaluate_plan(plan, args.evaluation_config) != 0)


if __name__ == "__main__":
    raise SystemExit(main())
