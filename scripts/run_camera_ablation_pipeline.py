"""Run both approved camera interventions with frozen source and one heavy worker."""
import argparse
import fcntl
import json
from pathlib import Path
import shlex
import sys
import traceback

from scripts.run_camera_ablation_batch import candidates, CONFIGURATIONS, PAIRS
from scripts.run_ood_pipeline import add_l0_report, run_stage
from wt.experiment import atomic_json, digest, file_digest, read_json
from wt.paths import OUTPUT_ROOT, PROCESSED_ROOT, REPO_ROOT


def read_inputs(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def freeze_json(path, value):
    if path.exists() and read_json(path) != value:
        raise ValueError(f"Frozen execution record differs: {path}")
    atomic_json(path, value)


def batches(rows, size):
    # One complete asset per dataset provides an early end-to-end control.
    yield rows[:1]
    for start in range(1, len(rows), size):
        yield rows[start:start + size]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--maximum-batches", type=int)
    args = parser.parse_args()
    config = read_json(args.config)
    control = args.control.resolve()
    control.mkdir(parents=True, exist_ok=True)
    publication = read_json(Path(config["publication_record"]))
    if publication["status"] != "pushed" or publication["commit"] != config["baseline_commit"]:
        raise ValueError("Baseline publication prerequisite not met")
    calibration = read_json(Path(config["calibration_report"]))
    if calibration["status"] != "passed" or calibration["camera_conditions"] != 60:
        raise ValueError("Camera calibration prerequisite not met")
    manifest = read_json(REPO_ROOT / "camera_source_manifest.json")
    for name, checksum in manifest["sources"].items():
        if file_digest(REPO_ROOT / name) != checksum:
            raise ValueError(f"Frozen execution source changed: {name}")
    source_hash = digest(manifest)
    freeze_json(control / "execution.json", {
        "config": config, "source_manifest_sha256": file_digest(REPO_ROOT / "camera_source_manifest.json"),
        "calibration_sha256": file_digest(Path(config["calibration_report"])),
        "source_root": str(REPO_ROOT), "source_revision": source_hash})
    datasets = {name: read_inputs(PROCESSED_ROOT / row["source"] / "eval100.jsonl")
                for name, row in config["datasets"].items()}
    grouped = {name: list(batches(rows, config["batch_size"])) for name, rows in datasets.items()}
    state = {"status": "running", "phase": "initializing", "source_root": str(REPO_ROOT),
             "seed": 42, "source_revision": source_hash, "experiments": {},
             "planned_inferences": 4000, "planned_stages": 7200,
             "new_inferences_planned": 3400}
    existing = control / "state.json"
    if existing.exists():
        state["experiments"] = read_json(existing).get("experiments", {})
    with (control / ".pipeline.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            for number in range(max(map(len, grouped.values()))):
                if args.maximum_batches is not None and number >= args.maximum_batches:
                    state.update(status="checkpoint", phase="first_batch_verified")
                    atomic_json(existing, state)
                    return 0
                batch = f"batch{number:02d}"
                for label, dataset_config in config["datasets"].items():
                    if number >= len(grouped[label]):
                        continue
                    source = PROCESSED_ROOT / dataset_config["source"]
                    selected = grouped[label][number]
                    ids = [row["sample_id"] for row in selected]
                    for condition in config["conditions"]:
                        stage_control = control / label / condition / batch
                        stage_control.mkdir(parents=True, exist_ok=True)
                        root = OUTPUT_ROOT / "experiments" / f"{config['run_id']}-{label}-{condition}"
                        state.update(batch=batch, dataset=label, condition=condition, phase="preparation")
                        atomic_json(existing, state)
                        if condition == "A0":
                            inputs = selected
                            original = OUTPUT_ROOT / "experiments" / dataset_config["control_experiment"]
                        else:
                            original = None
                            destination = PROCESSED_ROOT / config["data_subdirectory"] / label / condition
                            ids_path = stage_control / "ids.json"
                            freeze_json(ids_path, ids)
                            run_stage([sys.executable, "-uB", "-m", "examples.prepare_camera_ablation",
                                       "--source", str(source), "--destination", str(destination),
                                       "--condition", condition, "--ids-path", str(ids_path), "--batch", batch],
                                      stage_control / "preparation")
                            inputs = read_inputs(destination / f"{batch}.jsonl")
                        baseline_config = read_json(REPO_ROOT / "configs/baseline_v2.json")
                        baseline_config.update(
                            version="camera-ablation-v1", dataset=label + "-" + condition, seeds=[42],
                            output_root="evaluation/camera-ablation-v1",
                            method_configurations=[dict(method=a, config_id=b) for a, b in PAIRS],
                            camera_ablation={"condition": condition, "seed": 42,
                                             "source_revision": source_hash, "baseline_commit": config["baseline_commit"]})
                        config_path = control / label / condition / "evaluation_config.json"
                        freeze_json(config_path, baseline_config)
                        full_plan = candidates(datasets[label], root, original)
                        selected_candidates = [row for row in full_plan if row["sample_id"] in set(ids)]
                        spec = {"root": str(root), "inputs": inputs,
                                "control_source": str(original) if original else None,
                                "config": str(config_path), "experiment_name": root.name,
                                "full_plan": full_plan, "candidates": selected_candidates}
                        spec_path = stage_control / "spec.json"
                        freeze_json(spec_path, spec)
                        for kind in ("baseline", "pixal", "evaluate"):
                            state["phase"] = kind
                            atomic_json(existing, state)
                            command = [sys.executable, "-uB", "-m", "scripts.run_camera_ablation_batch",
                                       "--spec", str(spec_path), "--stage", kind]
                            if kind == "pixal":
                                shell = "cd " + shlex.quote(str(REPO_ROOT)) + \
                                    " && source compare_methods/pixal3d/env.sh && python -uB -m scripts.run_camera_ablation_batch --spec " + \
                                    shlex.quote(str(spec_path)) + " --stage pixal"
                                command = ["bash", "-c", shell]
                            exit_path = stage_control / kind / "exit.json"
                            if exit_path.exists() and read_json(exit_path).get("worker_exits") == [0]:
                                print("RESUME", label, condition, batch, kind, flush=True)
                                continue
                            run_stage(command, stage_control / kind)
                        pointer = read_json(root / "baseline_evaluation.json")
                        evaluation = Path(pointer["directory"])
                        report = read_json(evaluation / "summary.json")
                        state["experiments"][label + "/" + condition] = {
                            "root": str(root), "evaluation": str(evaluation),
                            "evaluated_stages": report["evaluated_stages"],
                            "pending_stages": report["pending_stages"], "status_counts": report["status_counts"]}
                        atomic_json(existing, state)
                        print("BATCH COMPLETE", label, condition, batch, report["status_counts"], flush=True)
            for label_condition, entry in state["experiments"].items():
                state.update(phase="audit", dataset_condition=label_condition)
                atomic_json(existing, state)
                root = Path(entry["root"])
                evaluation = Path(entry["evaluation"])
                run_stage([sys.executable, "-uB", "-m", "examples.validate_ood_results",
                           "--experiment", str(root)], control / label_condition / "audit",
                          monitor_resources=False)
                add_l0_report(evaluation, 100)
                for source_name in ("index.json", "summary.json", "audit.json", "visible_depth_l0_review.json"):
                    entry[source_name + "_sha256"] = file_digest(evaluation / source_name)
            state.update(status="complete", phase="evaluation_complete_analysis_pending")
            atomic_json(existing, state)
        except BaseException:
            state.update(status="failed", error=traceback.format_exc())
            atomic_json(existing, state)
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
