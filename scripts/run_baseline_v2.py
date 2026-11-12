"""Run fixed-seed baseline candidates using the established inference backends."""
import argparse
from collections import defaultdict
from contextlib import redirect_stderr, redirect_stdout
import datetime
import fcntl
import gc
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

from scripts.run_parallel_recovery import memory_sample, monitor_guard, new_backend, partitions
from wt.experiment import SCHEMA_VERSION, atomic_json, file_digest, read_json, run_directory
from wt.paths import OUTPUT_ROOT, REPO_ROOT

METHODS = {"baseline": {"wt": "defaults-v1", "trellis2": "defaults-v1",
                        "wt_trellis2": "defaults-v1"},
           "pixal": {"pixal3d": "resolution1024-v1"},
           "memory": {"wt_trellis2": "defaults-v1"}}


def inference_backend(kind):
    if kind != "memory":
        return new_backend(kind)
    from scripts.recovery_memory import MemoryBoundBackend
    ordinary = new_backend("baseline")
    return MemoryBoundBackend(ordinary.checkpoint, ordinary.trellis_model)


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def complete(directory):
    state = directory / "run.json"
    return state.is_file() and read_json(state).get("status") == "complete"


def terminal(directory):
    path = directory / "terminal_failure.json"
    if not path.exists():
        return False
    state = directory / "run.json"
    expected = file_digest(state) if state.exists() else None
    if read_json(path)["run_sha256"] != expected:
        raise ValueError(f"Terminal inference state changed: {directory}")
    return True


def jobs(root, inputs, kind, seed):
    manifest_path = root / "baseline_manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    memory_candidates = {tuple(value) for value in manifest.get("memory_candidates", [])}
    selected = []
    for sample in inputs:
        for method, configuration in METHODS[kind].items():
            memory_policy = (sample["sample_id"], method) in memory_candidates
            if (kind == "memory" and not memory_policy) or (kind == "baseline" and memory_policy):
                continue
            directory = run_directory(root, sample["sample_id"], method, configuration, seed)
            selected.append((sample, method, configuration, directory))
    return selected


def pending_inputs(root, inputs, kind, seed):
    unfinished = {sample["sample_id"] for sample, _, _, directory in jobs(root, inputs, kind, seed)
                  if not complete(directory) and not terminal(directory)}
    return [sample for sample in inputs if sample["sample_id"] in unfinished]


def initialize(root, source, config_path):
    config = read_json(config_path)
    expected = read_json(REPO_ROOT / "configs/historical_gso_samples.json")[config["split"]]
    paths = sorted((source / "samples").glob("*/input.json"))
    inputs = [read_json(path) for path in paths]
    if {sample["sample_id"] for sample in inputs} != set(expected):
        raise ValueError("Source assets differ from the frozen GSO split")
    records, memory_candidates = [], []
    for sample in inputs:
        if file_digest(Path(sample["image"])) != sample["sha256"]:
            raise ValueError(f"Frozen input changed: {sample['sample_id']}")
        destination = root / "samples" / sample["sample_id"] / "input.json"
        if destination.exists() and read_json(destination) != sample:
            raise ValueError(f"Existing experiment input changed: {destination}")
        for method, configuration in config["methods"].items():
            directory = run_directory(source, sample["sample_id"], method, configuration,
                                      config["report_single_seed"])
            state = directory / "run.json"
            if not complete(directory):
                raise ValueError(f"Source seed is incomplete: {directory}")
            if "runtime_memory_policy" in read_json(directory / "config.json")["provenance"]:
                memory_candidates.append([sample["sample_id"], method])
            records.append({"sample_id": sample["sample_id"], "method": method,
                            "source_directory": str(directory), "run_sha256": file_digest(state),
                            "config_sha256": file_digest(directory / "config.json")})
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": SCHEMA_VERSION, "source_experiment": str(source),
                "configuration": config, "source_candidates": records,
                "memory_candidates": sorted(memory_candidates),
                "inference_configs_sha256": file_digest(REPO_ROOT / "configs/recovery_defaults.json")}
    manifest_path = root / "baseline_manifest.json"
    if manifest_path.exists() and read_json(manifest_path) != manifest:
        raise ValueError("Frozen baseline manifest changed")
    atomic_json(manifest_path, manifest)
    header = root / "experiment.json"
    if not header.exists():
        atomic_json(header, {"schema_version": SCHEMA_VERSION, "experiment_id": root.name})
    for sample in inputs:
        destination = root / "samples" / sample["sample_id"] / "input.json"
        if not destination.exists():
            atomic_json(destination, sample)
    return inputs


def precompute(root, inputs, configs, seed, backend, kind):
    from wt.batch import cache_key
    missing = {}
    for sample in inputs:
        eligible = {method for _, method, _, _ in jobs(root, [sample], kind, seed)}
        for cfg in configs:
            if cfg["method"] == "trellis2" or cfg["method"] not in eligible:
                continue
            directory = run_directory(root, sample["sample_id"], cfg["method"], cfg["config_id"], seed)
            if complete(directory) or terminal(directory):
                continue
            key = cache_key(sample, cfg, seed, backend.provenance)
            cache = root / "_cache/wt" / key
            try:
                previous = read_json(cache / "complete.json")
                valid = (previous["cache_key"] == key
                         and file_digest(cache / "prediction.npz") == previous["sha256"]
                         and file_digest(cache / "rgba.png") == previous["rgba_sha256"])
            except (OSError, ValueError, KeyError):
                valid = False
            if not valid:
                missing[key] = (sample, cfg, cache)
    if not missing:
        return
    backend.load_wt()
    try:
        for position, (key, (sample, cfg, directory)) in enumerate(missing.items(), 1):
            directory.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            with (directory / "run.log").open("a") as log, redirect_stdout(log), redirect_stderr(log):
                backend.predict_wt(Path(sample["image"]), cfg, seed, directory)
            atomic_json(directory / "complete.json", {
                "cache_key": key, "sha256": file_digest(directory / "prediction.npz"),
                "rgba_sha256": file_digest(directory / "rgba.png"),
                "seconds": time.monotonic() - started})
            print("WT CACHE", seed, position, len(missing), sample["sample_id"], flush=True)
    finally:
        backend.unload_wt()


def run_worker(spec):
    root = Path(spec["root"])
    backend = inference_backend(spec["kind"])
    if backend.provenance != spec["provenance"]:
        raise ValueError("Inference provenance changed between parent and worker")
    inputs = spec["inputs"]
    if spec["kind"] == "pixal":
        from wt.baselines.pixal3d_batch import run_batch
        ids = [sample["sample_id"] for sample in inputs
               if not terminal(run_directory(root, sample["sample_id"], "pixal3d", "resolution1024-v1", spec["seed"]))]
        return run_batch(root, backend, ids, spec["seed"], summary_file=spec["summary"]) if ids else 0
    import wt.batch as batch
    groups = defaultdict(list)
    for sample in inputs:
        eligible = {method for _, method, _, _ in jobs(root, [sample], spec["kind"], spec["seed"])}
        active = tuple(index for index, cfg in enumerate(spec["configs"])
                       if cfg["method"] in eligible and not terminal(run_directory(root, sample["sample_id"], cfg["method"],
                                                     cfg["config_id"], spec["seed"])))
        if active:
            groups[active].append(sample)
    original = batch.atomic_json
    def save(path, value):
        if Path(path) == root / "last_batch.json":
            path = root / spec["summary"]
        original(path, value)
    batch.atomic_json = save
    try:
        failures = 0
        for indices, values in groups.items():
            configs = [spec["configs"][index] for index in indices]
            failures += batch.run_batch(root, values, configs, [spec["seed"]], backend)
        return int(failures > 0)
    finally:
        batch.atomic_json = original


def launch_worker(spec, directory, name):
    path = directory / f"{name}.json"
    atomic_json(path, spec)
    log_path = directory / f"{name}.log"
    log = log_path.open("a", buffering=1)
    process = subprocess.Popen([sys.executable, "-uB", "-m", "scripts.run_baseline_v2",
                                "--worker-spec", str(path)],
                               cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT)
    atomic_json(directory / f"{name}.process.json",
                {"pid": process.pid, "log": str(log_path), "started": timestamp()})
    return process, log


def monitor(processes, directory):
    missed, reason = 0, None
    peak_gpu, peak_cpu, missing_queries = 0, 0, 0
    try:
        with (directory / "resources.jsonl").open("a") as log:
            while any(process.poll() is None for process in processes):
                value = memory_sample()
                log.write(json.dumps(value) + "\n")
                log.flush()
                peak_gpu = max(peak_gpu, value["gpu_mib"] or 0)
                peak_cpu = max(peak_cpu, value["working_set_bytes"])
                missing_queries += value["gpu_mib"] is None
                missed, reason = monitor_guard(value, missed)
                if reason:
                    print("RESOURCE RECOVERY", reason, flush=True)
                    break
                time.sleep(10)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return {"guard": reason, "peak_gpu_mib": peak_gpu, "peak_working_set_bytes": peak_cpu,
            "missing_gpu_queries": missing_queries, "worker_exits": [p.returncode for p in processes]}


def record_failures(root, inputs, kind, seed, control, attempt):
    for sample, method, _, directory in jobs(root, inputs, kind, seed):
        state_path = directory / "run.json"
        state = read_json(state_path) if state_path.exists() else {}
        if state.get("status") not in ("failed", "running") or terminal(directory):
            continue
        if "initialization failed" in state.get("error", "").lower():
            raise RuntimeError(f"Model initialization failed, inspect {directory}")
        archive = control / "attempts" / sample["sample_id"] / method / str(attempt)
        archive.mkdir(parents=True, exist_ok=True)
        for name in ("run.json", "error.txt", "run.log", "inference.log"):
            if (directory / name).is_file():
                shutil.copyfile(directory / name, archive / name)
        history_path = directory / "attempt_history.json"
        history = read_json(history_path) if history_path.exists() else []
        history.append({"time": timestamp(), "status": state["status"], "evidence": str(archive),
                        "run_sha256": file_digest(state_path)})
        atomic_json(history_path, history)
        if len(history) >= 2:
            atomic_json(directory / "terminal_failure.json",
                        {"status": "failed", "attempts": history, "seed": seed,
                         "run_sha256": file_digest(state_path)})


def run_stage(args):
    root, source = args.experiment.resolve(), args.source_experiment.resolve()
    if not root.is_relative_to((OUTPUT_ROOT / "experiments").resolve()) or root == source:
        raise ValueError("Use a separate experiment under the configured output root")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0":
        raise ValueError("Use CUDA_VISIBLE_DEVICES=0 to preserve seed-42 inference provenance")
    config = read_json(args.config)
    if args.seed not in config["seeds"] or args.seed == config["report_single_seed"]:
        raise ValueError("Only additional seeds belong to the new inference directory")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inputs = initialize(root, source, args.config)
        inputs = pending_inputs(root, inputs, args.stage, args.seed)
        if not inputs:
            return 0
        from wt.batch import resolve_configs
        configs = resolve_configs(read_json(REPO_ROOT / "configs/recovery_defaults.json"))
        backend = inference_backend(args.stage)
        for sample, method, configuration, _ in jobs(root, inputs, args.stage, args.seed):
            old = run_directory(source, sample["sample_id"], method, configuration, config["report_single_seed"])
            if read_json(old / "config.json")["provenance"] != backend.provenance:
                raise ValueError(f"Current inference provenance differs from seed 42: {old}")
        provenance = backend.provenance
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        control = REPO_ROOT / ".runtime/logs/baseline-v2-20261110" / f"{args.stage}-seed{args.seed}-{stamp}"
        control.mkdir(parents=True)
        atomic_json(control / "started.json", {"started": timestamp(), "pid": os.getpid(),
                    "source_sha256": file_digest(Path(__file__)), "provenance": provenance,
                    "root": str(root), "kind": args.stage, "seed": args.seed})
        if args.stage in ("baseline", "memory"):
            precompute(root, inputs, configs, args.seed, backend, args.stage)
        del backend
        gc.collect()
        base = {"root": str(root), "kind": args.stage, "seed": args.seed,
                "configs": configs, "provenance": provenance}
        processes, handles = [], []
        workers = 1 if args.stage == "memory" else args.workers
        for index, values in enumerate(partitions(inputs, workers)):
            spec = {**base, "inputs": values, "summary": f"seed-{args.seed}-{args.stage}-worker-{index}.json"}
            process, handle = launch_worker(spec, control, f"worker-{index}")
            processes.append(process)
            handles.append(handle)
        execution = monitor(processes, control)
        for handle in handles:
            handle.close()
        record_failures(root, inputs, args.stage, args.seed, control, 1)
        pending = pending_inputs(root, inputs, args.stage, args.seed)
        retry = 0
        while pending:
            retry += 1
            health = memory_sample()
            _, reason = monitor_guard(health, 0)
            if health["gpu_mib"] is None or reason:
                raise RuntimeError(f"Resources unavailable for serial recovery: {health}")
            spec = {**base, "inputs": pending, "summary": f"seed-{args.seed}-{args.stage}-serial.json"}
            process, handle = launch_worker(spec, control, f"serial-{retry}")
            serial = monitor([process], control)
            handle.close()
            record_failures(root, pending, args.stage, args.seed, control, retry + 1)
            updated = pending_inputs(root, pending, args.stage, args.seed)
            if len(updated) == len(pending) and all(
                    read_json(directory / "run.json").get("status") == "planned"
                    for _, _, _, directory in jobs(root, updated, args.stage, args.seed)
                    if (directory / "run.json").exists()):
                raise RuntimeError(f"Worker made no inference progress: {serial}")
            pending = updated
        terminal_count = sum(terminal(directory) for _, _, _, directory in jobs(root, inputs, args.stage, args.seed))
        report = {"status": "complete", "kind": args.stage, "seed": args.seed,
                  "terminal_failures": terminal_count, "serial_retries": retry,
                  "execution": execution, "control": str(control), "finished": timestamp()}
        atomic_json(control / "complete.json", report)
        atomic_json(root / f"generation-{args.stage}-seed-{args.seed}.json", report)
        print(json.dumps(report), flush=True)
    return 0


def evaluate_seed(args, seed):
    command = [str(REPO_ROOT / ".venv/bin/python"), "-uB", "-m", "examples.evaluate_baseline_v2",
               "--experiment", str(args.experiment), "--source-experiment", str(args.source_experiment),
               "--config", str(args.config), "--seeds", str(seed)]
    if args.save_multiview_renders:
        command.append("--save-multiview-renders")
    evaluated = subprocess.run(command, cwd=REPO_ROOT)
    atomic_json(args.experiment / f"evaluation-seed-{seed}.json",
                {"finished": timestamp(), "exit_code": evaluated.returncode})
    if evaluated.returncode:
        raise RuntimeError(f"Evaluation for seed {seed} requires recovery")


def run_queue(args):
    config = read_json(args.config)
    seeds = args.seeds or [seed for seed in config["seeds"] if seed != config["report_single_seed"]]
    if len(set(seeds)) != len(seeds) or set(seeds) - set(config["seeds"]) or config["report_single_seed"] in seeds:
        raise ValueError("Queue seeds must be distinct additional seeds in the fixed budget")
    evaluate_seed(args, config["report_single_seed"])
    for seed in seeds:
        for kind, environment in (("baseline", "scripts/env.sh"), ("memory", "scripts/env.sh"),
                                  ("pixal", "compare_methods/pixal3d/env.sh")):
            command = ["python", "-uB", "-m", "scripts.run_baseline_v2",
                       "--experiment", str(args.experiment), "--source-experiment", str(args.source_experiment),
                       "--config", str(args.config), "--stage", kind, "--seed", str(seed),
                       "--workers", str(args.workers)]
            shell = f"cd {shlex.quote(str(REPO_ROOT))} && source {shlex.quote(environment)} && {shlex.join(command)}"
            environment_values = dict(os.environ)
            if kind == "memory":
                environment_values["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
            subprocess.run(["bash", "-c", shell], check=True, env=environment_values)
        evaluate_seed(args, seed)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path)
    parser.add_argument("--source-experiment", type=Path)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs/baseline_v2.json")
    parser.add_argument("--seeds", type=int, nargs="+")
    parser.add_argument("--save-multiview-renders", action="store_true",
                        help="Also export multi-view PNG sets during evaluation")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--stage", choices=("baseline", "memory", "pixal"))
    parser.add_argument("--worker-spec", type=Path)
    args = parser.parse_args()
    if args.worker_spec:
        return run_worker(read_json(args.worker_spec))
    if args.experiment is None or args.source_experiment is None:
        parser.error("--experiment and --source-experiment are required")
    if not os.environ.get("TMUX"):
        parser.error("Use the project's dedicated tmux session")
    return run_stage(args) if args.stage else run_queue(args)


if __name__ == "__main__":
    raise SystemExit(main())
