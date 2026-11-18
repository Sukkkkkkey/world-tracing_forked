"""Run one camera-ablation batch with frozen inputs and both Hybrid configurations."""
import argparse
import json
from pathlib import Path
import shutil

from wt.experiment import SCHEMA_VERSION, atomic_json, file_digest, read_json, run_directory
from wt.paths import OUTPUT_ROOT, REPO_ROOT, WEIGHTS_ROOT
from evaluation.camera_summary import candidate_key


CONFIGURATIONS = [
    {"method": "wt", "config_id": "defaults-v1"},
    {"method": "trellis2", "config_id": "defaults-v1"},
    {"method": "wt_trellis2", "config_id": "defaults-v1"},
    {"method": "wt_trellis2", "config_id": "shared-wt-v1",
     "bg_color": [128, 128, 128], "alpha_erode": 0},
]
PAIRS = [(row["method"], row["config_id"]) for row in CONFIGURATIONS] + [
    ("pixal3d", "resolution1024-v1")]



def initialize(root, inputs):
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / "experiment.json", {"schema_version": SCHEMA_VERSION, "experiment_id": root.name})
    for sample in inputs:
        value = dict(sample, sha256=file_digest(Path(sample["image"])))
        path = root / "samples" / sample["sample_id"] / "input.json"
        if path.exists() and read_json(path) != value:
            raise ValueError(f"Frozen experiment input changed: {path}")
        atomic_json(path, value)


def is_complete(directory):
    path = directory / "run.json"
    return path.exists() and read_json(path)["status"] == "complete"


def inference(inputs, root, control_source, kind):
    initialize(root, inputs)
    if kind == "pixal":
        from wt.camera_ablation import CameraPixalBackend
        from wt.baselines.pixal3d_batch import run_batch
        selected = [s["sample_id"] for s in inputs if control_source is None or not is_complete(
            run_directory(control_source, s["sample_id"], "pixal3d", "resolution1024-v1", 42))]
        if not selected:
            return 0
        backend = CameraPixalBackend(WEIGHTS_ROOT / "pixal3d/manifest.json")
        backend.provenance["camera_ablation_adapter_sha256"] = file_digest(REPO_ROOT / "wt/camera_ablation.py")
        return run_batch(root, backend, selected, 42)
    from wt.batch import cache_key, resolve_configs, run_batch
    from wt.camera_ablation import CameraMemoryBackend
    backend = CameraMemoryBackend(
        WEIGHTS_ROOT / "huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt",
        WEIGHTS_ROOT / "local-pipelines/TRELLIS.2")
    configurations = resolve_configs(CONFIGURATIONS)
    if control_source is None:
        return run_batch(root, inputs, configurations, [42], backend)
    # A0 imports the exact independent WT output as the shared-WT parent.
    shared = next(c for c in configurations if c["config_id"] == "shared-wt-v1")
    for value in inputs:
        sample = dict(value, sha256=file_digest(Path(value["image"])))
        original = run_directory(control_source, sample["sample_id"], "wt", "defaults-v1", 42)
        if not is_complete(original):
            raise ValueError(f"Missing frozen A0 WT: {original}")
        previous_input = read_json(original.parents[2] / "input.json")
        previous_config = read_json(original / "config.json")["parameters"]
        if previous_input["sha256"] != sample["sha256"]:
            raise ValueError("Frozen A0 WT input differs")
        if any(previous_config[name] != shared[name] for name in ("wt_steps", "bg_color", "alpha_erode")):
            raise ValueError("Frozen A0 WT preprocessing differs from shared parent")
        if read_json(original / "run.json")["seed"] != 42:
            raise ValueError("Frozen A0 WT seed differs")
        key = cache_key(sample, shared, 42, backend.provenance)
        cache = root / "_cache/wt" / key
        cache.mkdir(parents=True, exist_ok=True)
        source = original / "prediction.npz"
        if not (cache / "prediction.npz").exists():
            shutil.copy2(source, cache / "prediction.npz")
            shutil.copy2(Path(sample["image"]), cache / "rgba.png")
        if file_digest(cache / "prediction.npz") != file_digest(source):
            raise ValueError("Shared WT parent differs from the frozen baseline")
        atomic_json(cache / "complete.json", {
            "cache_key": key, "sha256": file_digest(source),
            "rgba_sha256": file_digest(cache / "rgba.png"), "seconds": 0,
            "source": str(source), "reuse": "exact frozen A0 independent WT"})
    groups = {}
    for sample in inputs:
        active = tuple(i for i, c in enumerate(configurations) if not is_complete(
            run_directory(control_source, sample["sample_id"], c["method"], c["config_id"], 42)))
        if active:
            groups.setdefault(active, []).append(sample)
    return sum(run_batch(root, rows, [configurations[i] for i in active], [42], backend)
               for active, rows in groups.items())


def candidates(inputs, root, control_source):
    rows = []
    for sample in inputs:
        for method, configuration in PAIRS:
            source = run_directory(root, sample["sample_id"], method, configuration, 42)
            if control_source is not None:
                previous = run_directory(control_source, sample["sample_id"], method, configuration, 42)
                if is_complete(previous):
                    source = previous
            for stage in (["points"] if method == "wt" else ["decoded", "glb"]):
                rows.append(dict(sample_id=sample["sample_id"], method=method, config_id=configuration,
                                 seed=42, stage=stage, source_directory=str(source)))
    return rows


def evaluate(spec):
    from examples.evaluate_baseline_v2 import BaselineEvaluator
    from scripts.run_ood_evaluation import index_row
    from examples.summarize_baseline_v2 import markdown, write_render_index
    from evaluation.camera_summary import summary
    evaluator = BaselineEvaluator(Path(spec["config"]))
    output = evaluator.root / spec["experiment_name"]
    output.mkdir(parents=True, exist_ok=True)
    plan = {"config": evaluator.config, "selected_seeds": [42],
            "candidates": spec["full_plan"], "mode": "fixed_seed"}
    if (output / "plan.json").exists() and read_json(output / "plan.json") != plan:
        raise ValueError("Frozen camera-ablation plan changed")
    atomic_json(output / "plan.json", plan)
    rows = {candidate_key(row): row for row in (
        read_json(output / "index.json")["results"] if (output / "index.json").exists() else [])}
    failures = 0
    for candidate in spec["candidates"]:
        directory = Path(candidate["source_directory"])
        if not is_complete(directory):
            raise ValueError(f"Finish inference recovery before evaluation: {directory}")
        result = evaluator.evaluate(directory, candidate["stage"], spec["experiment_name"])
        for value in [*evaluator.index_updates, result]:
            row = index_row(value)
            rows[candidate_key(row)] = row
        evaluator.index_updates.clear()
        atomic_json(output / "index.json", {"revision": evaluator.revision,
                    "config": evaluator.config, "results": list(rows.values())})
        print(candidate_key(candidate), result["status"], flush=True)
        failures += result["status"] != "complete"
    report = summary(output)
    atomic_json(output / "summary.json", report)
    (output / "summary.md").write_text(markdown(report))
    write_render_index(output, report)
    atomic_json(Path(spec["root"]) / "baseline_evaluation.json", {
        "revision": evaluator.revision, "directory": str(output),
        "index_sha256": file_digest(output / "index.json"), "summary": str(output / "summary.json")})
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--stage", choices=("baseline", "pixal", "evaluate"), required=True)
    args = parser.parse_args()
    spec = read_json(args.spec)
    root = Path(spec["root"])
    if not root.resolve().is_relative_to((OUTPUT_ROOT / "experiments").resolve()):
        raise ValueError("Experiment output outside project storage")
    if args.stage == "evaluate":
        return int(evaluate(spec) != 0)
    return int(inference(spec["inputs"], root,
                        Path(spec["control_source"]) if spec.get("control_source") else None,
                        args.stage) != 0)


if __name__ == "__main__":
    raise SystemExit(main())
