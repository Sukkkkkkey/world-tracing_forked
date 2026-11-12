"""Independent TRELLIS.2 Stage 2/CUDA smoke tests; no WT bridge or weights."""
import json
import os
from pathlib import Path

import torch
import torch.nn.functional as F
from flash_attn import flash_attn_func
from trellis2.modules.sparse import SparseTensor, SparseConv3d
from trellis2.models.structured_latent_flow import SLatFlowModel
from trellis2.pipelines.samplers.flow_euler import FlowEulerSampler
from trellis2.pipelines import Trellis2ImageTo3DPipeline
import nvdiffrast.torch as dr
import cumesh
from o_voxel.serialize import encode_seq, decode_seq
from nvdiffrec_render import renderutils


def main():
    torch.manual_seed(42)
    assert torch.cuda.is_available()
    device = 'cuda'
    # FlashAttention against PyTorch's reference implementation.
    q, k, v = [torch.randn(2, 32, 4, 32, device=device, dtype=torch.float16) for _ in range(3)]
    actual = flash_attn_func(q, k, v)
    expected = F.scaled_dot_product_attention(q.transpose(1, 2), k.transpose(1, 2), v.transpose(1, 2)).transpose(1, 2)
    torch.testing.assert_close(actual, expected, atol=2e-3, rtol=2e-3)
    xyz = torch.cartesian_prod(*[torch.arange(4, device=device)] * 3).int()
    coords = torch.cat([torch.zeros(len(xyz), 1, device=device, dtype=torch.int32), xyz], dim=1)
    for mode in ('z_order', 'hilbert'):
        torch.testing.assert_close(decode_seq(encode_seq(xyz, mode=mode), mode=mode), xyz, check_dtype=False)
    x = SparseTensor(feats=torch.randn(len(coords), 8, device=device), coords=coords)
    # FlexGEMM convolution compared with dense Conv3d at exactly occupied coordinates.
    conv = SparseConv3d(8, 8, 3).to(device)
    sparse_out = conv(x)
    dense = torch.zeros(1, 8, 4, 4, 4, device=device)
    dense[0, :, xyz[:, 0], xyz[:, 1], xyz[:, 2]] = x.feats.T
    dense_out = F.conv3d(dense, conv.weight.permute(0, 4, 1, 2, 3).contiguous(), conv.bias, padding=1)
    torch.testing.assert_close(sparse_out.feats, dense_out[0, :, xyz[:, 0], xyz[:, 1], xyz[:, 2]].T, atol=2e-3, rtol=2e-3)
    cond = torch.randn(1, 16, 64, device=device, dtype=torch.float16)
    sampler = FlowEulerSampler(sigma_min=1e-5)
    # Upstream keeps input/output projections in FP32 and casts blocks internally.
    for name, channels, concat in [('shape', 8, None), ('texture', 16, x)]:
        model = SLatFlowModel(resolution=8, in_channels=channels, model_channels=64,
            cond_channels=64, out_channels=8, num_blocks=2, num_heads=2, dtype='float16').to(device).eval()
        # Avoid a zero output head masking nonfinite or inactive attention blocks.
        torch.nn.init.normal_(model.out_layer.weight, std=0.02)
        with torch.no_grad():
            out = sampler.sample(model, x, cond=cond, steps=2, verbose=False, concat_cond=concat).samples
        assert out.feats.shape == x.feats.shape and torch.isfinite(out.feats).all()
        assert not torch.allclose(out.feats, x.feats)
        torch.testing.assert_close(out.coords, coords)
        print(f'{name} Stage 2: {tuple(out.feats.shape)} PASS', flush=True)
    vertices = torch.tensor([[-.5, -.5, 0], [.5, -.5, 0], [0, .5, 0]], device=device)
    faces = torch.tensor([[0, 1, 2]], device=device, dtype=torch.int32)
    mesh = cumesh.CuMesh()
    mesh.init(vertices, faces)
    verts_read, faces_read = mesh.read()
    torch.testing.assert_close(verts_read, vertices)
    torch.testing.assert_close(faces_read, faces)
    pos = torch.cat([vertices, torch.ones(3, 1, device=device)], -1)[None]
    raster, _ = dr.rasterize(dr.RasterizeCudaContext(), pos, faces, resolution=[32, 32])
    assert (raster[..., 3] > 0).sum() > 0
    cubemap = torch.ones(6, 16, 16, 3, device=device)
    irradiance = renderutils.diffuse_cubemap(cubemap)
    assert irradiance.shape == cubemap.shape and torch.isfinite(irradiance).all()
    assert irradiance.min() > 0
    torch.cuda.synchronize()
    report = dict(torch=torch.__version__, gpu=torch.cuda.get_device_name(), seed=42,
        checks=['FlashAttention vs SDPA', 'O-Voxel Morton/Hilbert roundtrip',
                'FlexGEMM sparse vs dense convolution', 'random-weight shape SLat Euler sampling',
                'random-weight texture SLat with concatenated shape conditioning',
                'CuMesh GPU read/write', 'nvdiffrast CUDA rasterisation',
                'nvdiffrec diffuse environment map', 'pipeline import'])
    path = Path(os.environ['WT_OUTPUT_ROOT']) / 'validation/trellis2-smoke.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
