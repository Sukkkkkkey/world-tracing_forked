"""Evaluate disjoint OOD assets in two processes using the unchanged v0.5 evaluator."""
import argparse
import datetime
import fcntl
import gc
from pathlib import Path
import subprocess
import sys
import traceback

from examples.evaluate_baseline_v2 import BaselineEvaluator, candidate_plan
from examples.summarize_baseline_v2 import markdown, summary, write_render_index
from scripts.run_baseline_v2 import monitor
from scripts.run_parallel_recovery import partitions
from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import OUTPUT_ROOT, REPO_ROOT


def index_row(result):
    return {
        **{name: result[name] for name in
           ("sample_id", "method", "config_id", "seed", "stage", "source_directory", "status", "result_path")},
        "result_sha256": file_digest(Path(result["result_path"])),
        "failure_phase": result.get("failure_phase"),
    }


def run_worker(spec):
    evaluator = BaselineEvaluator(Path(spec["config"]))
    results = {}
    for position, candidate in enumerate(spec["candidates"], 1):
        directory = Path(candidate["source_directory"])
        state_path = directory / "run.json"
        try:
            if read_json(state_path)["status"] == "complete":
                result = evaluator.evaluate(directory, candidate["stage"], spec["experiment_name"])
            else:
                terminal = read_json(directory / "terminal_failure.json")
                if terminal["run_sha256"] != file_digest(state_path):
                    raise ValueError("Terminal inference record changed")
                result = evaluator.failed_candidate(
                    candidate, spec["experiment_name"], terminal, "inference")
        except Exception:
            result = evaluator.failed_candidate(
                candidate, spec["experiment_name"], traceback.format_exc(), "evaluation")
        for updated in [*evaluator.index_updates, result]:
            key = (updated["sample_id"], updated["method"], updated["seed"], updated["stage"])
            results[key] = index_row(updated)
        evaluator.index_updates.clear()
        atomic_json(Path(spec["index"]), {"revision": evaluator.revision, "results": list(results.values())})
        print(f"{position}/{len(spec['candidates'])} {candidate['sample_id']} "
              f"{candidate['method']} {candidate['stage']} {result['status']}", flush=True)
    return int(any(row["status"] != "complete" and row["failure_phase"] != "inference"
                   for row in results.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs/ood_omniobject3d_v05.json")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--calibration", action="store_true")
    parser.add_argument("--worker-spec", type=Path)
    args = parser.parse_args()
    if args.worker_spec:
        return run_worker(read_json(args.worker_spec))
    if args.experiment is None:
        parser.error("--experiment is required")
    experiment = args.experiment.resolve()
    if not experiment.is_relative_to((OUTPUT_ROOT / "experiments").resolve()):
        parser.error("Experiment must be under the configured output directory")
    evaluator = BaselineEvaluator(args.config)
    config, revision = evaluator.config, evaluator.revision
    output = evaluator.root / experiment.name
    if config["seeds"] != [42]:
        raise ValueError("This OOD execution entry uses the frozen single seed")
    plan = candidate_plan(experiment, experiment, config, [42])
    for candidate in plan:
        directory = Path(candidate["source_directory"])
        state_path = directory / "run.json"
        if read_json(state_path)["status"] != "complete":
            terminal = read_json(directory / "terminal_failure.json")
            if terminal["run_sha256"] != file_digest(state_path):
                raise ValueError("Finish inference recovery before evaluation")
    del evaluator
    gc.collect()
    import torch
    torch.cuda.empty_cache()
    mode = "calibration" if args.calibration else "formal"
    plan_record = {"config": config, "selected_seeds": [42], "candidates": plan, "mode": mode}
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    control = REPO_ROOT / ".runtime/logs/ood-20261111" / (experiment.name + "-eval-" + stamp)
    control.mkdir(parents=True)
    with (output / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (output / "plan.json").exists():
            if read_json(output / "plan.json") != plan_record:
                raise ValueError("Existing evaluation plan differs")
        atomic_json(output / "plan.json", plan_record)
        sample_ids = sorted({row["sample_id"] for row in plan})
        shards = partitions(sample_ids, args.workers)
        processes, handles, indexes = [], [], []
        try:
            for number, values in enumerate(shards):
                index_path = control / f"worker-{number}-index.json"
                spec = {
                    "config": str(args.config.resolve()), "experiment_name": experiment.name,
                    "candidates": [row for row in plan if row["sample_id"] in set(values)],
                    "index": str(index_path),
                }
                spec_path = control / f"worker-{number}.json"
                atomic_json(spec_path, spec)
                log_path = control / f"worker-{number}.log"
                log = log_path.open("w", buffering=1)
                handles.append(log)
                process = subprocess.Popen(
                    [sys.executable, "-uB", "-m", "scripts.run_ood_evaluation",
                     "--worker-spec", str(spec_path)], cwd=REPO_ROOT,
                    stdout=log, stderr=subprocess.STDOUT)
                processes.append(process)
                indexes.append(index_path)
                atomic_json(control / f"worker-{number}.process.json",
                            {"pid": process.pid, "log": str(log_path)})
            observed = monitor(processes, control)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=30)
            for handle in handles:
                handle.close()
        rows = []
        for index_path in indexes:
            if index_path.exists():
                index = read_json(index_path)
                if index["revision"] != revision:
                    raise ValueError("Worker evaluation revision changed")
                rows.extend(index["results"])
        keys = [(row["sample_id"], row["method"], row["seed"], row["stage"]) for row in rows]
        if len(set(keys)) != len(keys):
            raise ValueError("Worker sample partitions overlapped")
        rows.sort(key=lambda row: (row["sample_id"], row["method"], row["seed"], row["stage"]))
        atomic_json(output / "index.json", {"revision": revision, "config": config, "results": rows})
        retry = any(observed["worker_exits"]) or len(rows) != len(plan)
        if retry:
            print("SERIAL EVALUATION RECOVERY", observed, flush=True)
            command = [
                sys.executable, "-uB", "-m", "examples.evaluate_baseline_v2",
                "--experiment", str(experiment), "--source-experiment", str(experiment),
                "--config", str(args.config), "--seeds", "42",
            ]
            if args.calibration:
                command.append("--calibration")
            subprocess.run(command, cwd=REPO_ROOT, check=True)
        report = summary(output)
        atomic_json(output / "summary.json", report)
        (output / "summary.md").write_text(markdown(report))
        write_render_index(output, report)
        atomic_json(experiment / "baseline_evaluation.json", {
            "revision": revision, "directory": str(output),
            "index_sha256": file_digest(output / "index.json"), "summary": str(output / "summary.json"),
        })
        atomic_json(output / "execution.json", {
            "workers": len(shards), "resources": observed, "serial_retry": retry,
            "runner_sha256": file_digest(Path(__file__)), "control": str(control),
            "planned": len(plan), "evaluated": report["evaluated_stages"],
        })
        print({"evaluation": str(output), "planned": len(plan), "status": report["status_counts"]}, flush=True)
        final_index = read_json(output / "index.json")
        failed_evaluations = [
            row for row in final_index["results"]
            if row["status"] != "complete" and
            read_json(Path(row["result_path"])).get("failure_phase") != "inference"
        ]
        return int(report["pending_stages"] > 0 or bool(failed_evaluations))


if __name__ == "__main__":
    raise SystemExit(main())
