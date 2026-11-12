"""Persistent two-stage inference: all WT jobs, then all TRELLIS / hybrid jobs."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import gc
import os
from pathlib import Path
import shutil
import time
import traceback

from wt.artifacts import save_npz
from wt.experiment import (SCHEMA_VERSION, WT_METHODS as METHODS, atomic_json, digest, file_digest,
                           identifier, read_json, run_directory)


def resolve_configs(configs):
    result, seen = [], set()
    for item in configs:
        method = item['method']
        if method not in METHODS:
            raise ValueError(f'Unknown method {method}')
        defaults = dict(method=method, config_id='defaults-v1', wt_steps=20,
                        bg_color=[128, 128, 128] if method == 'wt' else [0, 0, 0],
                        alpha_erode=0 if method == 'wt' else 2,
                        pipeline_type='1024_cascade', ray_steps=4, shape_steps=12,
                        tex_steps=12, max_num_tokens=49152, texture_size=4096,
                        decimation_target=1_000_000)
        unknown = set(item) - set(defaults)
        if unknown:
            raise ValueError(f'Unknown config keys: {sorted(unknown)}')
        cfg = {**defaults, **item}
        identifier(cfg['config_id'])
        key = (method, cfg['config_id'])
        if key in seen:
            raise ValueError(f'Duplicate method/config ID: {key}')
        seen.add(key)
        for name in ('wt_steps', 'shape_steps', 'tex_steps', 'max_num_tokens',
                     'texture_size', 'decimation_target'):
            if type(cfg[name]) is not int or cfg[name] <= 0:
                raise ValueError(f'{name} must be a positive integer')
        for name in ('ray_steps', 'alpha_erode'):
            if type(cfg[name]) is not int or cfg[name] < 0:
                raise ValueError(f'{name} must be a nonnegative integer')
        if cfg['pipeline_type'] not in ('512', '1024', '1024_cascade', '1536_cascade'):
            raise ValueError('Unknown pipeline_type')
        if len(cfg['bg_color']) != 3 or any(type(x) is not int or not 0 <= x <= 255 for x in cfg['bg_color']):
            raise ValueError('bg_color must be three integer channels in 0..255')
        result.append(cfg)
    if not result:
        raise ValueError('No configurations')
    return result


def wt_settings(cfg):
    return {key: cfg[key] for key in ('wt_steps', 'bg_color', 'alpha_erode')}


def cache_key(sample, cfg, seed, provenance):
    return digest(dict(input=sample['sha256'], wt=wt_settings(cfg), seed=seed,
                       provenance=provenance))


def completed(directory, config_hash, input_hash):
    try:
        state = read_json(directory / 'run.json')
        return (state['status'] == 'complete' and state['config_hash'] == config_hash
                and state['input_sha256'] == input_hash and bool(state.get('artifacts'))
                and all((directory / a['path']).is_file() for a in state['artifacts'].values()))
    except (OSError, KeyError, ValueError, TypeError):
        return False


def run_batch(root, inputs, configs, seeds, backend):
    """Backend loads at most once per stage. Failed jobs do not stop unrelated samples.

    A directory is single-writer (the CLI holds a lock). Resume requires identical
    input/config/provenance, and completed runs are never overwritten.
    """
    root = Path(root)
    configs = resolve_configs(configs)
    seeds = list(dict.fromkeys(seeds))
    if not seeds or any(type(s) is not int or not 0 <= s < 2**32 for s in seeds):
        raise ValueError('seeds must be integers in 0..2**32-1')
    samples, seen = [], set()
    for value in inputs:
        sample_id, image = identifier(value['sample_id']), Path(value['image']).resolve()
        if sample_id in seen:
            raise ValueError(f'Duplicate sample ID: {sample_id}')
        seen.add(sample_id)
        samples.append(dict(value, sample_id=sample_id, image=str(image), sha256=file_digest(image)))
    if not samples:
        raise ValueError('No input images')
    provenance = backend.provenance
    root.mkdir(parents=True, exist_ok=True)
    header = root / 'experiment.json'
    if header.exists():
        if read_json(header).get('schema_version') != SCHEMA_VERSION:
            raise ValueError('Unsupported existing experiment schema')
    else:
        atomic_json(header, dict(schema_version=SCHEMA_VERSION, experiment_id=root.name))
    jobs = []
    # Validate ALL identities before writing any planned states or loading models.
    for sample in samples:
        input_path = root / 'samples' / sample['sample_id'] / 'input.json'
        if input_path.exists() and read_json(input_path)['sha256'] != sample['sha256']:
            raise ValueError(f'Input changed for {sample["sample_id"]}; use a new sample/experiment ID')
        for cfg in configs:
            config_hash = digest(dict(config=cfg, provenance=provenance))
            for seed in seeds:
                directory = run_directory(root, sample['sample_id'], cfg['method'], cfg['config_id'], seed)
                state_path = directory / 'run.json'
                if state_path.exists() and read_json(state_path).get('config_hash') != config_hash:
                    raise ValueError(f'Config/source/weights changed at {directory}; use a new config ID')
                if not completed(directory, config_hash, sample['sha256']):
                    jobs.append((sample, cfg, seed, directory, config_hash))
    for sample in samples:
        atomic_json(root / 'samples' / sample['sample_id'] / 'input.json', sample)

    def state(job, status, **extra):
        sample, cfg, seed, directory, config_hash = job
        atomic_json(directory / 'run.json', dict(schema_version=SCHEMA_VERSION,
            sample_id=sample['sample_id'], method=cfg['method'], config_id=cfg['config_id'],
            seed=seed, config_hash=config_hash, input_sha256=sample['sha256'], status=status,
            **extra))

    for job in jobs:
        atomic_json(job[3] / 'config.json', dict(parameters=job[1], provenance=provenance))
        state(job, 'planned')
    print(f'Batch: {len(samples)} inputs, {len(jobs)} pending runs', flush=True)
    cache = {}
    for job in jobs:
        sample, cfg, seed = job[:3]
        if cfg['method'] != 'trellis2':
            key = cache_key(sample, cfg, seed, provenance)
            cache.setdefault(key, (sample, cfg, seed))
    cache_results, cache_errors = {}, {}
    missing = []
    for key, task in cache.items():
        directory = root / '_cache' / 'wt' / key
        try:
            info = read_json(directory / 'complete.json')
            if (info['cache_key'] != key or file_digest(directory / 'rgba.png') != info['rgba_sha256']
                    or file_digest(directory / 'prediction.npz') != info['sha256']):
                raise ValueError('Invalid cache')
            cache_results[key] = directory
        except (OSError, KeyError, ValueError):
            missing.append((key, task, directory))
    if missing:
        try:
            try:
                backend.load_wt()
            except Exception:
                error = traceback.format_exc()
                for key, _, _ in missing:
                    cache_errors[key] = f'WT initialization failed:\n{error}'
                missing = []
            for key, (sample, cfg, seed), directory in missing:
                directory.mkdir(parents=True, exist_ok=True)
                started = time.monotonic()
                try:
                    with (directory / 'run.log').open('w') as log, redirect_stdout(log), redirect_stderr(log):
                        backend.predict_wt(Path(sample['image']), cfg, seed, directory)
                    info = dict(cache_key=key, sha256=file_digest(directory / 'prediction.npz'),
                                rgba_sha256=file_digest(directory / 'rgba.png'),
                                seconds=time.monotonic() - started)
                    atomic_json(directory / 'complete.json', info)
                    cache_results[key] = directory
                except Exception:
                    cache_errors[key] = traceback.format_exc()
                    (directory / 'error.log').write_text(cache_errors[key])
                    backend.recover()
                print(f'WT cache {sample["sample_id"]} seed={seed}: {"complete" if key in cache_results else "failed"}', flush=True)
        finally:
            backend.unload_wt()
    mesh_jobs = []
    failures = 0
    for job in jobs:
        sample, cfg, seed, directory, _ = job
        key = cache_key(sample, cfg, seed, provenance)
        if cfg['method'] != 'trellis2' and key not in cache_results:
            state(job, 'failed', error=cache_errors.get(key, 'WT cache unavailable'))
            failures += 1
        elif cfg['method'] == 'wt':
            source = cache_results[key] / 'prediction.npz'
            shutil.copyfile(source, directory / 'prediction.npz')
            atomic_json(directory / 'runtime.json', read_json(source.parent / 'complete.json'))
            state(job, 'complete', artifacts={'points': dict(path='prediction.npz', kind='points', frame='camera_rdf')})
        else:
            # Native TRELLIS must never inherit a WT cache with matching defaults.
            mesh_jobs.append((job, None if cfg['method'] == 'trellis2' else cache_results[key]))
    if mesh_jobs:
        try:
            try:
                backend.load_trellis(include_stage1=any(j[0][1]['method'] == 'trellis2' for j in mesh_jobs),
                                     modes={j[0][1]['pipeline_type'] for j in mesh_jobs})
            except Exception:
                error = traceback.format_exc()
                for job, _ in mesh_jobs:
                    state(job, 'failed', error=f'TRELLIS initialization failed:\n{error}')
                failures += len(mesh_jobs)
                mesh_jobs = []
            for job, parent in mesh_jobs:
                sample, cfg, seed, directory, _ = job
                state(job, 'running')
                started = time.monotonic()
                try:
                    if parent is not None:
                        atomic_json(directory / 'wt_parent.json', dict(
                            path=os.path.relpath(parent / 'prediction.npz', directory),
                            sha256=file_digest(parent / 'prediction.npz'), settings=wt_settings(cfg)))
                    with (directory / 'run.log').open('w') as log, redirect_stdout(log), redirect_stderr(log):
                        artifacts = backend.generate_mesh(Path(sample['image']), cfg, seed, directory, parent)
                    wt_seconds = read_json(parent / 'complete.json')['seconds'] if parent else 0
                    mesh_seconds = time.monotonic() - started
                    atomic_json(directory / 'runtime.json', dict(mesh_seconds=mesh_seconds,
                        wt_seconds=wt_seconds, total_inference_seconds=mesh_seconds + wt_seconds))
                    state(job, 'complete', artifacts=artifacts)
                except Exception:
                    state(job, 'failed', error=traceback.format_exc())
                    failures += 1
                    backend.recover()
                print(f'{sample["sample_id"]} {cfg["method"]}/{cfg["config_id"]} seed={seed}: {read_json(directory / "run.json")["status"]}', flush=True)
        finally:
            backend.unload_trellis()
    atomic_json(root / 'last_batch.json', dict(pending=len(jobs), failed=failures,
                                               finished=len(jobs) - failures))
    return failures


class InferenceBackend:
    def __init__(self, checkpoint, trellis_model, device='cuda'):
        import torch
        from wt.checkpoint import CONFIGS
        self.checkpoint = Path(checkpoint).resolve() if checkpoint else None
        self.trellis_model = Path(trellis_model).resolve()
        self.device = torch.device(device)
        self.model = self.pipeline = None
        source_root = Path(__file__).resolve().parent
        self.provenance = dict(
            wt_model=CONFIGS['r75b'],
            sources=digest({str(p.relative_to(source_root)): file_digest(p)
                            for p in sorted(source_root.rglob('*.py'))}),
            torch=torch.__version__, device=str(self.device),
            trellis_descriptor=(file_digest(self.trellis_model / 'pipeline.json')
                                if (self.trellis_model / 'pipeline.json').is_file() else None),
            dependencies=file_digest(source_root.parent / 'dependencies.lock'))
        import platform
        import numpy as np
        self.provenance['environment'] = dict(
            python=platform.python_version(), numpy=np.__version__, cuda=torch.version.cuda,
            cudnn=torch.backends.cudnn.version(),
            gpu=torch.cuda.get_device_name(self.device) if self.device.type == 'cuda' else None,
            visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'),
            deterministic_algorithms=torch.are_deterministic_algorithms_enabled(),
            cudnn_benchmark=torch.backends.cudnn.benchmark,
            cudnn_deterministic=torch.backends.cudnn.deterministic,
            matmul_allow_tf32=torch.backends.cuda.matmul.allow_tf32,
            cudnn_allow_tf32=torch.backends.cudnn.allow_tf32,
            seed_policy='python-numpy-torch-cuda-per-pipeline-entry-v1',
            wt_autocast='bfloat16', trellis_precision='checkpoint-config')
        if self.checkpoint:
            stat = self.checkpoint.stat()
            self.provenance['checkpoint'] = dict(path=str(self.checkpoint), size=stat.st_size, mtime_ns=stat.st_mtime_ns)

    def load_wt(self):
        from wt.checkpoint import build_model_and_load_ckpt
        if self.checkpoint is None:
            raise ValueError('WT / hybrid requires --ckpt pointing to a local checkpoint')
        self.model, self.model_cfg = build_model_and_load_ckpt('r75b', self.checkpoint, self.device)

    def unload_wt(self):
        self.model = None
        self.recover()

    def recover(self):
        import torch
        if self.pipeline is not None:
            for model in self.pipeline.models.values():
                model.cpu()
            self.pipeline.image_cond_model.to('cpu')
            if self.pipeline.rembg_model is not None:
                self.pipeline.rembg_model.to('cpu')
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def predict_wt(self, image, cfg, seed, directory):
        import numpy as np
        import torch
        from PIL import Image
        from wt.data import load_rgba_image, preprocess_rgba_for_model
        from wt.inference import inference_diffusion, _bypass_activation_checkpointing
        self.reset_seed(seed)
        rgba = load_rgba_image(image, auto_alpha=True)
        Image.fromarray(rgba).save(directory / 'rgba.png')
        rgb, mask, intrinsics = preprocess_rgba_for_model(rgba,
            image_size=self.model_cfg['image_size'], num_layers=6, center_crop=True,
            alpha_erode_px=cfg['alpha_erode'], bg_color=tuple(cfg['bg_color']))
        torch.manual_seed(seed)
        inference_cfg = {**self.model_cfg['inference_kwargs'], 'num_steps': cfg['wt_steps']}
        with torch.no_grad(), torch.autocast(device_type=self.device.type, dtype=torch.bfloat16,
                                            enabled=self.device.type == 'cuda'), _bypass_activation_checkpointing(self.model):
            xyz, valid, _ = inference_diffusion(self.model, rgb.to(self.device),
                gt_mask=mask.to(self.device), use_gt_mask=True,
                intrinsics=intrinsics.to(self.device), invalid_fill_mode='noise', **inference_cfg)
        save_npz(directory / 'prediction.npz', xyz=xyz[0].float().cpu().numpy(),
            mask=valid[0].cpu().numpy().astype(bool),
            rgb=(rgb[0].permute(1, 2, 0).numpy() * 255).astype(np.uint8),
            intrinsics=intrinsics[0].numpy())

    def load_trellis(self, include_stage1, modes):
        from wt.textured_mesh.pipeline import load_trellis2_pipeline
        if not (self.trellis_model / 'pipeline.json').is_file():
            raise FileNotFoundError(f'Local TRELLIS descriptor missing: {self.trellis_model}')
        # low_vram keeps weights resident in CPU RAM and moves stages to GPU;
        # checkpoint files are read once, not once per image.
        self.pipeline = load_trellis2_pipeline(self.trellis_model, self.device,
            pipeline_type=next(iter(modes)) if len(modes) == 1 else None,
            include_stage1=include_stage1)

    def unload_trellis(self):
        self.pipeline = None
        self.recover()

    def generate_mesh(self, image, cfg, seed, directory, parent):
        if (cfg['method'] == 'trellis2') != (parent is None):
            raise ValueError('Native TRELLIS requires no WT parent; hybrid requires one')
        import numpy as np
        import torch
        import trimesh
        from PIL import Image
        from wt.textured_mesh import (aggregate_camera_cloud, compute_canonical_transform,
            v4_ray_fill, inject_coords_into_trellis2, save_mesh_glb, sparse_structure_resolution)
        self.reset_seed(seed)
        params = dict(seed=seed, pipeline_type=cfg['pipeline_type'],
            shape_slat_sampler_params={'steps': cfg['shape_steps']},
            tex_slat_sampler_params={'steps': cfg['tex_steps']}, max_num_tokens=cfg['max_num_tokens'])
        metadata = dict(frame='gltf_yup', seed=seed, pipeline_type=cfg['pipeline_type'])
        with torch.no_grad():
            if parent is None:
                with Image.open(image) as source:
                    meshes = self.pipeline.run(source.copy(), **params)
            else:
                with np.load(parent / 'prediction.npz', allow_pickle=False) as data:
                    xyz, mask = data['xyz'], data['mask']
                tf = compute_canonical_transform(aggregate_camera_cloud(xyz, mask))
                resolution = sparse_structure_resolution(cfg['pipeline_type'])
                coords, count = v4_ray_fill(xyz, mask, tf.apply, res=resolution, ray_steps=cfg['ray_steps'])
                with Image.open(parent / 'rgba.png') as source:
                    meshes = inject_coords_into_trellis2(self.pipeline, source.copy(), coords,
                                                        ss_res=resolution, **params)
                metadata.update(canonical_transform=tf.to_dict(), ss_res=resolution, injected_voxels=count)
            mesh = meshes[0]
            trimesh.Trimesh(mesh.vertices.detach().cpu().numpy(), mesh.faces.detach().cpu().numpy(),
                           process=False).export(directory / 'decoded_mesh.ply')
            save_mesh_glb(directory / 'mesh.glb', mesh, texture_size=cfg['texture_size'],
                          decimation_target=cfg['decimation_target'])
        metadata.update(voxel_size=float(mesh.voxel_size),
            decoded_vertices=len(mesh.vertices), decoded_faces=len(mesh.faces),
            sparse_sampler=self.pipeline.sparse_structure_sampler_params,
            shape_sampler={**self.pipeline.shape_slat_sampler_params, 'steps': cfg['shape_steps']},
            tex_sampler={**self.pipeline.tex_slat_sampler_params, 'steps': cfg['tex_steps']})
        atomic_json(directory / 'mesh.json', metadata)
        return dict(mesh=dict(path='mesh.glb', kind='mesh', frame='gltf_yup', metadata='mesh.json'),
                    decoded_mesh=dict(path='decoded_mesh.ply', kind='mesh', frame='canonical_zup', metadata='mesh.json'))

    @staticmethod
    def reset_seed(seed):
        """Reset independent libraries at each sample/pipeline entry, including preprocessing."""
        import random
        import numpy as np
        import torch
        random.seed(seed)
        np.random.seed(seed % (2 ** 32))
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
