"""Hybrid pilot smoke tests: synthetic CPU artifacts, no models or CUDA."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from wt.batch import InferenceBackend
from wt.experiment import atomic_json, digest, file_digest, read_json, run_directory
from wt.hybrid_ablation import (CONDITIONS, PREPROCESSING, assert_camera_idle, build_plan,
    check_selection, evaluation_candidates, parameters, source_record, validate_plan, validate_sources, validate_backend_provenance)
from wt.textured_mesh.canon import compute_canonical_transform, aggregate_camera_cloud
from wt.textured_mesh.voxelise import surface_voxels, v4_ray_fill
from scripts.run_hybrid_ablation import completed_job, execute_plan


PROVENANCE = dict(trellis_descriptor="fixture", dependencies="fixture", torch="fixture",
                  environment=dict(numpy="fixture", cuda="fixture", matmul_allow_tf32=False,
                                   cudnn_allow_tf32=True, trellis_precision="checkpoint-config"))


def cloud(cells, res=16):
    xyz = (np.asarray(cells, dtype=np.float32) + 0.5) / res - 0.5
    xyz = xyz.reshape(1, -1, 1, 3)
    return xyz, np.ones(xyz.shape[:-1], dtype=bool)


def test_surface_does_not_connect_adjacent_layers():
    xyz, mask = cloud([(3, 8, 8), (12, 8, 8)])
    xyz, mask = xyz.reshape(2, 1, 1, 3), mask.reshape(2, 1, 1)
    coords, count = surface_voxels(xyz, mask, lambda p: p, 16)
    assert count == 2
    assert coords.tolist() == [[3, 8, 8], [12, 8, 8]]
    band, n = surface_voxels(xyz, mask, lambda p: p, 16, band_radius=1)
    assert n == 14
    assert [8, 8, 8] not in band.tolist()


def test_closed_surface_keeps_empty_interior():
    cells = [(x, y, z) for x in range(4, 9) for y in range(4, 9) for z in range(4, 9)
             if 4 in (x, y, z) or 8 in (x, y, z)]
    xyz, mask = cloud(cells)
    raw, n = surface_voxels(xyz, mask, lambda p: p, 16)
    filled, count = v4_ray_fill(xyz, mask, lambda p: p, 16, ray_steps=0, close_iters=0)
    assert n == 98 and count == 125
    assert [6, 6, 6] not in raw.tolist() and [6, 6, 6] in filled.tolist()
    band, _ = surface_voxels(xyz, mask, lambda p: p, 16, band_radius=1)
    assert [6, 6, 6] not in band.tolist()


def test_band_has_six_neighbors_not_diagonals_and_no_wraparound():
    xyz, mask = cloud([(0, 0, 0), (0, 0, 0)])
    coords, n = surface_voxels(xyz, mask, lambda p: p, 16, band_radius=1)
    assert coords.tolist() == [[0, 0, 0], [0, 0, 1], [0, 1, 0], [1, 0, 0]]
    assert n == 4 and coords.dtype == np.int32


def test_masks_nonfinite_and_boundary_filtering():
    xyz = np.array([[[[0, 0, 0], [0.5, 0, 0], [-0.5, 0, 0],
                      [np.nan, 0, 0], [0.2, 0.2, 0.2]]]], dtype=np.float32)
    mask = np.array([[[True, True, True, True, False]]])
    before = xyz.copy()
    coords, n = surface_voxels(xyz, mask, lambda p: p, 32)
    assert n == 1 and coords.tolist() == [[16, 16, 16]]
    np.testing.assert_equal(xyz, before)
    coords, n = surface_voxels(xyz, np.zeros_like(mask), lambda p: p, 32)
    assert coords.shape == (0, 3) and n == 0


@pytest.mark.parametrize("kwargs", [{"res": 0}, {"res": True}, {"band_radius": 2},
                                    {"band_radius": True}, {"band_radius": -1}])
def test_bad_surface_arguments(kwargs):
    xyz, mask = cloud([(4, 4, 4)])
    with pytest.raises(ValueError):
        surface_voxels(xyz, mask, lambda p: p, **kwargs)


def test_default_hook_preserves_official_coords_exactly():
    xyz, mask = cloud([(2, 5, 6), (9, 6, 5), (9, 5, 8)])
    backend = InferenceBackend.__new__(InferenceBackend)
    cfg = parameters("defaults-v1")
    tf, coords, count = backend.hybrid_structure(xyz, mask, cfg, 32)
    old_tf = compute_canonical_transform(aggregate_camera_cloud(xyz, mask))
    expected, n = v4_ray_fill(xyz, mask, old_tf.apply, 32, ray_steps=4)
    assert tf.to_dict() == old_tf.to_dict()
    assert count == n
    np.testing.assert_array_equal(coords, expected)


def test_backend_uses_frozen_transform_and_rejects_empty():
    from wt.hybrid_ablation_backend import HybridAblationBackend
    backend = HybridAblationBackend.__new__(HybridAblationBackend)
    cfg = parameters("defaults-v1")
    job = dict(strategy="surface", parameters=cfg,
               canonical_transform=dict(centroid=[0, 0, 0], scale=1, axis_map="identity"))
    backend.configure_job(job)
    xyz = np.zeros((6, 504, 504, 3), dtype=np.float32)
    mask = np.zeros(xyz.shape[:-1], dtype=bool)
    mask[0, 0, 0] = True
    tf, coords, n = backend.hybrid_structure(xyz, mask, cfg, 32)
    assert coords.tolist() == [[16, 16, 16]] and n == 1
    assert tf.to_dict() == job["canonical_transform"]
    with pytest.raises(ValueError, match="Empty"):
        backend.hybrid_structure(xyz, np.zeros_like(mask), cfg, 32)
    with pytest.raises(RuntimeError, match="frozen"):
        backend.load_wt()


@pytest.fixture(scope="module")
def pilot(tmp_path_factory):
    import wt.paths
    base = tmp_path_factory.mktemp("hybrid")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wt.paths, "OUTPUT_ROOT", base)
        contexts, source_manifests, selected = [], {}, {}
        for dataset in ("GSO", "OOD"):
            ids = [f"{dataset}_{i:02}" for i in range(50)]
            source_manifests[dataset] = {"sample_ids": ids}
            selected[dataset] = [dict(sample_id=s, reason="synthetic geometry coverage",
                                     geometry_tags=["thin" if i % 2 else "compact"])
                                 for i, s in enumerate(ids[:20])]
            for condition in CONDITIONS:
                data = base / "data" / dataset / condition
                root = base / "experiments" / f"camera-{dataset}-{condition}"
                rows = []
                for sid in ids:
                    folder = data / "samples" / sid
                    folder.mkdir(parents=True)
                    image = folder / "input.png"
                    Image.new("RGBA", (4, 4), (20, 40, 60, 255)).save(image)
                    sample = dict(sample_id=sid, image=str(image), sha256=file_digest(image))
                    atomic_json(folder / "input.json", sample)
                    rows.append(sample)
                    if sid not in ids[:20]:
                        continue
                    atomic_json(root / "samples" / sid / "input.json", sample)
                    for prep in PREPROCESSING:
                        cfg = parameters(prep)
                        dest = run_directory(root, sid, "wt_trellis2", prep, 42)
                        parent = root / "_cache" / f"{sid}-{prep}"
                        parent.mkdir(parents=True)
                        xyz, mask = cloud([(3, 4, 5), (8, 9, 10)])
                        np.savez(parent / "prediction.npz", xyz=xyz, mask=mask)
                        Image.open(image).save(parent / "rgba.png")
                        atomic_json(dest / "config.json", dict(parameters=cfg, provenance=PROVENANCE))
                        atomic_json(dest / "mesh.json", dict(ss_res=32, pipeline_type="1024_cascade",
                            canonical_transform=dict(centroid=[0, 0, 0], scale=1, axis_map="identity")))
                        atomic_json(dest / "wt_parent.json", dict(path=str(parent / "prediction.npz"),
                            sha256=file_digest(parent / "prediction.npz"),
                            settings={k: cfg[k] for k in ("wt_steps", "bg_color", "alpha_erode")}))
                        (dest / "decoded_mesh.ply").write_text("official decoded")
                        (dest / "mesh.glb").write_text("official glb")
                        atomic_json(dest / "run.json", dict(status="complete", seed=42, sample_id=sid,
                            method="wt_trellis2", config_id=prep, input_sha256=sample["sha256"],
                            artifacts={"decoded_mesh": {"path": "decoded_mesh.ply"},
                                       "mesh": {"path": "mesh.glb"}}))
                contexts.append(dict(dataset=dataset, condition=condition, source_inputs=rows,
                                     root=str(root), data=str(data), control_source=None))
        camera = dict(seed=42, config=dict(assets_per_dataset=50, conditions=list(CONDITIONS)),
                      condition_aliases={"B0": "A0"}, source_manifests=source_manifests,
                      contexts=contexts)
        camera_path, selection_path = base / "camera.json", base / "selection.json"
        atomic_json(camera_path, camera)
        selection = dict(selection_basis="geometry_diversity",
                         camera_plan_sha256=file_digest(camera_path), datasets=selected)
        atomic_json(selection_path, selection)
        plan = build_plan(camera_path, selection_path, base / "experiments" / "ablation")
        yield base, camera, selection, plan


def test_full_factorial_plan_reuses_exact_sources(pilot):
    base, camera, selection, plan = pilot
    assert validate_plan(plan) == base / "experiments" / "ablation"
    validate_sources(plan)
    assert len(plan["jobs"]) == 720 and len(plan["sources"]) == 240
    assert sum(j["strategy"] != "fill" for j in plan["jobs"]) == 480
    assert sum(len(v) for v in evaluation_candidates(plan).values()) == 720
    assert {row["stage"] for rows in evaluation_candidates(plan).values() for row in rows} == {"glb"}
    for job in plan["jobs"]:
        if job["strategy"] == "fill":
            assert job["destination"] == plan["sources"][job["source_key"]]["source_directory"]
    assert all(j["condition"] != "B0" for j in plan["jobs"])


@pytest.mark.parametrize("problem", ["duplicate", "outside", "score", "reason"])
def test_selection_rejects_invalid_pool_or_score_selection(pilot, problem):
    _, camera, selection, _ = pilot
    selection = copy.deepcopy(selection)
    if problem == "duplicate":
        selection["datasets"]["GSO"][-1] = selection["datasets"]["GSO"][0]
    elif problem == "outside":
        selection["datasets"]["GSO"][-1]["sample_id"] = "outside"
    elif problem == "score":
        selection["selection_basis"] = "hybrid_error"
    else:
        selection["datasets"]["GSO"][0]["reason"] = ""
    with pytest.raises(ValueError):
        check_selection(camera, selection)


def test_changed_plan_or_parent_rejected(pilot):
    _, _, _, plan = pilot
    altered = copy.deepcopy(plan)
    altered["jobs"][0]["seed"] = 17
    with pytest.raises(ValueError, match="changed"):
        validate_plan(altered)
    source = next(iter(plan["sources"].values()))
    path = Path(source["parent_directory"]) / "prediction.npz"
    before = path.read_bytes()
    try:
        path.write_bytes(b"changed")
        with pytest.raises(ValueError, match="source changed"):
            validate_sources(plan)
    finally:
        path.write_bytes(before)


class FakeBackend:
    provenance = PROVENANCE
    def __init__(self):
        self.events = []
    def configure_job(self, job):
        self.job = job
    def load_trellis(self, **kwargs):
        assert kwargs == dict(include_stage1=False, modes={"1024_cascade"})
        self.events.append("load")
    def unload_trellis(self):
        self.events.append("unload")
    def recover(self):
        self.events.append("recover")
    def generate_mesh(self, image, cfg, seed, directory, parent):
        assert seed == 42 and parent == Path(self.job["parent_directory"])
        with np.load(parent / "prediction.npz") as data:
            coords, count = surface_voxels(data["xyz"], data["mask"], lambda p: p,
                                           band_radius=int(self.job["strategy"] == "band"))
        assert count > 0
        self.events.append("mesh")
        (directory / "decoded_mesh.ply").write_text(str(coords.tolist()))
        (directory / "mesh.glb").write_text(str(count))
        return {"mesh": {"path": "mesh.glb"}, "decoded_mesh": {"path": "decoded_mesh.ply"}}


def test_end_to_end_cpu_smoke_and_resume(pilot):
    _, _, _, plan = pilot
    backend = FakeBackend()
    assert execute_plan(plan, lambda: backend, lambda: None) == 0
    assert backend.events.count("load") == 1
    assert backend.events.count("mesh") == 480
    assert backend.events[-1] == "unload"
    validate_sources(plan)  # official results/parents were not touched
    other = FakeBackend()
    assert execute_plan(plan, lambda: other, lambda: None) == 0
    assert other.events == []
    row = next(j for j in plan["jobs"] if j["strategy"] != "fill")
    path = Path(row["destination"])
    state = read_json(path / "run.json")
    with pytest.raises(ValueError, match="identity changed"):
        completed_job(path, "changed", state["input_sha256"])
    mesh = path / "mesh.glb"
    before = mesh.read_bytes()
    try:
        mesh.write_bytes(b"damaged")
        with pytest.raises(ValueError, match="artifact changed"):
            completed_job(path, state["config_hash"], state["input_sha256"])
    finally:
        mesh.write_bytes(before)
    for relative in ("config.json", "wt_parent.json", "../../../input.json"):
        metadata = path / relative
        original = metadata.read_bytes()
        try:
            metadata.write_bytes(b"changed")
            with pytest.raises(ValueError, match="provenance changed"):
                completed_job(path, state["config_hash"], state["input_sha256"])
        finally:
            metadata.write_bytes(original)


def test_gpu_work_refused_while_camera_active(tmp_path):
    proc = tmp_path / "proc"
    path = proc / "123" / "cmdline"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"python\0/snapshot/scripts/run_camera_ablation_modelwise.py\0--run\0")
    with pytest.raises(RuntimeError, match="camera_ablation still active"):
        assert_camera_idle(proc)
    path.write_bytes(b"python\0-m\0scripts.run_camera_ablation_batch\0")
    with pytest.raises(RuntimeError, match="camera_ablation still active"):
        assert_camera_idle(proc)


def test_no_cuda_context_was_created():
    import os
    import torch
    assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""
    assert not torch.cuda.is_initialized()


@pytest.mark.parametrize("field", ["trellis_descriptor", "dependencies", "torch", "environment"])
def test_backend_provenance_drift_is_rejected(pilot, field):
    source = next(iter(pilot[3]["sources"].values()))
    actual = copy.deepcopy(PROVENANCE)
    actual[field] = {} if field == "environment" else "changed"
    with pytest.raises(ValueError, match="mismatch"):
        validate_backend_provenance(source, actual)


def test_run_cli_requires_explicit_gpu_flag_before_reading_files(monkeypatch):
    import sys
    from scripts.run_hybrid_ablation import main
    monkeypatch.setattr(sys, "argv", ["hybrid", "run", "--plan", "/missing/plan.json"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 2


def test_official_metric_reuse_checks_revision_and_source(tmp_path):
    from scripts.run_hybrid_ablation import reuse_official_result
    experiment = tmp_path / "official"
    metrics = tmp_path / "metrics"
    artifact = tmp_path / "input.bin"
    artifact.write_bytes(b"frozen")
    job = dict(evaluation_roots=[str(experiment)], sample_id="x", config_id="defaults-v1",
               source_directory=str(tmp_path / "source"), dataset="GSO", condition="A0",
               preprocessing="defaults-v1")
    result = dict(revision="v1", status="complete", source_directory=job["source_directory"],
                  inputs={str(artifact): file_digest(artifact)}, result_path=str(metrics / "result.json"))
    atomic_json(metrics / "result.json", result)
    atomic_json(experiment / "baseline_evaluation.json", dict(directory=str(metrics)))
    row = dict(sample_id="x", method="wt_trellis2", config_id="defaults-v1", seed=42,
               stage="decoded", status="complete", result_path=result["result_path"],
               result_sha256=file_digest(metrics / "result.json"))
    atomic_json(metrics / "index.json", dict(revision="v1", results=[row]))
    assert reuse_official_result(job, "decoded", "v1") == result
    with pytest.raises(ValueError, match="compatible"):
        reuse_official_result(job, "decoded", "v2")
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="input changed"):
        reuse_official_result(job, "decoded", "v1")


def test_mesh_adapter_preserves_frozen_camera_preprocessing(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import torch
    import wt.textured_mesh as mesh_module
    import wt.camera_ablation as camera
    from wt.hybrid_ablation_backend import HybridAblationBackend
    backend = HybridAblationBackend.__new__(HybridAblationBackend)
    cfg = parameters("defaults-v1")
    tf = dict(centroid=[0, 0, 0], scale=1, axis_map="identity")
    backend.configure_job(dict(strategy="band", parameters=cfg, canonical_transform=tf))
    parent = tmp_path / "parent"
    parent.mkdir()
    xyz = np.zeros((6, 504, 504, 3), dtype=np.float32)
    mask = np.zeros(xyz.shape[:-1], dtype=bool)
    mask[0, 0, 0] = True
    np.savez(parent / "prediction.npz", xyz=xyz, mask=mask)
    Image.new("RGBA", (4, 4), (10, 20, 30, 255)).save(parent / "rgba.png")
    original = lambda image: image
    backend.pipeline = SimpleNamespace(preprocess_image=original,
        sparse_structure_sampler_params={}, shape_slat_sampler_params={}, tex_slat_sampler_params={})
    calls = []
    monkeypatch.setattr(camera, "spatial_record", lambda image: {"frozen": "B1"})
    def frozen(image, spatial, method):
        calls.append((spatial, method))
        return image
    monkeypatch.setattr(camera, "frozen_mesh_image", frozen)
    mesh = SimpleNamespace(vertices=torch.tensor([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
                           faces=torch.tensor([[0, 1, 2]]), voxel_size=1/1024)
    def inject(pipeline, image, coords, **kwargs):
        pipeline.preprocess_image(image)
        assert len(coords) == 7 and kwargs["ss_res"] == 32
        assert kwargs["seed"] == 42 and kwargs["pipeline_type"] == "1024_cascade"
        return [mesh]
    monkeypatch.setattr(mesh_module, "inject_coords_into_trellis2", inject)
    monkeypatch.setattr(mesh_module, "save_mesh_glb",
                        lambda path, mesh, **kwargs: path.write_bytes(b"synthetic glb"))
    dest = tmp_path / "output"
    dest.mkdir()
    # Exercise the real camera/base mesh adapter with CPU mesh and mocked sampling.
    artifacts = camera.CameraInferenceBackend.generate_mesh(
        backend, parent / "rgba.png", cfg, 42, dest, parent)
    assert {"mesh", "decoded_mesh"} == set(artifacts)
    assert calls == [({"frozen": "B1"}, "trellis2")]
    assert backend.pipeline.preprocess_image is original
    assert read_json(dest / "mesh.json")["canonical_transform"] == tf
    assert not torch.cuda.is_initialized()


def test_evaluation_routes_official_to_reuse_only(pilot, monkeypatch, tmp_path):
    import evaluation.hybrid_glb as evaluation
    import scripts.run_hybrid_ablation as runner
    _, _, _, plan = pilot
    assert execute_plan(plan, FakeBackend, lambda: None) == 0
    candidates = evaluation_candidates(plan)[("GSO", "A0")][:2]
    assert [c["strategy"] for c in candidates] == ["fill", "surface"]
    calls, reuses = [], []
    def result(source, stage, directory):
        state = read_json(source / "run.json")
        value = {key: state[key] for key in ("sample_id", "method", "config_id", "seed")}
        value.update(stage=stage, status="complete", source_directory=str(source),
                     result_path=str(directory / stage / "result.json"))
        atomic_json(Path(value["result_path"]), value)
        return value
    class Evaluator:
        def __init__(self, config):
            self.root = tmp_path / "metrics"
            self.config, self.revision, self.index_updates = {}, "cpu-fixture", []
        def evaluate(self, source, stage, name):
            assert source == Path(candidates[1]["source_directory"])
            calls.append(stage)
            return result(source, stage, self.root / "synthetic")
    def reuse(job, stage, revision):
        assert revision == "cpu-fixture"
        reuses.append(stage)
        return result(Path(job["source_directory"]), stage, tmp_path / "reused")
    monkeypatch.setattr(evaluation, "HybridGlbEvaluator", Evaluator)
    monkeypatch.setattr(runner, "reuse_official_result", reuse)
    monkeypatch.setattr(runner, "evaluation_candidates", lambda p: {("GSO", "A0"): candidates})
    assert runner.evaluate_plan(plan, tmp_path / "config", lambda: None) == 0
    assert calls == ["glb"] and reuses == ["glb"]
    index = read_json(tmp_path / "metrics" / f"{Path(plan['root']).name}-GSO-A0-glb-only" / "index.json")
    assert len(index["results"]) == 2
    validate_sources(plan)
    import torch
    assert not torch.cuda.is_initialized()
