"""Offline dependency checks with synthetic CUDA inputs; no pretrained weights."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    expected_env = Path(os.environ['WT_PIXAL3D_ENV']).resolve()
    if Path(sys.prefix).resolve() != expected_env:
        raise RuntimeError(f'Expected isolated environment {expected_env}, got {sys.prefix}')
    if not (os.environ.get('STY') or os.environ.get('TMUX')):
        raise RuntimeError('Run checks in a dedicated screen/tmux session')
    destination = Path(os.environ['WT_OUTPUT_ROOT']) / 'validation/pixal3d-environment.json'
    destination.unlink(missing_ok=True)  # A failed rerun must not leave a stale PASS.
    import torch
    import torch.nn.functional as F
    import utils3d
    import natten
    from flash_attn import flash_attn_func
    from pixal3d.pipelines import Pixal3DImageTo3DPipeline
    from pixal3d.trainers.flow_matching.mixins.image_conditioned_proj import DinoV3ProjFeatureExtractor
    from pixal3d.modules.sparse import SparseTensor, SparseConv3d
    from moge.model.v2 import MoGeModel
    from moge.utils.geometry_torch import normalized_view_plane_uv, recover_focal_shift
    import cumesh
    import nvdiffrast.torch as dr
    from o_voxel.serialize import encode_seq, decode_seq

    assert torch.__version__ == '2.6.0+cu124'
    assert torch.cuda.is_available()
    assert natten.__version__.split('+')[0] == '0.21.0'
    checks = ['Pixal3D pipeline/projection and MoGe-2 imports']
    torch.manual_seed(42)
    device = 'cuda'

    # Independent dense reference for attention; a 3x3 neighborhood covers
    # the full 3x3 image at every query, including boundary-shifted windows.
    q, k, v = [torch.randn(1, 3, 3, 2, 32, device=device, dtype=torch.float16)
               for _ in range(3)]
    actual = natten.na2d(q, k, v, kernel_size=3, backend='cutlass-fna')
    dense = [t.reshape(1, 9, 2, 32).transpose(1, 2) for t in (q, k, v)]
    expected = F.scaled_dot_product_attention(*dense).transpose(1, 2).reshape_as(actual)
    torch.testing.assert_close(actual, expected, atol=3e-3, rtol=3e-3)
    flash = flash_attn_func(*[t.reshape(1, 9, 2, 32) for t in (q, k, v)])
    torch.testing.assert_close(flash.reshape_as(expected), expected, atol=3e-3, rtol=3e-3)
    checks.append('NATTEN CUTLASS and FlashAttention vs dense SDPA')

    # Local Hub source, explicitly random weights: this must never fetch a model.
    naf = torch.hub.load(os.environ['WT_NAF_ROOT'], 'naf', source='local',
                         pretrained=False, device=device).eval()
    # Upstream DINOv3/NAF conditions use FP32 and 1024 feature channels.
    guide = torch.rand(1, 3, 32, 32, device=device)
    features = torch.ones(1, 1024, 16, 16, device=device)
    with torch.no_grad():
        result = naf(guide, features, (32, 32))
    assert result.shape == (1, 1024, 32, 32)
    torch.testing.assert_close(result, torch.ones_like(result), atol=3e-4, rtol=3e-4)
    checks.append('NAF FP32/1024-channel upsampling preserves constant features')
    del naf

    # APIs required by MoGe-2 infer(), not just a successful import of utils3d.
    uv = normalized_view_plane_uv(16, 16, device=device)
    depth = 2 + uv[..., 0].square() + 0.3 * uv[..., 1]
    points = torch.cat([uv * depth[..., None] / 1.2, (depth - 0.4)[..., None]], -1)
    focal, shift = recover_focal_shift(points, downsample_size=(16, 16))
    torch.testing.assert_close(focal, torch.tensor(1.2, device=device), atol=1e-4, rtol=1e-4)
    torch.testing.assert_close(shift, torch.tensor(0.4, device=device), atol=1e-4, rtol=1e-4)
    intrinsics = utils3d.pt.intrinsics_from_focal_center(
        *[torch.tensor(x, device=device) for x in (1., 1., .5, .5)])
    recovered = utils3d.pt.depth_map_to_point_map(depth, intrinsics=intrinsics)
    assert recovered.shape == (16, 16, 3) and torch.isfinite(recovered).all()
    torch.testing.assert_close(recovered[..., 2], depth)
    checks.append('MoGe focal/shift recovery and utils3d camera APIs')

    xyz = torch.cartesian_prod(*[torch.arange(4, device=device)] * 3).int()
    coords = torch.cat([torch.zeros(len(xyz), 1, device=device, dtype=torch.int32), xyz], 1)
    x = SparseTensor(feats=torch.randn(len(coords), 8, device=device), coords=coords)
    conv = SparseConv3d(8, 8, 3).to(device).eval()
    with torch.no_grad():
        sparse_out = conv(x)
        dense_x = torch.zeros(1, 8, 4, 4, 4, device=device)
        dense_x[0, :, xyz[:, 0], xyz[:, 1], xyz[:, 2]] = x.feats.T
        dense_out = F.conv3d(dense_x, conv.weight.permute(0, 4, 1, 2, 3).contiguous(), conv.bias, padding=1)
    torch.testing.assert_close(sparse_out.feats, dense_out[0, :, xyz[:, 0], xyz[:, 1], xyz[:, 2]].T,
                               atol=2e-3, rtol=2e-3)
    for mode in ('z_order', 'hilbert'):
        torch.testing.assert_close(decode_seq(encode_seq(xyz, mode=mode), mode=mode), xyz, check_dtype=False)
    checks.append('Pixal3D FlexGEMM convolution vs dense Conv3d; O-Voxel roundtrip')

    vertices = torch.tensor([[-.5, -.5, 0], [.5, -.5, 0], [0, .5, 0]], device=device)
    faces = torch.tensor([[0, 1, 2]], device=device, dtype=torch.int32)
    mesh = cumesh.CuMesh()
    mesh.init(vertices, faces)
    vertices_read, faces_read = mesh.read()
    torch.testing.assert_close(vertices_read, vertices)
    torch.testing.assert_close(faces_read, faces)
    positions = torch.cat([vertices, torch.ones(3, 1, device=device)], -1)[None]
    raster, _ = dr.rasterize(dr.RasterizeCudaContext(), positions, faces, resolution=[16, 16])
    assert (raster[..., 3] > 0).sum() > 0
    checks.append('CuMesh GPU geometry and nvdiffrast rasterization')
    torch.cuda.synchronize()

    sources = {}
    locked = {line.split()[0]: line.split()[1]
              for line in Path(__file__).with_name('sources.lock').read_text().splitlines()
              if line.strip() and not line.startswith('#')}
    for name, key in [('Pixal3D', 'WT_PIXAL3D_ROOT'), ('MoGe2', 'WT_MOGE2_ROOT'), ('NAF', 'WT_NAF_ROOT')]:
        root = Path(os.environ[key]).resolve()
        sources[name] = dict(path=str(root), revision=subprocess.check_output(
            ['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
            dirty=bool(subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True)))
        assert sources[name]['revision'] == locked[name], f'{name} source revision changed'
        assert not sources[name]['dirty'], f'{name} source has unrecorded local changes'
    versions = {name: importlib.metadata.version(name) for name in (
        'torch', 'torchvision', 'numpy', 'transformers', 'diffusers', 'accelerate',
        'natten', 'flash-attn', 'utils3d', 'flex_gemm', 'cumesh', 'nvdiffrast', 'o_voxel')}
    origins = {name: str(Path(importlib.import_module(name).__file__).resolve())
               for name in ('pixal3d', 'moge', 'utils3d', 'natten')}
    report = dict(status='passed', scope='offline synthetic CUDA dependency checks; no pretrained inference',
                  environment=sys.prefix, gpu=torch.cuda.get_device_name(),
                  capability=torch.cuda.get_device_capability(), versions=versions, sources=sources,
                  module_origins=origins, checks=checks,
                  checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
