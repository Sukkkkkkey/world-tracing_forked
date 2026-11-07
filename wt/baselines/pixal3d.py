"""Pinned, local-only Pixal3D single-view inference with the experiment contract."""
from __future__ import annotations

import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from wt.experiment import CAMERA_NA, atomic_json, file_digest


CONFIG = dict(method='pixal3d', config_id='resolution1024-v1',
              pipeline_type='1024_cascade', low_vram=True, max_num_tokens=49152,
              sparse_structure_sampler_params=dict(steps=12, guidance_strength=7.5,
                  guidance_rescale=0.7, rescale_t=5.0, guidance_interval=[0.6, 1.0]),
              shape_slat_sampler_params=dict(steps=12, guidance_strength=7.5,
                  guidance_rescale=0.5, rescale_t=3.0, guidance_interval=[0.6, 1.0]),
              tex_slat_sampler_params=dict(steps=12, guidance_strength=1.0,
                  guidance_rescale=0.0, rescale_t=3.0, guidance_interval=[0.6, 0.9]),
              texture_size=4096, decimation_target=1000000,
              remesh=True, remesh_band=1, remesh_project=0,
              camera='moge-2-vitl-fov-normalized-cube', mesh_scale=1.0,
              extend_pixel=0, camera_image_resolution=512)


class Pixal3DBackend:
    def __init__(self, manifest):
        if Path(sys.prefix).resolve() != Path(os.environ['WT_PIXAL3D_ENV']).resolve():
            raise RuntimeError('Activate the isolated world_tracing_pixal3d environment')
        self.manifest_path = Path(manifest).resolve()
        self.manifest = json.loads(self.manifest_path.read_text())
        if self.manifest['status'] != 'verified':
            raise ValueError('Weights must be checksum verified')
        root = Path(__file__).resolve().parents[2]
        lock = root / 'compare_methods/pixal3d/sources.lock'
        sources = {}
        for line in lock.read_text().splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            name, revision, _ = line.split()
            source = Path(os.environ[{'Pixal3D': 'WT_PIXAL3D_ROOT',
                                     'MoGe2': 'WT_MOGE2_ROOT', 'NAF': 'WT_NAF_ROOT'}[name]])
            actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
            dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True)
            if actual != revision or dirty:
                raise ValueError(f'{name} differs from the pinned clean source')
            sources[name] = revision
        # Hash the actual assets once at startup, before any run is marked complete.
        from compare_methods.pixal3d.fetch_weights import verify
        for record in self.manifest['files']:
            if not verify(Path(record['local_path']), record):
                raise ValueError(f'Weight checksum mismatch: {record["path"]}')
        for record in self.manifest['rmbg']['files']:
            if file_digest(Path(self.manifest['rmbg']['directory']) / record['Path']) != record['Sha256']:
                raise ValueError('RMBG checksum mismatch')
        self.provenance = dict(sources=sources,
            weights_manifest_sha256=file_digest(self.manifest_path),
            pipeline_sha256=file_digest(Path(self.manifest['pipeline']) / 'pipeline.json'),
            sources_sha256={name: file_digest(root / name) for name in (
                'wt/baselines/pixal3d.py', 'wt/baselines/pixal3d_batch.py',
                'wt/experiment.py', 'examples/infer_pixal3d_batch.py',
                'compare_methods/pixal3d/env.sh', 'compare_methods/pixal3d/weights.lock.json',
                'compare_methods/pixal3d/requirements.lock.txt', 'dependencies.lock')},
            versions={name: importlib.metadata.version(name) for name in (
                'torch', 'torchvision', 'numpy', 'transformers', 'natten', 'flash-attn',
                'utils3d', 'flex_gemm', 'cumesh', 'nvdiffrast', 'o_voxel')})
        self.pipeline = None

    def load(self):
        import torch
        from pixal3d.pipelines import Pixal3DImageTo3DPipeline
        from pixal3d.trainers.flow_matching.mixins.image_conditioned_proj import DinoV3ProjFeatureExtractor
        from moge.model.v2 import MoGeModel
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        self.pipeline = Pixal3DImageTo3DPipeline.from_pretrained(self.manifest['pipeline'])
        for name, image_size, grid, naf in [('ss', 512, 16, None), ('shape_512', 512, 32, 512),
                                            ('shape_1024', 1024, 64, 512), ('tex_1024', 1024, 64, 1024)]:
            model = DinoV3ProjFeatureExtractor(model_name=self.manifest['dinov3'], image_size=image_size,
                grid_resolution=grid, use_naf_upsample=naf is not None, naf_target_size=naf)
            if naf is not None:
                model.naf_model = torch.hub.load(os.environ['WT_NAF_ROOT'], 'naf', source='local', pretrained=False)
                model.naf_model.load_state_dict(torch.load(self.manifest['naf'], map_location='cpu', weights_only=True))
                model.naf_model.eval().requires_grad_(False)
            setattr(self.pipeline, 'image_cond_model_' + name, model.eval())
        self.pipeline.low_vram = True
        self.pipeline._device = torch.device('cuda')
        self.moge = MoGeModel.from_pretrained(self.manifest['moge']).eval()

    def infer(self, image_path, directory, seed):
        import numpy as np
        import torch
        import trimesh
        from PIL import Image
        import o_voxel
        directory = Path(directory)
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        start = time.perf_counter()
        pipeline = self.pipeline
        # Call upstream preprocessing unchanged, including RMBG and alpha crop.
        with torch.no_grad():
            with Image.open(image_path) as image:
                original_size = image.size
                processed = pipeline.preprocess_image(image)
            processed.save(directory / 'preprocessed.png')
            tensor = torch.from_numpy(np.array(processed).astype(np.float32) / 255).permute(2, 0, 1).cuda()
            self.moge.cuda()
            intrinsics = self.moge.infer(tensor)['intrinsics'].squeeze().cpu().numpy()
            self.moge.cpu()
            del tensor
            torch.cuda.empty_cache()
            angle = 2 * math.atan(1 / (2 * float(intrinsics[0, 0])))
            # Exactly upstream distance_from_fov([-1,0,0], [0,511], scale=1).
            f_pixels = float((16.0 / torch.tan(torch.tensor(angle / 2.0)) * 512 / 32).item())
            camera = dict(camera_angle_x=angle, distance=f_pixels / 512, mesh_scale=1.0)
            torch.cuda.synchronize()
            camera_seconds = time.perf_counter() - start
            meshes, (_, _, resolution) = pipeline.run(processed, camera_params=camera, seed=seed,
                preprocess_image=False, return_latent=True, pipeline_type=CONFIG['pipeline_type'],
                max_num_tokens=CONFIG['max_num_tokens'], **{key: CONFIG[key] for key in (
                    'sparse_structure_sampler_params', 'shape_slat_sampler_params', 'tex_slat_sampler_params')})
            mesh = meshes[0]
            # Save BEFORE O-Voxel remeshing/decimation. Evaluation uses this artifact.
            decoded = trimesh.Trimesh(mesh.vertices.detach().cpu().numpy(),
                                     mesh.faces.detach().cpu().numpy(), process=False)
            decoded.export(directory / 'decoded_mesh.ply')
            torch.cuda.synchronize()
            generation_seconds = time.perf_counter() - start - camera_seconds
            glb = o_voxel.postprocess.to_glb(vertices=mesh.vertices, faces=mesh.faces,
                attr_volume=mesh.attrs, coords=mesh.coords, attr_layout=pipeline.pbr_attr_layout,
                grid_size=resolution, aabb=[[-0.5]*3, [0.5]*3], use_tqdm=True,
                **{key: CONFIG[key] for key in ('texture_size', 'decimation_target',
                                               'remesh', 'remesh_band', 'remesh_project')})
            rotation = np.array([[-1, 0, 0, 0], [0, 0, -1, 0], [0, -1, 0, 0], [0, 0, 0, 1]])
            glb.apply_transform(rotation)
            glb.export(directory / 'mesh.glb', extension_webp=True)
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
        atomic_json(directory / 'mesh.json', dict(camera=camera, moge_intrinsics=intrinsics.tolist(),
            original_image_size=original_size, preprocessed_image_size=processed.size,
            preprocessing='upstream alpha/RMBG, max 1024, alpha>0.8 bbox x1.1, black composite',
            decoded_frame='pixal3d_yup', decoded_to_glb=np.diag([-1., 1., -1., 1.]).tolist(),
            camera_protocol_status='N/A', camera_protocol_reason=CAMERA_NA['pixal3d'],
            resolution=resolution, vertices=len(decoded.vertices), faces=len(decoded.faces)))
        atomic_json(directory / 'runtime.json', dict(total_inference_seconds=elapsed,
            camera_seconds=camera_seconds, generation_seconds=generation_seconds,
            export_seconds=elapsed-camera_seconds-generation_seconds,
            peak_gpu_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_gpu_reserved_bytes=torch.cuda.max_memory_reserved(), gpu=torch.cuda.get_device_name()))
        torch.cuda.empty_cache()
        return dict(mesh=dict(path='mesh.glb', kind='mesh', frame='gltf_yup', metadata='mesh.json'),
                    decoded_mesh=dict(path='decoded_mesh.ply', kind='mesh', frame='pixal3d_yup', metadata='mesh.json'),
                    preprocessed=dict(path='preprocessed.png', kind='image', frame='image'))
