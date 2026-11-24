"""Plan, run, or evaluate the Hybrid pilot; GPU work requires --execute-gpu."""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import nullcontext, redirect_stdout, redirect_stderr
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


def mesh_batches(plan, batch_size):
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    rows = [resolved_job(plan, r) for r in plan["jobs"] if r["strategy"] != "fill"]
    if batch_size == 1:
        return [[job] for job in rows]
    groups = defaultdict(list)
    for job in rows:
        groups[job["experiment_root"], job["config_id"]].append(job)
    return [jobs[i:i + batch_size] for jobs in groups.values()
            for i in range(0, len(jobs), batch_size)]


def execute_plan(plan, backend_factory=None, idle_check=assert_camera_idle, *, batch_size=1):
    """Single-process mesh inference; larger batches share the diffusion passes."""
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
        executor = file_digest(Path(__file__))
        for group in mesh_batches(plan, batch_size):
            members = [job["source_key"] for job in group]
            schedule = dict(requested_size=batch_size, actual_size=len(group), members=members)
            todo = []
            for job in group:
                payload = dict(parameters=job["parameters"], strategy=job["strategy"],
                    source_pins=job["pins"], transform=job["canonical_transform"],
                    provenance=backend.provenance, executor_sha256=executor)
                if batch_size > 1:
                    payload.update(batch=schedule, plan_hash=plan["plan_hash"])
                identity = digest(payload)
                directory = Path(job["destination"])
                if not completed_job(directory, identity, job["input"]["sha256"]):
                    todo.append((job, directory, identity))
            if todo:
                pending.append((group, todo, schedule))
        if not pending:
            return 0
        save_plan(root / "plan.json", plan)
        failures = 0
        try:
            idle_check()
            backend.load_trellis(include_stage1=False, modes={"1024_cascade"})
            for group, todo, schedule in pending:
                idle_check()
                validate_sources({"sources": {j["source_key"]: j for j in group}})
                started = time.monotonic()
                try:
                    with (backend.prepare_batch(group) if batch_size > 1 else nullcontext()):
                        sampling_seconds = time.monotonic() - started if batch_size > 1 else 0
                        for job, directory, identity in todo:
                            idle_check()
                            finish_mesh(plan, backend, job, directory, identity, schedule, sampling_seconds)
                except Exception:
                    message = traceback.format_exc()
                    failed = [str(d) for _, d, _ in todo if not (d / "run.json").exists()
                              or read_json(d / "run.json").get("status") != "complete"]
                    atomic_json(root / "batch-failures" / (digest(schedule) + ".json"),
                                dict(batch=schedule, failed=failed, error=message))
                    print(message, flush=True)
                    failures += max(1, len(failed))
                    backend.recover()
                    if batch_size == 1 or "out of memory" not in message.lower():
                        break
        finally:
            backend.unload_trellis()
        return failures


def finish_mesh(plan, backend, job, directory, identity, schedule, sampling_seconds):
    experiment = Path(job["experiment_root"])
    header = dict(schema_version=SCHEMA_VERSION, experiment_id=experiment.name)
    save_plan(experiment / "experiment.json", header)
    save_plan(experiment / "samples" / job["sample_id"] / "input.json", job["input"])
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory / "config.json", dict(
        parameters=job["parameters"], provenance=backend.provenance,
        hybrid_ablation=dict(strategy=job["strategy"], condition=job["condition"],
            preprocessing=job["preprocessing"], source=job["source_directory"],
            source_pins=job["pins"], plan_hash=plan["plan_hash"], batch=schedule)))
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
        sample_seconds = time.monotonic() - started
        atomic_json(directory / "runtime.json", dict(
            mesh_seconds=sample_seconds + sampling_seconds / len(schedule["members"]), wt_seconds=0,
            batch_sampling_seconds=sampling_seconds, per_sample_seconds=sample_seconds,
            wt_reused=True, total_inference_seconds=sample_seconds + sampling_seconds / len(schedule["members"])))
        atomic_json(directory / "run.json", dict(state, status="complete", artifacts=artifacts))
    except Exception:
        atomic_json(directory / "run.json", dict(state, status="failed", error=traceback.format_exc()))
        raise


class MissingOfficialMetric(ValueError):
    """The frozen source has no compatible completed metric for this stage."""


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
                if stage == "glb" and name == (result.get("export_pair") or {}).get("decoded_result"):
                    continue
                if stage == "glb" and Path(name).name == "decoded_mesh.ply":
                    raise ValueError("Unexpected decoded mesh input in an official GLB result")
                if file_digest(Path(name)) != checksum:
                    raise ValueError(f"Official evaluation input changed: {name}")
            return result
    raise MissingOfficialMetric(f"No compatible official {stage} result; wait for camera evaluation: "
                     f"{job['dataset']}/{job['condition']}/{job['sample_id']}/{job['preprocessing']}")


def evaluate_plan(plan, evaluation_config=None, idle_check=assert_camera_idle):
    """Separate evaluation products; official inference artifacts remain read-only."""
    validate_plan(plan)
    validate_sources(plan)
    idle_check()
    from evaluation.hybrid_glb import HybridGlbEvaluator
    from scripts.run_ood_evaluation import index_row
    contexts = {}
    if evaluation_config is None:
        camera_plan = Path(plan["camera_plan"])
        if file_digest(camera_plan) != plan["camera_plan_sha256"]:
            raise ValueError("Frozen camera plan changed")
        contexts = {(c["dataset"], c["condition"]): c for c in read_json(camera_plan)["contexts"]}
    failures = 0
    for (dataset, condition), candidates in evaluation_candidates(plan).items():
        name = f"{Path(plan['root']).name}-{dataset}-{condition}-glb-only"
        context = contexts.get((dataset, condition))
        config_path = Path(context["evaluation_config"] if context else evaluation_config)
        evaluator = HybridGlbEvaluator(config_path)
        if context:
            official = read_json(Path(context["root"]) / "baseline_evaluation.json")
            if evaluator.revision != official["revision"]:
                raise ValueError(f"Official evaluation revision mismatch: {dataset}/{condition}")
        output = evaluator.root / name
        output.mkdir(parents=True, exist_ok=True)
        report = {"config": evaluator.config, "selected_seeds": [42],
                  "evaluation_scope": "exported-glb-only-v1", "candidates": candidates, "mode": "fixed_seed", "plan_hash": plan["plan_hash"]}
        save_plan(output / "plan.json", report)
        rows = {}
        missing_official = []
        for candidate in candidates:
            idle_check()
            directory = Path(candidate["source_directory"])
            if not (directory / "run.json").exists() or read_json(directory / "run.json").get("status") != "complete":
                result = evaluator.failed_candidate(candidate, name, "No complete inference GLB", "inference")
            elif candidate["strategy"] == "fill":
                job = next(j for j in plan["jobs"] if
                           (j["dataset"], j["condition"], j["sample_id"], j["config_id"], j["strategy"])
                           == (dataset, condition, candidate["sample_id"], candidate["config_id"], "fill"))
                try:
                    result = reuse_official_result(resolved_job(plan, job), candidate["stage"], evaluator.revision)
                except MissingOfficialMetric as exc:
                    missing_official.append(dict(candidate, status="unavailable", reason=str(exc)))
                    failures += 1
                    atomic_json(output / "missing_official.json", missing_official)
                    continue
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
        atomic_json(output / "missing_official.json", missing_official)
        del evaluator
        atomic_json(output / "ablation_groups.json", dict(dataset=dataset, condition=condition,
            candidates=candidates, selection=plan["selection"], plan_hash=plan["plan_hash"]))
    return failures


def check_camera_evaluation_overlap(state_path):
    """Allow an explicitly selected overlap controller in its evaluation-only phase."""
    state = read_json(state_path)
    if state.get("status") != "running":
        return assert_camera_idle()
    if (state.get("phase") != "evaluation" or state.get("inference_phase")
            or state.get("external_worker") or state.get("external_workers")
            or any(w.get("kind") != "eval" for w in state["active"])):
        raise RuntimeError("Camera inference is active")
    pid = int(state["controller_pid"])
    args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    if (not any(Path(os.fsdecode(arg)).name == "run_camera_ablation_overlap.py" for arg in args)
            or os.fsencode(str(state_path.resolve().parent)) not in args):
        raise RuntimeError("Cannot confirm the selected camera evaluation controller")


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
        if name == "run":
            p.add_argument("--overlap-camera-evaluation", type=Path, metavar="STATE_JSON",
                           help="Allow concurrent camera evaluation after its inference has finished")
            p.add_argument("--batch-size", type=int, default=1,
                           help="Assets in a single batched Hybrid diffusion call (default: 1)")
        if name == "evaluate":
            p.add_argument("--evaluation-config", type=Path, help="Default: each group uses its frozen camera evaluation config")
    args = parser.parse_args()
    if args.command == "run" and args.batch_size < 1:
        parser.error("--batch-size must be positive")
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
        guard = assert_camera_idle
        if args.overlap_camera_evaluation:
            guard = lambda: check_camera_evaluation_overlap(args.overlap_camera_evaluation)
        return int(execute_plan(plan, batch_size=args.batch_size, idle_check=guard) != 0)
    return int(evaluate_plan(plan, args.evaluation_config) != 0)


if __name__ == "__main__":
    raise SystemExit(main())
