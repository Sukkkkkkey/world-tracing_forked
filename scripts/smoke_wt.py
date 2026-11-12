"""Offline WT GPU validation using synthetic inputs and random model weights."""
import json
from copy import deepcopy

import numpy as np
import torch

from wt import MultilayerXYZModel, inference_diffusion, inference_video_diffusion, solve_intrinsics_from_xyz
from wt.checkpoint import CONFIGS
from wt.data import preprocess_rgba_for_model
from wt.inference import _bypass_activation_checkpointing
from wt.paths import output_path
from wt.sampling import denoise_geometry
from wt.textured_mesh.canon import compute_canonical_transform, canon_inverse
from wt.textured_mesh.voxelise import v4_ray_fill
from wt.viz import init_recording, log_prediction, save_rrd


def main():
    torch.manual_seed(42)
    rng = np.random.default_rng(42)
    assert torch.cuda.is_available(), 'CUDA is required for this smoke test'
    device = torch.device('cuda')
    # Verify integration numerically against a constant, known velocity.
    class ConstantVelocity(torch.nn.Module):
        def forward(self, x, t, conditioning):
            return {'v_t': torch.ones_like(x)}
    noise = torch.randn(1, 3, 2, 8, 8, device=device)
    result = denoise_geometry(ConstantVelocity(), noise, {}, iterations=4)
    torch.testing.assert_close(result, noise.permute(0, 2, 3, 4, 1) - 1)
    # Recover known intrinsics from a synthetic, nonplanar pointmap.
    v, u = np.mgrid[:28, :28] + 0.5
    z = rng.uniform(1, 3, (28, 28))
    xyz = np.stack([(u - 14) * z / 30, (v - 14) * z / 32, z], -1)
    K, _ = solve_intrinsics_from_xyz(xyz, np.ones((28, 28), bool))
    np.testing.assert_allclose(K, [[30, 0, 14], [0, 32, 14], [0, 0, 1]], atol=1e-5)
    layers = np.stack([xyz, xyz * 1.2]).astype(np.float32)
    tf = compute_canonical_transform(layers.reshape(-1, 3))
    np.testing.assert_allclose(canon_inverse(tf.apply(layers.reshape(-1, 3)), tf), layers.reshape(-1, 3), atol=1e-6)
    coords, count = v4_ray_fill(layers, np.ones(layers.shape[:-1], bool), tf.apply, res=16)
    assert len(coords) > 0 and coords.min() >= 0 and coords.max() < 16
    # Actual WT architecture: full random MoGe encoder, reduced DiT, no mocks.
    cfg = deepcopy(CONFIGS['r75b'])
    cfg['model_kwargs'].update(num_layers=2, decoder_embed_dim=96, num_decoder_blocks=3,
                               num_decoder_heads=4, num_head_blocks=3)
    model = MultilayerXYZModel(**cfg['model_kwargs']).eval().to(device)
    rgba = rng.integers(0, 256, (40, 40, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    rgb, mask, intr = preprocess_rgba_for_model(rgba, image_size=28, num_layers=2)
    kwargs = dict(cfg['inference_kwargs'], num_steps=2)
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16), _bypass_activation_checkpointing(model):
        pred, pred_mask, _ = inference_diffusion(model, rgb.to(device), gt_mask=mask.to(device),
            use_gt_mask=True, intrinsics=intr.to(device), invalid_fill_mode='noise', **kwargs)
    assert pred.shape == (1, 2, 28, 28, 3), pred.shape
    assert torch.isfinite(pred).all()
    torch.testing.assert_close(pred_mask.bool(), mask.to(device).bool())
    recording = init_recording(application_id='wt.synthetic.validation')
    log_prediction((rgb[0].permute(1, 2, 0).numpy() * 255).astype(np.uint8),
                   pred[0].float().cpu().numpy(), pred_mask[0].cpu().numpy().astype(bool),
                   intrinsics=intr[0].numpy(), name='random weights, synthetic input', recording=recording)
    rrd = output_path('validation/synthetic_wt.rrd')
    save_rrd(recording, rrd)
    recording.flush()
    assert rrd.stat().st_size > 0
    object_shape = list(pred.shape)
    del model
    # Scene normalisation and dynamic temporal attention use different paths.
    shapes = {'r75b': object_shape}
    for config_name in ('r69l', 'r76'):
        cfg = deepcopy(CONFIGS[config_name])
        cfg['model_kwargs'].update(num_layers=2, decoder_embed_dim=96, num_decoder_blocks=3,
                                  num_decoder_heads=4, num_head_blocks=3)
        model = MultilayerXYZModel(**cfg['model_kwargs']).eval().to(device)
        kwargs = dict(cfg['inference_kwargs'], num_steps=2)
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16), _bypass_activation_checkpointing(model):
            if config_name == 'r76':
                clip_rgb = torch.stack([rgb, torch.flip(rgb, [-1])], dim=1).to(device)
                clip_mask = torch.stack([mask, torch.flip(mask, [-1])], dim=1).to(device)
                pred, pred_mask, _ = inference_video_diffusion(model, clip_rgb, gt_mask_clip=clip_mask,
                    use_gt_mask=True, intrinsics=intr.to(device), invalid_fill_mode='noise', **kwargs)
                assert pred.shape == (1, 2, 2, 28, 28, 3), pred.shape
            else:
                pred, pred_mask, _ = inference_diffusion(model, rgb.to(device), gt_mask=mask.to(device),
                    use_gt_mask=True, intrinsics=intr.to(device), invalid_fill_mode='noise', **kwargs)
                assert pred.shape == (1, 2, 28, 28, 3), pred.shape
            assert torch.isfinite(pred).all()
            shapes[config_name] = list(pred.shape)
        del model
    report = dict(torch=torch.__version__, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(),
                  seed=42, wt_shapes=shapes, voxel_count=count,
                  checks=['Euler numerical solution', 'intrinsics recovery', 'canonical roundtrip',
                          'voxelisation bounds', 'WT random-weight object/scene/dynamic GPU forward',
                          'Rerun synthetic recording export'])
    path = output_path('validation/wt-smoke.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
