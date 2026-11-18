"""Paused, model-major camera queue; reuse A0 as B0 and keep frozen inference code."""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout, redirect_stderr
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

CONFIGURATIONS = [
    dict(method="wt", config_id="defaults-v1"),
    dict(method="trellis2", config_id="defaults-v1"),
    dict(method="wt_trellis2", config_id="defaults-v1"),
    dict(method="wt_trellis2", config_id="shared-wt-v1", bg_color=[128]*3, alpha_erode=0),
]
PHASES = ("wt", "trellis2", "hybrid-default", "hybrid-shared")
PHASE_CONFIG = dict(zip(PHASES, CONFIGURATIONS))

def read(path):
    return json.loads(Path(path).read_text())

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)

def freeze(path, value):
    if Path(path).exists() and read(path) != value:
        raise ValueError(f"Frozen plan changed: {path}")
    save(path, value)

def select_inputs(rows, limit):
    if len(rows) < limit or limit <= 0:
        raise ValueError("Insufficient assets")
    ids = [r["sample_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate sample ID")
    return rows[:limit]

def bootstrap(config):
    root = Path(config["source_root"]).resolve()
    manifest = read(root / "camera_source_manifest.json")
    for name, expected in manifest["sources"].items():
        if sha(root / name) != expected:
            raise ValueError(f"Frozen numerical source changed: {name}")
    sys.path.insert(0, str(root))
    from wt.paths import REPO_ROOT
    if REPO_ROOT.resolve() != root:
        raise ValueError("Run with the frozen source first on PYTHONPATH")
    return root

def make_plan(config, control):
    from wt.paths import OUTPUT_ROOT, PROCESSED_ROOT
    if config["seed"] != 42 or config["assets_per_dataset"] != 50:
        raise ValueError("Expected approved seed 42 and 50 assets")
    if config["conditions"] != ["A0", "A1", "B1"] or config["condition_aliases"] != {"B0": "A0"}:
        raise ValueError("Expected unique A0/A1/B1 with B0 alias")
    if config["configurations"] != CONFIGURATIONS or config["phase_order"] != list(PHASES):
        raise ValueError("Method order/configurations changed")
    contexts, sources = [], {}
    for label, dataset in config["datasets"].items():
        source = PROCESSED_ROOT / dataset["source"]
        manifest = source / "eval100.jsonl"
        rows = select_inputs([json.loads(l) for l in manifest.read_text().splitlines() if l], 50)
        sources[label] = dict(manifest=str(manifest), sha256=sha(manifest),
                              sample_ids=[r["sample_id"] for r in rows])
        freeze(control / label / "ids.json", sources[label]["sample_ids"])
        for condition in config["conditions"]:
            contexts.append(dict(dataset=label, condition=condition, source=str(source),
                source_inputs=rows,
                data=str(source if condition == "A0" else
                         PROCESSED_ROOT / config["data_subdirectory"] / label / condition),
                root=str(OUTPUT_ROOT / "experiments" / f"{config['run_id']}-{label}-{condition}"),
                control_source=str(OUTPUT_ROOT / "experiments" / dataset["control_experiment"])
                               if condition == "A0" else None,
                evaluation_config=str(Path(config["old_control"]) / label / condition / "evaluation_config.json")))
    plan = dict(config=config, source_manifests=sources, contexts=contexts,
                condition_aliases=config["condition_aliases"], unique_method_outputs=1200,
                unique_evaluation_stages=2100, labeled_evaluation_stages=2800,
                seed=42, planned_assets_per_dataset=50,
                parent_policy={"defaults-v1": "black background, alpha_erode=2",
                               "shared-wt-v1": "exact independent WT prediction, gray background, alpha_erode=0"})
    freeze(control / "plan.json", plan)
    return plan

def context_inputs(context, require=False):
    if context["condition"] == "A0":
        return context["source_inputs"]
    rows = []
    for original in context["source_inputs"]:
        path = Path(context["data"]) / "samples" / original["sample_id"] / "input.json"
        if path.exists():
            rows.append(read(path))
        elif require:
            raise ValueError(f"Input not prepared: {path}")
        else:
            rows.append(dict(sample_id=original["sample_id"], image=None))
    return rows

def complete_run(path, sample, cfg):
    state_path = Path(path) / "run.json"
    if not state_path.exists() or read(state_path).get("status") != "complete":
        return False
    state = read(state_path)
    if (state.get("seed") != 42 or state.get("method") != cfg["method"]
            or state.get("config_id") != cfg["config_id"]
            or read(Path(path) / "config.json")["parameters"] != cfg):
        raise ValueError(f"Completed run configuration mismatch: {path}")
    source_input = read(Path(path).parents[2] / "input.json")
    expected = sample.get("sha256") or sample.get("artifact_sha256", {}).get("input.png")
    if expected is None and sample.get("image"):
        expected = sha(sample["image"])
    if expected is None or source_input["sha256"] != expected or state["input_sha256"] != expected:
        raise ValueError(f"Completed run input mismatch: {path}")
    artifacts = state.get("artifacts", {})
    if not artifacts or not all((Path(path) / a["path"]).is_file() for a in artifacts.values()):
        raise ValueError(f"Completed run has missing artifacts: {path}")
    return True

def run_source(context, sample, cfg):
    from wt.experiment import run_directory
    roots = ([context["control_source"]] if context.get("control_source") else []) + [context["root"]]
    for root in roots:
        path = run_directory(Path(root), sample["sample_id"], cfg["method"], cfg["config_id"], 42)
        if complete_run(path, sample, cfg):
            return path, True
    return run_directory(Path(context["root"]), sample["sample_id"], cfg["method"], cfg["config_id"], 42), False

def inventory(plan, control):
    from wt.batch import resolve_configs
    rows = []
    for context in plan["contexts"]:
        inputs = context_inputs(context)
        for cfg in resolve_configs(CONFIGURATIONS):
            complete = 0
            for sample in inputs:
                complete += run_source(context, sample, cfg)[1]
            stages = 1 if cfg["method"] == "wt" else 2
            rows.append(dict(dataset=context["dataset"], condition=context["condition"],
                method=cfg["method"], config_id=cfg["config_id"], planned=50,
                reusable=complete, pending=50-complete, stages_per_output=stages))
    value = dict(rows=rows, reusable_outputs=sum(r["reusable"] for r in rows),
                 pending_outputs=sum(r["pending"] for r in rows), unique_outputs=1200,
                 pending_output_stages=sum(r["pending"]*r["stages_per_output"] for r in rows),
                 note="Pending evaluation must additionally check existing indexes; internal WT parents excluded.")
    save(control / "inventory.json", value)
    return value

def prepare(plan, control):
    from wt.paths import REPO_ROOT
    for context in plan["contexts"]:
        if context["condition"] == "A0":
            continue
        command = [sys.executable, "-uB", "-m", "examples.prepare_camera_ablation",
            "--source", context["source"], "--destination", context["data"],
            "--condition", context["condition"], "--ids-path",
            str(control / context["dataset"] / "ids.json"), "--batch", "modelwise50-20261118"]
        subprocess.run(command, cwd=REPO_ROOT, check=True)

def cache_valid(path, key):
    try:
        info = read(path / "complete.json")
        return (info["cache_key"] == key and sha(path / "prediction.npz") == info["sha256"]
                and sha(path / "rgba.png") == info["rgba_sha256"])
    except (OSError, KeyError, ValueError):
        return False

def parent_cache(context, sample, cfg, backend):
    from wt.batch import cache_key
    sample = dict(sample, sha256=sha(sample["image"]))
    key = cache_key(sample, cfg, 42, backend.provenance)
    return Path(context["root"]) / "_cache" / "wt" / key, key

def ensure_parent(context, sample, cfg, backend):
    from wt.batch import resolve_configs, wt_settings
    directory, key = parent_cache(context, sample, cfg, backend)
    shared = cfg["config_id"] == "shared-wt-v1"
    source = None
    if shared:
        wt_cfg = resolve_configs([CONFIGURATIONS[0]])[0]
        source, complete = run_source(context, sample, wt_cfg)
        if not complete or wt_settings(wt_cfg) != wt_settings(cfg):
            raise ValueError("Shared Hybrid requires completed, matching independent WT")
        source = source / "prediction.npz"
    if cache_valid(directory, key):
        if source is not None and sha(source) != sha(directory / "prediction.npz"):
            raise ValueError("Existing shared parent differs from independent WT")
        return directory
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    if source is not None:
        shutil.copyfile(source, directory / "prediction.npz")
        shutil.copyfile(sample["image"], directory / "rgba.png")
    else:
        backend.load_wt()
        with (directory / "run.log").open("w") as log, redirect_stdout(log), redirect_stderr(log):
            backend.predict_wt(Path(sample["image"]), cfg, 42, directory)
    save(directory / "complete.json", dict(cache_key=key, sha256=sha(directory / "prediction.npz"),
         rgba_sha256=sha(directory / "rgba.png"), seconds=time.monotonic()-started,
         **({"source":str(source), "reuse":"exact independent WT"} if source else {})))
    return directory

def resident_backend(base, phase):
    class Resident(base):
        def load_wt(self):
            if phase != "wt":
                raise RuntimeError("WT parents must finish before mesh phases")
            if self.model is None:
                super().load_wt()
        def unload_wt(self):
            pass
        def load_trellis(self, include_stage1, modes):
            if phase == "wt":
                raise RuntimeError("Mesh inference attempted during WT phase")
            if self.pipeline is None:
                super().load_trellis(include_stage1, modes)
        def unload_trellis(self):
            pass
        def close(self):
            super().unload_trellis()
            super().unload_wt()
    return Resident

def inference(plan, phase, backend=None):
    from wt.batch import resolve_configs, run_batch
    from scripts.run_camera_ablation_batch import initialize
    from wt.camera_ablation import CameraMemoryBackend
    from wt.paths import WEIGHTS_ROOT
    cfg = resolve_configs([PHASE_CONFIG[phase]])[0]
    contexts = [(c, context_inputs(c, require=True)) for c in plan["contexts"]]
    if backend is None:
        backend = resident_backend(CameraMemoryBackend, phase)(
            WEIGHTS_ROOT / "huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt",
            WEIGHTS_ROOT / "local-pipelines/TRELLIS.2")
    try:
        if phase.startswith("hybrid"):
            for context, inputs in contexts:
                for sample in inputs:
                    if run_source(context, sample, cfg)[1]:
                        continue
                    parent, key = parent_cache(context, sample, cfg, backend)
                    if not cache_valid(parent, key):
                        raise ValueError(f"WT phase incomplete: {parent}")
                    if phase == "hybrid-shared":
                        wt_cfg = resolve_configs([CONFIGURATIONS[0]])[0]
                        wt_source, done = run_source(context, sample, wt_cfg)
                        if not done or sha(wt_source/"prediction.npz") != sha(parent/"prediction.npz"):
                            raise ValueError("Shared parent is not the exact independent WT")
        for context, inputs in contexts:
            pending = [s for s in inputs if not run_source(context, s, cfg)[1]]
            initialize(Path(context["root"]), inputs)
            if pending and run_batch(Path(context["root"]), pending, [cfg], [42], backend):
                raise RuntimeError(f"Inference failed: {context['dataset']}/{context['condition']}/{phase}")
            if phase == "wt":
                for hybrid in resolve_configs(CONFIGURATIONS[2:]):
                    for sample in inputs:
                        if not run_source(context, sample, hybrid)[1]:
                            ensure_parent(context, sample, hybrid, backend)
    finally:
        backend.close()

def selected_candidates(context):
    from wt.batch import resolve_configs
    candidates = []
    for sample in context_inputs(context, require=True):
        for cfg in resolve_configs(CONFIGURATIONS):
            source, complete = run_source(context, sample, cfg)
            if not complete:
                raise ValueError(f"Inference incomplete: {source}")
            for stage in (["points"] if cfg["method"] == "wt" else ["decoded", "glb"]):
                candidates.append(dict(sample_id=sample["sample_id"], method=cfg["method"],
                    config_id=cfg["config_id"], seed=42, stage=stage, source_directory=str(source)))
    return candidates

def evaluate(plan, control):
    from evaluation.camera_summary import candidate_key, summary
    from examples.summarize_baseline_v2 import markdown, write_render_index
    old_state = read(Path(plan["config"]["old_control"]) / "state.json")
    state = dict(status="running", phase="evaluation", seed=42, planned_assets_per_dataset=50,
                 condition_aliases=plan["condition_aliases"], source_revision=old_state["source_revision"],
                 experiments={})
    helper = Path(plan["config"]["support_root"]) / "run_camera_parallel_evaluation.py"
    for context in plan["contexts"]:
        label = context["dataset"] + "/" + context["condition"]
        old = Path(old_state["experiments"][label]["evaluation"])
        prior_plan = read(old / "plan.json")
        selected = selected_candidates(context)
        existing = {candidate_key(r):r for r in read(old/"index.json")["results"]}
        missing = [r for r in selected if candidate_key(r) not in existing
                   or existing[candidate_key(r)].get("status") != "complete"]
        if missing:
            spec = dict(root=context["root"], config=context["evaluation_config"],
                experiment_name=Path(context["root"]).name,
                full_plan=prior_plan["candidates"], candidates=missing)
            spec_path = control / "evaluation" / label / "spec.json"
            save(spec_path, spec)
            subprocess.run([sys.executable, "-uB", str(helper), "--spec", str(spec_path),
                "--control", str(spec_path.parent/"workers"), "--workers", "2"],
                cwd=plan["config"]["source_root"], check=True)
        original = read(old/"index.json")
        chosen = {candidate_key(r) for r in selected}
        rows = [r for r in original["results"] if candidate_key(r) in chosen]
        if len(rows) != len(chosen) or any(r.get("status") != "complete" for r in rows):
            raise ValueError(f"Evaluation incomplete: {label}")
        destination = control / "cohort-evaluation" / label
        freeze(destination/"plan.json", dict(prior_plan, candidates=selected))
        save(destination/"index.json", dict(original, results=rows))
        report = summary(destination)
        save(destination/"summary.json", report)
        (destination/"summary.md").write_text(markdown(report))
        write_render_index(destination, report)
        state["experiments"][label] = dict(root=context["root"], evaluation=str(destination),
                                          evaluated_stages=len(rows), pending_stages=0)
        if context["condition"] == "A0":
            state["experiments"][context["dataset"]+"/B0"] = dict(
                state["experiments"][label], alias_of=label, independent_repeat=False)
        save(control/"cohort-state.json",state)
    state.update(status="complete", phase="evaluation_complete_analysis_pending")
    save(control/"cohort-state.json",state)
    return state

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--phase", choices=("plan","all","prepare",*PHASES,"evaluate"), default="plan")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.phase != "plan" and not args.execute:
        parser.error("Queue is paused; execution requires explicit --execute")
    config = read(args.config)
    for key, value in {"CUDA_VISIBLE_DEVICES":"0", "PYTHONHASHSEED":"42", "OMP_NUM_THREADS":"8", "OPENBLAS_NUM_THREADS":"8", "MKL_NUM_THREADS":"8", "PYTORCH_CUDA_ALLOC_CONF":"expandable_segments:True"}.items():
        os.environ[key] = value
    root = bootstrap(config)
    control = args.control.resolve()
    if not control.is_relative_to(Path(config["project_root"]).resolve()/".runtime"):
        raise ValueError("Control must be inside the project .runtime directory")
    control.mkdir(parents=True, exist_ok=True)
    freeze(control/"orchestration.json", {
        "runner": str(Path(__file__).resolve()), "runner_sha256": sha(__file__),
        "config": str(args.config.resolve()), "config_sha256": sha(args.config),
        "numerical_source_manifest_sha256": sha(root/"camera_source_manifest.json")})
    plan = make_plan(config, control)
    if args.phase == "plan":
        if (control/"state.json").exists() and read(control/"state.json").get("status") == "running":
            raise ValueError("Cannot replace an active queue state with a plan")
        value = inventory(plan, control)
        save(control/"state.json", dict(status="paused_ready", phase="planned",
            planned_assets_per_dataset=50, unique_outputs=1200, unique_stages=2100,
            condition_aliases={"B0":"A0"}, inventory=str(control/"inventory.json")))
        print(json.dumps(value), flush=True)
        return 0
    lock_name = ".controller.lock" if args.phase == "all" else ".phase.lock"
    with (control/lock_name).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        save(control/"execution.json", dict(config_sha256=sha(args.config),
            script=str(Path(__file__).resolve()),script_sha256=sha(__file__),
            source_manifest_sha256=sha(root/"camera_source_manifest.json"),
            phase_order=list(PHASES), condition_aliases={"B0":"A0"}))
        if args.phase == "all":
            try:
                for phase in ("prepare",*PHASES,"evaluate"):
                    save(control/"state.json",dict(status="running",phase=phase,controller_pid=os.getpid()))
                    subprocess.run([sys.executable,"-uB",str(Path(__file__).resolve()),
                        "--config",str(args.config.resolve()),"--control",str(control),
                        "--phase",phase,"--execute"],cwd=root,check=True)
                save(control/"state.json",dict(status="complete",phase="evaluation_complete_analysis_pending"))
            except BaseException:
                save(control/"state.json",dict(status="failed",phase=phase,error=traceback.format_exc()))
                raise
        elif args.phase == "prepare":
            prepare(plan,control)
        elif args.phase == "evaluate":
            evaluate(plan,control)
        else:
            inference(plan,args.phase)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
