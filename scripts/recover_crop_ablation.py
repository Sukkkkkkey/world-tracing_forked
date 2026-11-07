"""Recreate the existing three-sample WT crop/background diagnostic."""
import fcntl
import json
from pathlib import Path
import time

import numpy as np
from wt.artifacts import save_npz
from PIL import Image
import torch

from evaluation.render import Rasterizer, load_mesh_parts, normalize_parts
from wt.batch import InferenceBackend
from wt.data import compute_object_crop, load_rgba_image, preprocess_rgba_for_model
from wt.experiment import atomic_json, file_digest, read_json, run_directory
from wt.inference import inference_diffusion, _bypass_activation_checkpointing
from wt.paths import OUTPUT_ROOT, PROCESSED_ROOT, WEIGHTS_ROOT

REPO = Path(__file__).resolve().parents[1]


def main():
    recipe = read_json(REPO / 'configs/recovery_experiments.json')['supplemental'][0]
    dataset = PROCESSED_ROOT / 'gso/v1'
    destination = OUTPUT_ROOT / 'validation' / recipe['id']
    main_root = OUTPUT_ROOT / 'experiments/20261013-P0-gso-pilot-v1'
    checkpoint = WEIGHTS_ROOT / 'huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt'
    inventory = {row['asset_id']: row for row in map(json.loads, (dataset / 'inventory.jsonl').read_text().splitlines())}
    backend = InferenceBackend(checkpoint, WEIGHTS_ROOT / 'local-pipelines/TRELLIS.2')
    source_files = {}
    for sample in recipe['samples']:
        baseline = run_directory(main_root, sample, 'wt', 'defaults-v1', recipe['seed'])
        assert read_json(baseline / 'run.json')['status'] == 'complete'
        assert read_json(baseline / 'config.json')['provenance'] == backend.provenance
        for path in [baseline / 'prediction.npz', baseline / 'run.json', dataset / 'samples' / sample / 'input.json']:
            source_files[str(path)] = file_digest(path)
    backend.load_wt()
    renderer = Rasterizer()
    records = []
    try:
        for sample in recipe['samples']:
            data_dir = dataset / 'samples' / sample
            camera = read_json(data_dir / 'camera.json')
            rgba = load_rgba_image(data_dir / 'input.png', auto_alpha=True)
            parts, _, _ = normalize_parts(load_mesh_parts(inventory[sample]['mesh']), 'z')
            for variant in recipe['variants']:
                started = time.monotonic()
                folder = destination / 'inference' / sample / variant
                folder.mkdir(parents=True, exist_ok=True)
                ratio = recipe['crop_ratios'][variant]
                background = [0, 0, 0] if variant == 'black' else recipe['default_background']
                backend.reset_seed(recipe['seed'])
                rgb, mask, intrinsics = preprocess_rgba_for_model(rgba, image_size=recipe['image_size'],
                    num_layers=6, center_crop=ratio is not None, max_object_ratio=ratio or 2/3,
                    alpha_erode_px=recipe['alpha_erode'], bg_color=tuple(background))
                crop = compute_object_crop(rgba, ratio) if ratio is not None else (0, 0, rgba.shape[0])
                y1, x1, side = crop
                assert rgba.shape[0] == rgba.shape[1], 'Whole-image K update assumes the square frozen GSO input'
                K = np.asarray(camera['K'], dtype=np.float64).copy()
                K[0, 2] -= x1
                K[1, 2] -= y1
                K[:2] *= recipe['image_size'] / side
                _, gt_depth, gt_mask, _ = renderer.render(parts, K, np.asarray(camera['T_world_to_camera']),
                    recipe['image_size'], texture=False)
                torch.manual_seed(recipe['seed'])
                kwargs = dict(backend.model_cfg['inference_kwargs'], num_steps=recipe['wt_steps'])
                with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16), _bypass_activation_checkpointing(backend.model):
                    xyz, valid, _ = inference_diffusion(backend.model, rgb.cuda(),
                        gt_mask=mask.cuda(), use_gt_mask=True, intrinsics=intrinsics.cuda(),
                        invalid_fill_mode='noise', **kwargs)
                xyz, valid = xyz[0].float().cpu().numpy(), valid[0].cpu().numpy().astype(bool)
                assert xyz.shape == (6, 504, 504, 3) and valid.any() and np.isfinite(xyz[valid]).all()
                image = (rgb[0].permute(1, 2, 0).numpy() * 255).astype(np.uint8)
                Image.fromarray(image).save(folder / 'input.png')
                save_npz(folder / 'prediction.npz', xyz=xyz, mask=valid, rgb=image, intrinsics=intrinsics[0].numpy())
                save_npz(folder / 'gt_depth.npz', depth=gt_depth, mask=gt_mask, K=K)
                common = valid[0] & gt_mask & np.isfinite(gt_depth) & (gt_depth > 0)
                assert common.any()
                record = dict(sample_id=sample, variant=variant, seed=recipe['seed'], wt_steps=recipe['wt_steps'],
                    bg_color=background, alpha_erode=0, crop_y_x_side=list(crop), max_object_ratio=ratio,
                    model_K=intrinsics[0].numpy().tolist(), gt_K=K.tolist(), common_pixels=int(common.sum()),
                    gt_mean_z=float(gt_depth[common].mean()), pred_mean_z=float(xyz[0, ..., 2][common].mean()),
                    pred_all_layer_z_min=float(xyz[..., 2][valid].min()),
                    pred_all_layer_z_max=float(xyz[..., 2][valid].max()),
                    seconds=time.monotonic() - started, full_multilayer_gt_available=False)
                if variant == 'baseline':
                    baseline = run_directory(main_root, sample, 'wt', 'defaults-v1', recipe['seed'])
                    with np.load(baseline / 'prediction.npz', allow_pickle=False) as old:
                        same = np.array_equal(old['xyz'], xyz) and np.array_equal(old['mask'], valid)
                        record['baseline_replay_equal'] = bool(same)
                        record['baseline_max_abs_difference'] = float(np.max(np.abs(old['xyz'] - xyz)))
                        assert same, 'Default ablation no longer reproduces the new P0 result'
                record['artifact_sha256'] = {name: file_digest(folder / name) for name in ('input.png', 'prediction.npz', 'gt_depth.npz')}
                atomic_json(folder / 'metrics.json', record)
                records.append(record)
                print('CROP', len(records), '/', recipe['runs'], sample, variant, flush=True)
    finally:
        backend.unload_wt()
    assert len(records) == recipe['runs']
    assert all(file_digest(Path(path)) == checksum for path, checksum in source_files.items())
    atomic_json(destination / 'inference_records.json', records)
    atomic_json(destination / 'recovery-validation.json', dict(status='passed', runs=len(records), recipe=recipe,
        source_sha256=source_files, script_sha256=file_digest(Path(__file__)),
        baseline_replays=3, full_multilayer_gt_available=False,
        scope='Existing 15 WT inference variants and actual crop K / visible-surface Z diagnostics'))
    print(destination, flush=True)


if __name__ == '__main__':
    with (REPO / '.runtime/recovery-gpu.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main()
