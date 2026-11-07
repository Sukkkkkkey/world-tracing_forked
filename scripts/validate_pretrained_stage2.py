"""Offline pretrained TRELLIS.2 Stage 2 smoke test with synthetic conditioning.

Runs released 512/1024 shape and texture flows, without DINOv3, RMBG or a WT
bridge. This verifies checkpoint compatibility and inference, not image quality.
"""
import gc
import json
import os
from pathlib import Path
import time

import torch
from huggingface_hub import snapshot_download
from safetensors.torch import load_file
from trellis2 import models
from trellis2.modules.sparse import SparseTensor
from trellis2.pipelines.samplers.flow_euler import FlowEulerSampler


def main():
    torch.manual_seed(42)
    torch.set_num_threads(8)
    torch.cuda.reset_peak_memory_stats()
    root = Path(os.environ['WT_WEIGHTS_ROOT'])
    record = json.loads((root / 'download-manifest.json').read_text())['trellis2']
    snapshot = Path(snapshot_download(record['repo'], revision=record['revision'],
                                     local_files_only=True, token=False))
    xyz = torch.cartesian_prod(*[torch.arange(4, device='cuda')] * 3).int()
    coords = torch.cat([torch.zeros(len(xyz), 1, device='cuda', dtype=torch.int32), xyz], 1)
    sampler = FlowEulerSampler(sigma_min=1e-5)
    results = []
    for resolution in (512, 1024):
        for task in ('img2shape', 'imgshape2tex'):
            started = time.monotonic()
            prefix = snapshot / f'ckpts/slat_flow_{task}_dit_1_3B_{resolution}_bf16'
            cfg = json.loads(prefix.with_suffix('.json').read_text())
            model = getattr(models, cfg['name'])(**cfg['args'])
            model.load_state_dict(load_file(str(prefix.with_suffix('.safetensors'))), strict=True)
            model.cuda().eval()
            noise = SparseTensor(feats=torch.randn(len(coords), model.out_channels, device='cuda'), coords=coords)
            cond = torch.randn(1, 16, model.cond_channels, device='cuda', dtype=model.dtype)
            # Synthetic shape conditioning keeps this independent of any WT integration.
            concat = None if task == 'img2shape' else noise.replace(torch.randn_like(noise.feats))
            with torch.inference_mode():
                out = sampler.sample(model, noise, cond=cond, concat_cond=concat, steps=2, verbose=False).samples
            assert out.feats.shape == noise.feats.shape
            assert torch.isfinite(out.feats).all()
            assert not torch.allclose(out.feats, noise.feats)
            torch.testing.assert_close(out.coords, coords)
            torch.cuda.synchronize()
            result = dict(task=task, resolution=resolution, shape=list(out.feats.shape),
                          strict_checkpoint_load=True, finite=True, steps=2,
                          seconds=round(time.monotonic()-started, 2))
            results.append(result)
            print(json.dumps(result), flush=True)
            del model, noise, cond, concat, out
            gc.collect()
            torch.cuda.empty_cache()
    report = dict(repo=record['repo'], revision=record['revision'], seed=42,
                  conditioning='random tensors; no DINOv3/RMBG/WT',
                  peak_gpu_bytes=torch.cuda.max_memory_allocated(), checks=results)
    output = Path(os.environ['WT_OUTPUT_ROOT']) / 'validation/trellis2-pretrained-stage2.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(output, flush=True)


if __name__ == '__main__':
    main()
