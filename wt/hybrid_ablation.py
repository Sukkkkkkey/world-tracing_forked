"""CPU planning and provenance checks for the 20-asset Hybrid pilot.

Planning requires an explicit geometry-diverse selection. It does not select
using model errors, generate missing camera inputs, or recompute WT parents.
"""
from __future__ import annotations

from pathlib import Path
import os

from wt.batch import resolve_configs, wt_settings
from wt.experiment import atomic_json, digest, file_digest, identifier, read_json, run_directory

CONDITIONS = ("A0", "A1", "B1")
PREPROCESSING = ("defaults-v1", "shared-wt-v1")
STRATEGIES = ("fill", "surface", "band")


def parameters(preprocessing):
    if preprocessing not in PREPROCESSING:
        raise ValueError("Unknown preprocessing")
    row = dict(method="wt_trellis2", config_id=preprocessing)
    if preprocessing == "shared-wt-v1":
        row.update(bg_color=[128, 128, 128], alpha_erode=0)
    return resolve_configs([row])[0]


def check_selection(camera_plan, selection):
    if selection.get("selection_basis") != "geometry_diversity":
        raise ValueError("Selection must use geometry_diversity, not model scores")
    if set(selection.get("datasets", {})) != {"GSO", "OOD"}:
        raise ValueError("Select GSO and OOD separately")
    selected = {}
    for label in ("GSO", "OOD"):
        pool = camera_plan["source_manifests"][label]["sample_ids"]
        rows = selection["datasets"][label]
        ids = [identifier(row["sample_id"]) for row in rows]
        if len(pool) != 50 or len(set(pool)) != 50:
            raise ValueError("Expected frozen camera pool of 50 unique assets")
        if len(ids) != 20 or len(set(ids)) != 20 or not set(ids) <= set(pool):
            raise ValueError("Select 20 unique assets from the camera pool")
        if any(not isinstance(r.get("reason"), str) or not r["reason"].strip()
               or not isinstance(r.get("geometry_tags"), list)
               or not r["geometry_tags"]
               or any(not isinstance(t, str) or not t.strip() for t in r["geometry_tags"])
               for r in rows):
            raise ValueError("Each selection requires a reason and geometry_tags")
        selected[label] = ids
    return selected


def output_boundary(path):
    from wt.paths import OUTPUT_ROOT
    root = Path(path).resolve()
    allowed = (OUTPUT_ROOT / "experiments").resolve()
    if root == allowed or not root.is_relative_to(allowed):
        raise ValueError("Ablation output must be a new subdirectory of project experiments")
    return root


def source_record(source, sample, cfg):
    """Pin the official result's exact parent, input and transform without inference."""
    from scripts.run_camera_ablation_modelwise import complete_run
    from wt.textured_mesh.canon import CanonicalTransform
    source = Path(source).resolve()
    if not complete_run(source, sample, cfg):
        raise ValueError(f"Official Hybrid is not complete: {source}")
    input_path = source.parents[2] / "input.json"
    record = read_json(input_path)
    image = Path(record["image"]).resolve()
    parent_meta = read_json(source / "wt_parent.json")
    prediction = (source / parent_meta["path"]).resolve()
    rgba = prediction.parent / "rgba.png"
    if prediction.name != "prediction.npz" or parent_meta["settings"] != wt_settings(cfg):
        raise ValueError("Official parent settings mismatch")
    if file_digest(prediction) != parent_meta["sha256"]:
        raise ValueError("Frozen WT parent changed")
    if file_digest(image) != record["sha256"]:
        raise ValueError("Frozen camera image changed")
    # Parent rgba is the same source RGBA, before per-model RGB compositing.
    from PIL import Image
    import numpy as np
    with Image.open(rgba) as a, Image.open(image) as b:
        if not np.array_equal(np.asarray(a.convert("RGBA")), np.asarray(b.convert("RGBA"))):
            raise ValueError("WT parent RGBA does not match camera input")
    mesh = read_json(source / "mesh.json")
    tf = CanonicalTransform(**mesh["canonical_transform"])
    if mesh["ss_res"] != 32 or mesh["pipeline_type"] != "1024_cascade":
        raise ValueError("Official grid/pipeline mismatch")
    paths = [input_path, image, prediction, rgba, source / "run.json",
             source / "config.json", source / "mesh.json", source / "wt_parent.json"]
    spatial_input = image.parent / "input.json"
    if spatial_input.exists():
        paths.append(spatial_input)
    if "camera_ablation" in record:
        spatial = Path(record["camera_ablation"]["spatial"]).resolve()
        if file_digest(spatial) != record["artifact_sha256"]["spatial.json"]:
            raise ValueError("Frozen spatial record changed")
        paths.append(spatial)
    state = read_json(source / "run.json")
    for name in ("decoded_mesh", "mesh"):
        if name not in state["artifacts"] or not (source / state["artifacts"][name]["path"]).is_file():
            raise ValueError("Official decoded/GLB missing")
    return dict(source_directory=str(source), input=record,
                parent_directory=str(prediction.parent),
                parent_reference=parent_meta,
                canonical_transform=tf.to_dict(),
                baseline_provenance=read_json(source / "config.json")["provenance"],
                pins={str(p.resolve()): file_digest(p) for p in paths})


def validate_backend_provenance(source, actual):
    """Keep checkpoint descriptor and numerical environment equal to the control."""
    baseline = source["baseline_provenance"]
    for key in ("trellis_descriptor", "dependencies", "torch"):
        if not baseline.get(key) or actual.get(key) != baseline[key]:
            raise ValueError(f"Baseline/current provenance mismatch: {key}")
    for key in ("numpy", "cuda", "matmul_allow_tf32", "cudnn_allow_tf32", "trellis_precision"):
        expected = baseline.get("environment", {})
        if key not in expected or actual.get("environment", {}).get(key) != expected[key]:
            raise ValueError(f"Baseline/current environment mismatch: {key}")


def build_plan(camera_plan_path, selection_path, root):
    from scripts.run_camera_ablation_modelwise import context_inputs, run_source
    camera_plan_path, selection_path = Path(camera_plan_path), Path(selection_path)
    camera = read_json(camera_plan_path)
    selection = read_json(selection_path)
    if selection.get("camera_plan_sha256") != file_digest(camera_plan_path):
        raise ValueError("Selection camera plan hash mismatch")
    if (camera["config"]["assets_per_dataset"] != 50 or camera["seed"] != 42
            or camera["config"]["conditions"] != list(CONDITIONS)
            or camera.get("condition_aliases") != {"B0": "A0"}):
        raise ValueError("Expected modelwise50 A0/A1/B1 camera plan")
    ids = check_selection(camera, selection)
    root = output_boundary(root)
    contexts = {(c["dataset"], c["condition"]): c for c in camera["contexts"]}
    expected = {(d, c) for d in ids for c in CONDITIONS}
    if len(contexts) != len(camera["contexts"]) or set(contexts) != expected:
        raise ValueError("Camera contexts must cover each dataset/condition exactly once")
    jobs, sources = [], {}
    for label, condition in sorted(expected):
        context = contexts[label, condition]
        for source_root in (context["root"], context.get("control_source")):
            if source_root and (root.is_relative_to(Path(source_root).resolve())
                                or Path(source_root).resolve().is_relative_to(root)):
                raise ValueError("Ablation output overlaps source experiment")
        samples = {s["sample_id"]: s for s in context_inputs(context, require=True)}
        experiment = root / f"{root.name}-{label}-{condition}"
        for sid in ids[label]:
            for prep in PREPROCESSING:
                cfg = parameters(prep)
                source, complete = run_source(context, samples[sid], cfg)
                if not complete:
                    raise ValueError(f"Wait for camera Hybrid: {label}/{condition}/{sid}/{prep}")
                key = f"{label}/{condition}/{sid}/{prep}"
                sources[key] = source_record(source, samples[sid], cfg)
                sources[key]["evaluation_roots"] = list(dict.fromkeys(
                    [context["root"], str(Path(source).parents[4])]))
                for strategy in STRATEGIES:
                    config_id = prep if strategy == "fill" else f"{strategy}-{prep}"
                    destination = source if strategy == "fill" else run_directory(
                        experiment, sid, "wt_trellis2", config_id, 42)
                    jobs.append(dict(dataset=label, condition=condition, sample_id=sid,
                        preprocessing=prep, strategy=strategy, seed=42, source_key=key,
                        config_id=config_id, experiment_root=str(experiment),
                        destination=str(destination), parameters=dict(cfg, config_id=config_id)))
    plan = dict(version="hybrid-ablation-pilot-v1", root=str(root), seed=42,
                selection=selection, selected_ids=ids, condition_aliases={"B0": "A0"},
                camera_plan=str(camera_plan_path.resolve()),
                camera_plan_sha256=file_digest(camera_plan_path),
                selection_sha256=file_digest(selection_path), sources=sources, jobs=jobs,
                budget=dict(outputs=720, reused_official=240, new_mesh=480, evaluation_stages=1440))
    plan["plan_hash"] = digest(plan)
    return plan


def validate_plan(plan):
    payload = {k: v for k, v in plan.items() if k != "plan_hash"}
    if plan.get("plan_hash") != digest(payload):
        raise ValueError("Frozen ablation plan changed")
    if plan.get("version") != "hybrid-ablation-pilot-v1" or plan["seed"] != 42:
        raise ValueError("Unsupported ablation plan")
    root = output_boundary(plan["root"])
    expected = {(d, c, sid, p, v) for d, ids in plan["selected_ids"].items()
                for sid in ids for c in CONDITIONS for p in PREPROCESSING for v in STRATEGIES}
    actual = {(j["dataset"], j["condition"], j["sample_id"], j["preprocessing"], j["strategy"])
              for j in plan["jobs"]}
    if len(plan["jobs"]) != 720 or len(actual) != 720 or actual != expected:
        raise ValueError("Incomplete or duplicate factorial jobs")
    for job in plan["jobs"]:
        source = plan["sources"][job["source_key"]]
        if job["strategy"] == "fill":
            if job["destination"] != source["source_directory"]:
                raise ValueError("Official result must be referenced, not regenerated")
        else:
            dest = Path(job["destination"]).resolve()
            if not dest.is_relative_to(root) or dest.is_relative_to(Path(source["source_directory"])):
                raise ValueError("Unsafe ablation destination")
    return root


def validate_sources(plan):
    checked = {}
    for source in plan["sources"].values():
        for path, checksum in source["pins"].items():
            if path in checked and checked[path] != checksum:
                raise ValueError("Conflicting source pins")
            if path not in checked:
                if file_digest(Path(path)) != checksum:
                    raise ValueError(f"Frozen source changed: {path}")
                checked[path] = checksum


def resolved_job(plan, job):
    return dict(plan["sources"][job["source_key"]], **job)


def evaluation_candidates(plan):
    """Use existing v0.5 evaluator contracts, keeping camera conditions separate."""
    groups = {}
    for job in plan["jobs"]:
        key = (job["dataset"], job["condition"])
        rows = groups.setdefault(key, [])
        for stage in ("decoded", "glb"):
            rows.append(dict(sample_id=job["sample_id"], method="wt_trellis2",
                config_id=job["config_id"], seed=42, stage=stage,
                source_directory=job["destination"], strategy=job["strategy"],
                preprocessing=job["preprocessing"]))
    return groups


def save_plan(path, plan):
    path = Path(path)
    if path.exists():
        if read_json(path) != plan:
            raise ValueError("Refusing to replace a frozen ablation plan")
        return
    atomic_json(path, plan)


def assert_camera_idle(proc=Path("/proc")):
    """Refuse concurrent GPU work; inspecting /proc creates no CUDA context."""
    markers = ("run_camera_ablation_modelwise", "run_camera_ablation_parallel_pipeline",
               "run_camera_ablation_pipeline", "run_camera_ablation_batch",
               "run_camera_parallel_evaluation", "continue_camera_ablation",
               "examples.prepare_camera_ablation")
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            parts = (entry / "cmdline").read_bytes().split(b"\0")
            args = [p.decode(errors="replace") for p in parts if p]
        except (OSError, PermissionError):
            continue
        # Check executable/module argument basenames, not shell command strings.
        if any(any(Path(arg).name.removesuffix(".py") == m or arg == m or arg.endswith("." + m) for m in markers)
               for arg in args):
            raise RuntimeError(f"camera_ablation still active (PID {entry.name}); GPU work refused")
