"""Replay frozen camera Hybrid parents with alternative sparse supports."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path


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

    @contextmanager
    def prepare_batch(self, jobs):
        """Prepare image conditioning and sample both shape flows and texture once per group."""
        import numpy as np
        import torch
        from PIL import Image
        from wt.camera_ablation import fixed_mesh_preprocessing, spatial_record
        from wt.textured_mesh.batched_cascade import sample_latents

        cfg = jobs[0]["parameters"]
        images, supports, metadata = [], [], []
        torch.cuda.reset_peak_memory_stats(self.device)
        for job in jobs:
            if job["parameters"] != cfg:
                raise ValueError("Hybrid batch mixes sampler configurations")
            self.configure_job(job)
            self.reset_seed(job["seed"])
            parent = Path(job["parent_directory"])
            with np.load(parent / "prediction.npz", allow_pickle=False) as data:
                tf, coords, count = self.hybrid_structure(data["xyz"], data["mask"], cfg, 32)
            spatial = spatial_record(job["input"]["image"])
            with Image.open(parent / "rgba.png") as source:
                if source.mode == "RGBA" and source.getchannel("A").getextrema()[1] <= 204:
                    raise ValueError("Empty TRELLIS foreground: " + job["sample_id"])
                with fixed_mesh_preprocessing(self.pipeline, spatial, "trellis2"):
                    images.append(self.pipeline.preprocess_image(source.copy()))
            supports.append(coords)
            metadata.append(dict(canonical_transform=tf.to_dict(), ss_res=32, injected_voxels=count))
        shape, texture, lengths, rng_states = sample_latents(
            self.pipeline, images, supports, [job["seed"] for job in jobs], cfg)
        self.batch_peaks = (torch.cuda.max_memory_allocated(self.device),
                            torch.cuda.max_memory_reserved(self.device))
        # SparseTensor[i] remaps the member to batch index zero for the existing decoder.
        self.batch_latents = (shape, texture, lengths, rng_states, metadata,
                              {j["destination"]: i for i, j in enumerate(jobs)})
        try:
            yield
        finally:
            self.batch_latents = self.batch_peaks = None

    def hybrid_mesh(self, parent, cfg, params):
        batch = getattr(self, "batch_latents", None)
        if batch is None:
            return super().hybrid_mesh(parent, cfg, params)
        import torch
        shape, texture, lengths, rng_states, metadata, indices = batch
        i = indices[self.ablation_job["destination"]]
        self.cascade_tokens = lengths[i]
        torch.set_rng_state(rng_states[i])
        return self.pipeline.decode_latent(shape[i], texture[i], 1024), metadata[i]

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
            "batch_sampling_peak_allocated_bytes": self.batch_peaks[0] if getattr(self, "batch_peaks", None) else None,
            "batch_sampling_peak_reserved_bytes": self.batch_peaks[1] if getattr(self, "batch_peaks", None) else None,
            "note": "Process peaks; sampling is shared by all batch members"})
        return artifacts
