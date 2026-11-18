"""Replay frozen camera Hybrid parents with alternative sparse supports."""
from __future__ import annotations


from wt.camera_ablation import CameraMemoryBackend
from wt.textured_mesh.canon import CanonicalTransform
from wt.textured_mesh.voxelise import surface_voxels


class HybridAblationBackend(CameraMemoryBackend):
    """Reuse the reviewed camera and memory adapters, without WT inference."""

    def load_wt(self):
        raise RuntimeError("Hybrid ablation must reuse a frozen WT parent")

    def configure_job(self, job):
        self.ablation_job = job
        self.cascade_tokens = None

    def load_trellis(self, include_stage1, modes):
        if include_stage1:
            raise ValueError("Hybrid ablation never loads sparse-structure Stage 1")
        super().load_trellis(False, modes)
        original = self.pipeline.sample_shape_slat_cascade

        def sample(*args, **kwargs):
            slat, resolution = original(*args, **kwargs)
            self.cascade_tokens = len(slat.coords)
            return slat, resolution

        self.pipeline.sample_shape_slat_cascade = sample

    def hybrid_structure(self, xyz, mask, cfg, resolution):
        job = self.ablation_job
        if cfg != job["parameters"] or resolution != 32:
            raise ValueError("Ablation configuration changed")
        if xyz.shape != (6, 504, 504, 3) or mask.shape != xyz.shape[:-1]:
            raise ValueError("Expected frozen six-layer 504x504 WT prediction")
        tf = CanonicalTransform(**job["canonical_transform"])
        radius = {"surface": 0, "band": 1}[job["strategy"]]
        coords, count = surface_voxels(xyz, mask, tf.apply, res=resolution,
                                      band_radius=radius)
        if not count:
            raise ValueError("Empty ablation support; no fallback to official fill")
        return tf, coords, count

    def generate_mesh(self, image, cfg, seed, directory, parent):
        import torch
        from wt.experiment import atomic_json, read_json
        torch.cuda.reset_peak_memory_stats(self.device)
        artifacts = super().generate_mesh(image, cfg, seed, directory, parent)
        metadata = read_json(directory / "mesh.json")
        metadata.update(voxel_strategy=self.ablation_job["strategy"],
                        band_radius=int(self.ablation_job["strategy"] == "band"),
                        cascade_tokens=self.cascade_tokens,
                        canonical_transform_source=self.ablation_job["source_directory"])
        atomic_json(directory / "mesh.json", metadata)
        atomic_json(directory / "gpu_memory.json", {
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(self.device),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(self.device),
            "note": "PyTorch process peaks; not whole-card telemetry"})
        return artifacts
