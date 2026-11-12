"""Run frozen OOD inputs with serial WT and two independent, monitored mesh workers."""
import argparse
import datetime
import fcntl
import json
from pathlib import Path
import subprocess
import sys

from scripts.run_baseline_v2 import monitor
from scripts.run_parallel_recovery import (
    archive_incomplete, baseline_preflight, incomplete, memory_sample,
    monitor_guard, new_backend, partitions, precompute_wt,
)
from wt.batch import resolve_configs
from wt.experiment import SCHEMA_VERSION, atomic_json, file_digest, read_json
from wt.paths import OUTPUT_ROOT, REPO_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--configs", type=Path, default=REPO_ROOT / "configs/ood_inference.json")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--precompute-only", action="store_true", help="Prepare serial WT caches for a later mesh run")
    args = parser.parse_args()
    root = args.out.resolve()
    if not root.is_relative_to((OUTPUT_ROOT / "experiments").resolve()):
        parser.error("Experiment must be under the configured output directory")
    inputs = [json.loads(line) for line in args.inputs.read_text().splitlines() if line.strip()]
    ids = [sample["sample_id"] for sample in inputs]
    frozen = read_json(args.inputs.parent / "split.json")["splits"][args.inputs.stem]
    if set(ids) != set(frozen) or len(ids) != len(frozen):
        raise ValueError("Input list differs from the frozen split")
    for sample in inputs:
        if file_digest(Path(sample["image"])) != sample["artifact_sha256"]["input.png"]:
            raise ValueError(f"Frozen image changed: {sample['sample_id']}")
    configs = resolve_configs(read_json(args.configs))
    if {config["method"] for config in configs} != {"wt", "trellis2"}:
        raise ValueError("This OOD runner expects WT and native TRELLIS.2")
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    control = REPO_ROOT / ".runtime/logs/ood-20261111" / (root.name + "-" + stamp)
    control.mkdir(parents=True)
    with (root / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        backend = new_backend("baseline")
        baseline_preflight(root, inputs, configs, backend)
        precompute_wt(root, inputs, configs, backend)
        if args.precompute_only:
            atomic_json(root / "ood_precompute.json", {
                "status": "passed", "samples": len(inputs), "seed": 42,
                "inputs_sha256": file_digest(args.inputs), "configs_sha256": file_digest(args.configs),
                "provenance": backend.provenance,
            })
            print({"status": "passed", "wt_caches": len(inputs)}, flush=True)
            return
        provenance = backend.provenance
        header = root / "experiment.json"
        if header.exists():
            if read_json(header)["schema_version"] != SCHEMA_VERSION:
                raise ValueError("Existing experiment schema changed")
        else:
            atomic_json(header, {"schema_version": SCHEMA_VERSION, "experiment_id": root.name})
        shards = partitions(inputs, args.workers)
        processes, handles = [], []
        try:
            for index, samples in enumerate(shards):
                spec = {
                    "kind": "baseline", "root": str(root), "samples": samples,
                    "configs": configs, "provenance": provenance,
                    "summary": f"ood-worker-{index}.json",
                }
                path = control / f"worker-{index}.json"
                atomic_json(path, spec)
                log_path = control / f"worker-{index}.log"
                log = log_path.open("w", buffering=1)
                handles.append(log)
                process = subprocess.Popen(
                    [sys.executable, "-uB", "-m", "scripts.run_parallel_recovery",
                     "--worker-spec", str(path)], cwd=REPO_ROOT,
                    stdout=log, stderr=subprocess.STDOUT)
                processes.append(process)
                atomic_json(control / f"worker-{index}.process.json",
                            {"pid": process.pid, "log": str(log_path)})
            observed = monitor(processes, control)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=30)
            for handle in handles:
                handle.close()
        pending = incomplete(root, ids, "baseline", configs)
        retries = []
        if pending:
            retries = archive_incomplete(root, pending, control / "incomplete-attempts")
            health = memory_sample()
            atomic_json(control / "retry-resources.json", health)
            _, unsafe = monitor_guard(health, 0)
            if health["gpu_mib"] is None or unsafe:
                raise RuntimeError(f"Resources have not recovered: {health}")
            retry_ids = {path.relative_to(root / "samples").parts[0] for path in pending}
            spec = {
                "kind": "baseline", "root": str(root),
                "samples": [sample for sample in inputs if sample["sample_id"] in retry_ids],
                "configs": configs, "provenance": provenance, "summary": "ood-serial-retry.json",
            }
            path = control / "retry.json"
            atomic_json(path, spec)
            print(f"SERIAL RETRY {len(retry_ids)} samples", flush=True)
            with (control / "retry.log").open("w", buffering=1) as log:
                retry_process = subprocess.run(
                    [sys.executable, "-uB", "-m", "scripts.run_parallel_recovery",
                     "--worker-spec", str(path)], cwd=REPO_ROOT,
                    stdout=log, stderr=subprocess.STDOUT)
                if retry_process.returncode not in (0, 1):
                    raise RuntimeError(f"Serial worker exited unexpectedly: {retry_process.returncode}")
        terminal_failures = []
        for directory in incomplete(root, ids, "baseline", configs):
            state_path = directory / "run.json"
            state = read_json(state_path)
            if state["status"] != "failed" or "initialization failed" in state.get("error", "").lower():
                raise RuntimeError(f"Inference needs recovery: {directory}")
            terminal = {
                "status": "failed", "seed": 42, "run_sha256": file_digest(state_path),
                "parallel_attempt": str(control / "incomplete-attempts"),
                "serial_attempt": str(control / "retry.log"),
                "error": state.get("error"),
            }
            atomic_json(directory / "terminal_failure.json", terminal)
            terminal_failures.append(str(directory))
        if any(observed["worker_exits"]) and not retries:
            raise RuntimeError("A worker failed after writing outputs; inspect the preserved log")
        report = {
            "status": "completed_with_failures" if terminal_failures else "passed",
            "terminal_failures": terminal_failures, "inputs_sha256": file_digest(args.inputs),
            "configs_sha256": file_digest(args.configs), "runner_sha256": file_digest(Path(__file__)),
            "samples": len(inputs), "wt_batch_size": 1, "mesh_workers": len(shards), "seed": 42,
            "provenance": provenance, "resources": observed, "retries": retries,
            "control": str(control),
        }
        atomic_json(root / "ood_execution.json", report)
        atomic_json(control / "complete.json", report)
        print({"status": report["status"], "samples": len(inputs),
               "failed_candidates": len(terminal_failures), "control": str(control)}, flush=True)


if __name__ == "__main__":
    main()
