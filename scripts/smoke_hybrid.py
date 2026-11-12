"""Synthetic WT geometry -> real TRELLIS.2 shape/texture flow on CUDA.

Uses small random-weight flow models and random image conditions. The decoder
is an assertion boundary, not a generated mesh; real mesh export is exercised
separately through examples/infer_textured_mesh.py with pretrained weights.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image
import torch

from wt.paths import OUTPUT_ROOT
from wt.textured_mesh import compute_canonical_transform, inject_coords_into_trellis2, v4_ray_fill
from trellis2.models.structured_latent_flow import SLatFlowModel
from trellis2.pipelines import Trellis2ImageTo3DPipeline
from trellis2.pipelines.samplers.flow_euler import FlowEulerSampler


class SyntheticPipeline(Trellis2ImageTo3DPipeline):
    def get_cond(self, images, resolution, include_neg_cond=True):
        return {"cond": torch.randn(1, 16, 64, device=self.device, dtype=torch.float16)}

    def decode_latent(self, shape, texture, resolution):
        torch.testing.assert_close(shape.coords, texture.coords)
        for latent in (shape, texture):
            assert latent.feats.shape == (len(self.expected), 8)
            assert torch.isfinite(latent.feats).all()
            torch.testing.assert_close(latent.coords[:, 1:].cpu(), torch.from_numpy(self.expected))
        return [dict(resolution=resolution, tokens=len(self.expected), shape=list(shape.feats.shape))]


def main():
    torch.manual_seed(42)
    rng = np.random.default_rng(42)
    xyz = rng.normal(size=(3, 12, 12, 3)).astype(np.float32)
    mask = np.ones(xyz.shape[:-1], dtype=bool)
    transform = compute_canonical_transform(xyz.reshape(-1, 3))
    reports = []
    for mode, grid in (("512", 32), ("1024", 64)):
        coords, raw = v4_ray_fill(xyz, mask, transform.apply, res=grid, max_voxels=64, seed=42)
        models = {}
        for kind, channels in (("shape", 8), ("tex", 16)):
            model = SLatFlowModel(resolution=grid, in_channels=channels, model_channels=64,
                cond_channels=64, out_channels=8, num_blocks=2, num_heads=2, dtype="float16").cuda().eval()
            torch.nn.init.normal_(model.out_layer.weight, std=0.02)
            models[f"{kind}_slat_flow_model_{mode}"] = model
        normalization = {"mean": [0.1] * 8, "std": [1.2] * 8}
        pipeline = SyntheticPipeline(models=models,
            shape_slat_sampler=FlowEulerSampler(sigma_min=1e-5),
            tex_slat_sampler=FlowEulerSampler(sigma_min=1e-5),
            shape_slat_sampler_params={}, tex_slat_sampler_params={},
            shape_slat_normalization=normalization, tex_slat_normalization=normalization,
            low_vram=False)
        pipeline._device = torch.device("cuda")  # Models are already on GPU; no image encoder.
        pipeline.expected = coords
        result = inject_coords_into_trellis2(pipeline, Image.new("RGB", (32, 32)), coords,
            pipeline_type=mode, ss_res=grid, preprocess_image=False,
            shape_slat_sampler_params={"steps": 2}, tex_slat_sampler_params={"steps": 2})
        reports.append(dict(mode=mode, raw_voxels=raw, **result[0]))
    output = OUTPUT_ROOT / "validation/hybrid-smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(seed=42, synthetic=True, mesh_decoder_executed=False,
                                     results=reports), indent=2) + "\n")
    print(output, flush=True)


if __name__ == "__main__":
    main()
