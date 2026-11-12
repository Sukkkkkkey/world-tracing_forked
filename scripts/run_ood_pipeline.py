"""Run the frozen OOD sample in ready batches, evaluating each batch after inference."""
import argparse
from collections import Counter
import fcntl
import gc
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

from examples.summarize_baseline_v2 import distribution, markdown, summary, write_render_index
from scripts.run_baseline_v2 import monitor
from scripts.run_parallel_recovery import partitions
from wt.experiment import atomic_json, file_digest, read_json, run_directory
from wt.paths import OUTPUT_ROOT, REPO_ROOT


def run_stage(command, directory, *, monitor_resources=True):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "run.log").open("a", buffering=1) as log:
        process = subprocess.Popen(command, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT)
        atomic_json(directory / "process.json", {"pid": process.pid, "command": command,
                                                "log": str(directory / "run.log")})
        if monitor_resources:
            observed = monitor([process], directory)
        else:
            observed = {"worker_exits": [process.wait()], "monitor": "delegated-to-stage"}
    atomic_json(directory / "exit.json", observed)
    if process.returncode:
        raise RuntimeError(f"Stage failed with exit {process.returncode}, see {directory / 'run.log'}")


def frozen_plan(experiment, selected_ids, config):
    candidates = []
    for sample in sorted(selected_ids):
        for method, configuration in config["methods"].items():
            for stage in (["points"] if method == "wt" else config["mesh_stages"]):
                candidates.append({
                    "sample_id": sample, "method": method, "config_id": configuration,
                    "seed": 42, "stage": stage,
                    "source_directory": str(run_directory(experiment, sample, method, configuration, 42))})
    return {"config": config, "selected_seeds": [42], "candidates": candidates, "mode": "formal"}


def publish(experiment, evaluation, revision, config, rows):
    rows.sort(key=lambda row: (row["sample_id"], row["method"], row["seed"], row["stage"]))
    atomic_json(evaluation / "index.json", {"revision": revision, "config": config, "results": rows})
    report = summary(evaluation)
    atomic_json(evaluation / "summary.json", report)
    (evaluation / "summary.md").write_text(markdown(report))
    write_render_index(evaluation, report)
    atomic_json(experiment / "baseline_evaluation.json", {
        "revision": revision, "directory": str(evaluation),
        "index_sha256": file_digest(evaluation / "index.json"),
        "summary": str(evaluation / "summary.json")})
    return report


def evaluate_batch(plan, sample_ids, config_path, experiment, control):
    candidates = [row for row in plan["candidates"] if row["sample_id"] in set(sample_ids)]
    indexes = []
    workers, handles = [], []
    control.mkdir(parents=True, exist_ok=True)
    try:
        for number, shard in enumerate(partitions(sample_ids, 2)):
            index_path = control / f"worker-{number}-index.json"
            spec = {"config": str(config_path), "experiment_name": experiment.name,
                    "candidates": [row for row in candidates if row["sample_id"] in set(shard)],
                    "index": str(index_path)}
            spec_path = control / f"worker-{number}.json"
            atomic_json(spec_path, spec)
            log_path = control / f"worker-{number}.log"
            handle = log_path.open("a", buffering=1)
            handles.append(handle)
            process = subprocess.Popen(
                [sys.executable, "-uB", "-m", "scripts.run_ood_evaluation", "--worker-spec", str(spec_path)],
                cwd=REPO_ROOT, stdout=handle, stderr=subprocess.STDOUT)
            workers.append(process)
            indexes.append(index_path)
            atomic_json(control / f"worker-{number}.process.json",
                        {"pid": process.pid, "log": str(log_path), "spec": str(spec_path)})
        observed = monitor(workers, control)
    finally:
        for process in workers:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)
        for handle in handles:
            handle.close()
    if any(observed["worker_exits"]):
        spec = {"config": str(config_path), "experiment_name": experiment.name,
                "candidates": candidates, "index": str(control / "retry-index.json")}
        atomic_json(control / "retry.json", spec)
        run_stage([sys.executable, "-uB", "-m", "scripts.run_ood_evaluation",
                   "--worker-spec", str(control / "retry.json")], control / "serial-retry")
        indexes = [Path(spec["index"])]
    return [row for path in indexes for row in read_json(path)["results"]]


def add_l0_report(evaluation, total_assets):
    from examples.review_ood_protocol import l0_review
    rows = []
    index = read_json(evaluation / "index.json")
    for entry in index["results"]:
        if entry["method"] == "wt" and entry["status"] == "complete":
            rows.append(l0_review(read_json(Path(entry["result_path"]))))
    valid = [row for row in rows if row["l0_ssi"]["status"] == "complete"]
    metrics = {name: distribution([row["l0_ssi"][name] for row in valid])
               for name in ("mae", "rmse", "absrel", "delta1", "delta2")}
    report = {
        "status": "passed", "valid_assets": len(valid), "total_assets": total_assets,
        "available_predictions": len(rows), "minimum_coverage": .95,
        "failure_reasons": dict(Counter(row["l0_ssi"].get("reason") for row in rows
                                       if row["l0_ssi"]["status"] != "complete")),
        "metrics": metrics, "records": rows,
        "source_sha256": file_digest(REPO_ROOT / "examples/review_ood_protocol.py")}
    atomic_json(evaluation / "visible_depth_l0_review.json", report)
    lines = ["", "## WT 原像素 L0＋SSI 补充", "",
             "| 有效资产 | MAE ↓ | RMSE ↓ | AbsRel ↓ | δ1 ↑ | δ2 ↑ |",
             "| ---: | ---: | ---: | ---: | ---: | ---: |",
             f"| {len(valid)}/{total_assets} | " +
             " | ".join("—" if values["mean"] is None else f"{values['mean']:.6f}"
                        for values in metrics.values()) + " |", ""]
    with (evaluation / "summary.md").open("a") as handle:
        handle.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--inference-workers", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    if not args.experiment.resolve().is_relative_to((OUTPUT_ROOT / "experiments").resolve()):
        parser.error("Experiment must be under the project output directory")
    args.control.mkdir(parents=True, exist_ok=True)
    args.experiment.mkdir(parents=True, exist_ok=True)
    selection_path = args.dataset / "selection.json"
    selection_hash = file_digest(selection_path)
    selection = read_json(selection_path)
    splits = read_json(args.dataset / "split.json")["splits"]
    config = read_json(args.config)
    plan = frozen_plan(args.experiment, splits["eval100"], config)
    state = {
        "status": "running", "phase": "waiting_inputs", "planned_assets": len(splits["eval100"]),
        "planned_inferences": len(splits["eval100"]) * 2, "planned_evaluation_stages": len(plan["candidates"]),
        "completed_assets": 0, "selection_sha256": selection_hash,
        "dataset": str(args.dataset), "experiment": str(args.experiment),
        "source_root": str(REPO_ROOT), "runner_sha256": file_digest(Path(__file__))}
    atomic_json(args.control / "state.json", state)
    evaluation, revision = None, None
    completed = []
    with (args.experiment / ".pipeline.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            for batch in selection["batch_order"]:
                state.update(batch=batch, phase="waiting_inputs")
                atomic_json(args.control / "state.json", state)
                ready_path = args.dataset / "ready" / (batch + ".json")
                while not ready_path.exists():
                    prepare_exit = args.control / "preparation.exit"
                    if prepare_exit.exists() and int(prepare_exit.read_text()) != 0:
                        raise RuntimeError("Source preparation failed, see preparation.log")
                    time.sleep(15)
                ready = read_json(ready_path)
                inputs_path = Path(ready["inputs"])
                if ready["selection_sha256"] != selection_hash or ready["inputs_sha256"] != file_digest(inputs_path):
                    raise ValueError("Prepared batch differs from the frozen selection")
                state["phase"] = "inference"
                atomic_json(args.control / "state.json", state)
                run_stage([sys.executable, "-uB", "-m", "scripts.run_ood_inference",
                           "--inputs", str(inputs_path), "--out", str(args.experiment),
                           "--configs", str(REPO_ROOT / "configs/ood_inference.json"),
                           "--workers", str(args.inference_workers)],
                          args.control / batch / "inference", monitor_resources=False)
                if evaluation is None:
                    from examples.evaluate_baseline_v2 import BaselineEvaluator
                    evaluator = BaselineEvaluator(args.config)
                    revision = evaluator.revision
                    evaluation = evaluator.root / args.experiment.name
                    del evaluator
                    gc.collect()
                    import torch
                    torch.cuda.empty_cache()
                    evaluation.mkdir(parents=True, exist_ok=True)
                    if (evaluation / "plan.json").exists() and read_json(evaluation / "plan.json") != plan:
                        raise ValueError("Existing frozen evaluation plan differs")
                    atomic_json(evaluation / "plan.json", plan)
                    state.update(evaluation=str(evaluation), evaluation_revision=revision)
                state["phase"] = "evaluation"
                atomic_json(args.control / "state.json", state)
                new_rows = evaluate_batch(plan, splits[batch], args.config, args.experiment,
                                          args.control / batch / "evaluation")
                previous = read_json(evaluation / "index.json")["results"] if (evaluation / "index.json").exists() else []
                rows = {(row["sample_id"], row["method"], row["seed"], row["stage"]): row
                        for row in previous + new_rows}
                report = publish(args.experiment, evaluation, revision, config, list(rows.values()))
                completed.extend(splits[batch])
                state.update(completed_assets=len(set(completed)),
                             evaluated_stages=report["evaluated_stages"], status_counts=report["status_counts"])
                atomic_json(args.control / "state.json", state)
                print(f"BATCH COMPLETE {batch} assets={len(set(completed))} stages={report['evaluated_stages']}", flush=True)
            if file_digest(selection_path) != selection_hash:
                raise ValueError("Frozen selection changed during execution")
            if report["pending_stages"]:
                raise RuntimeError("Evaluation budget remains incomplete")
            state["phase"] = "audit"
            atomic_json(args.control / "state.json", state)
            run_stage([sys.executable, "-uB", "-m", "examples.validate_ood_results",
                       "--experiment", str(args.experiment)], args.control / "audit", monitor_resources=False)
            add_l0_report(evaluation, len(splits["eval100"]))
            run_stage([sys.executable, "-uB", "-m", "examples.analyze_ood_results",
                       "--experiment", str(args.experiment), "--gso-summary",
                       str(OUTPUT_ROOT / "evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/summary_seed42.json")],
                      args.control / "analysis", monitor_resources=False)
            state.update(status="complete", phase="complete")
            atomic_json(args.control / "state.json", state)
            atomic_json(args.experiment / "ood_pipeline_complete.json", state)
        except BaseException:
            state.update(status="failed", error=traceback.format_exc())
            atomic_json(args.control / "state.json", state)
            raise


if __name__ == "__main__":
    main()

