"""Evaluate disjoint asset shards with the frozen numerical implementation."""
import argparse
import subprocess
import sys
from pathlib import Path

from evaluation.camera_summary import candidate_key, summary
from examples.evaluate_baseline_v2 import BaselineEvaluator
from examples.summarize_baseline_v2 import markdown, write_render_index
from scripts.run_baseline_v2 import monitor
from scripts.run_ood_evaluation import index_row
from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import REPO_ROOT


def partition_candidates(candidates, workers):
    samples = list(dict.fromkeys(row["sample_id"] for row in candidates))
    shards = [set(samples[i::workers]) for i in range(workers)]
    return [[row for row in candidates if row["sample_id"] in ids] for ids in shards if ids]


def work(spec_path, output_path):
    spec = read_json(spec_path)
    evaluator = BaselineEvaluator(Path(spec["config"]))
    rows = {}
    failures = 0
    for candidate in spec["candidates"]:
        result = evaluator.evaluate(Path(candidate["source_directory"]), candidate["stage"], spec["experiment_name"])
        for value in [*evaluator.index_updates, result]:
            row = index_row(value)
            rows[candidate_key(row)] = row
        evaluator.index_updates.clear()
        atomic_json(output_path, {"revision": evaluator.revision, "config": evaluator.config,
                                 "results": list(rows.values())})
        failures += result["status"] != "complete"
        print(candidate_key(candidate), result["status"], flush=True)
    return int(failures != 0)


def evaluate(spec_path, control, workers):
    spec = read_json(spec_path)
    control.mkdir(parents=True, exist_ok=True)
    handles, processes, paths = [], [], []
    try:
        for number, candidates in enumerate(partition_candidates(spec["candidates"], workers)):
            shard_spec = dict(spec, candidates=candidates)
            shard_path = control / f"worker-{number}.json"
            atomic_json(shard_path, shard_spec)
            output = control / f"worker-{number}-index.json"
            path = control / f"worker-{number}.log"
            handle = path.open("a", buffering=1)
            handles.append(handle)
            command = [sys.executable, "-uB", str(Path(__file__).resolve()), "--worker",
                       "--spec", str(shard_path), "--index", str(output)]
            process = subprocess.Popen(command, cwd=REPO_ROOT, stdout=handle, stderr=subprocess.STDOUT)
            processes.append(process)
            paths.append(output)
            atomic_json(control / f"worker-{number}-process.json",
                        {"pid": process.pid, "command": command, "log": str(path)})
        observed = monitor(processes, control)
        atomic_json(control / "worker-exits.json", observed)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)
        for handle in handles:
            handle.close()
    if any(observed["worker_exits"]):
        return 1
    indexes = [read_json(path) for path in paths]
    if len({index["revision"] for index in indexes}) != 1:
        raise ValueError("Mixed numerical revisions across workers")
    revision = indexes[0]["revision"]
    config = indexes[0]["config"]
    from wt.paths import OUTPUT_ROOT
    destination = OUTPUT_ROOT / config["output_root"] / revision / spec["experiment_name"]
    destination.mkdir(parents=True, exist_ok=True)
    plan = {"config": config, "selected_seeds": [42], "candidates": spec["full_plan"], "mode": "fixed_seed"}
    if (destination / "plan.json").exists() and read_json(destination / "plan.json") != plan:
        raise ValueError("Frozen numerical plan differs")
    atomic_json(destination / "plan.json", plan)
    existing = read_json(destination / "index.json")["results"] if (destination / "index.json").exists() else []
    rows = {candidate_key(row): row for row in existing}
    incoming = {}
    for index in indexes:
        for row in index["results"]:
            key = candidate_key(row)
            if key in incoming:
                raise ValueError("Worker asset shards overlap")
            if file_digest(Path(row["result_path"])) != row["result_sha256"]:
                raise ValueError("Worker result changed")
            incoming[key] = row
    expected = {candidate_key(row) for row in spec["candidates"]}
    if set(incoming) != expected:
        raise ValueError("Worker results do not cover the exact batch")
    rows.update(incoming)
    atomic_json(destination / "index.json", {"revision": revision, "config": config, "results": list(rows.values())})
    report = summary(destination)
    atomic_json(destination / "summary.json", report)
    (destination / "summary.md").write_text(markdown(report))
    write_render_index(destination, report)
    atomic_json(Path(spec["root"]) / "baseline_evaluation.json", {
        "revision": revision, "directory": str(destination),
        "index_sha256": file_digest(destination / "index.json"), "summary": str(destination / "summary.json")})
    atomic_json(control / "executor.json", {
        "source_sha256": file_digest(Path(__file__)), "workers": len(indexes),
        "numerical_revision": revision, "index_sha256": file_digest(destination / "index.json")})
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--index", type=Path)
    args = parser.parse_args()
    if args.worker:
        if args.index is None:
            parser.error("--worker requires --index")
        return work(args.spec, args.index)
    if args.control is None:
        parser.error("--control required for the coordinator")
    return evaluate(args.spec, args.control, args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
