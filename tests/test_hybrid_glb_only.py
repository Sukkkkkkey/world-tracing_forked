from pathlib import Path

import pytest
from wt.experiment import atomic_json, file_digest
from evaluation.hybrid_glb import HybridGlbEvaluator


def test_glb_only_without_a_decoded_file(tmp_path, monkeypatch):
    sample_dir = tmp_path / "samples" / "asset"
    directory = sample_dir / "wt_trellis2" / "surface" / "seed-0042"
    directory.mkdir(parents=True)
    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    for name in ("gt_depth.npz", "gt_points.npz", "parent.npz"):
        (tmp_path / name).write_bytes(name.encode())
    for name in ("mesh.glb", "config.json", "mesh.json"):
        (directory / name).write_bytes(name.encode())
    atomic_json(directory / "wt_parent.json", {"path": str(tmp_path / "parent.npz")})
    atomic_json(sample_dir / "input.json", dict(sample_id="asset", image=str(source),
        sha256=file_digest(source), evaluation_dir=str(tmp_path),
        artifact_sha256={k: file_digest(tmp_path / k) for k in ("gt_points.npz", "gt_depth.npz")}))
    atomic_json(directory / "run.json", dict(status="complete", method="wt_trellis2",
        config_id="surface", seed=42, input_sha256=file_digest(source), artifacts={"mesh": {}}))
    ev = HybridGlbEvaluator.__new__(HybridGlbEvaluator)
    ev.revision, ev.root, ev.config = "test", tmp_path / "eval", {"protocol_version": "v0.5"}
    ev.reference = lambda sample: ([], {}, dict(directory=str(tmp_path), signature="gt"))
    def compute(directory, state, stage, sample, cameras, reference, dest, decoded_record=None):
        assert stage == "glb" and decoded_record is None
        return dict(shape={"test": 1}, files={}, export_pair={"status": "failed"})
    ev.compute = compute
    ev.ensure_images = lambda *args: {}
    import examples.evaluate_multiview as mv
    monkeypatch.setattr(mv, "CACHE_ROOT", tmp_path / "cache")
    result = ev.evaluate(directory, "glb", "pilot")
    assert result["status"] == "complete" and result["shape"] == {"test": 1}
    assert all("decoded" not in k for k in result["inputs"])
    assert "export_pair" not in result
    with pytest.raises(ValueError, match="only exported GLBs"):
        ev.evaluate(directory, "decoded", "pilot")
