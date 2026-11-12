"""Recreate six icecream texture-seed runs while fixing each R1 shape latent."""
import fcntl
import hashlib
from pathlib import Path
import time
import subprocess
import sys

import numpy as np
from PIL import Image
import torch
from wt.artifacts import save_torch
import trimesh

from wt.batch import InferenceBackend
from wt.experiment import SCHEMA_VERSION, atomic_json, digest, file_digest, read_json, resolve_reference, run_directory
from wt.paths import OUTPUT_ROOT, WEIGHTS_ROOT
from wt.textured_mesh import aggregate_camera_cloud, compute_canonical_transform, sparse_structure_resolution, v4_ray_fill, save_mesh_glb

REPO = Path(__file__).resolve().parents[1]


def tensor_record(tensor):
    value = tensor.detach().cpu().contiguous()
    return dict(shape=list(value.shape), dtype=str(value.dtype),
                sha256=hashlib.sha256(value.view(torch.uint8).numpy().tobytes()).hexdigest())


def cond_record(value):
    if isinstance(value, torch.Tensor):
        return tensor_record(value)
    if isinstance(value, dict):
        return {k: cond_record(v) for k, v in value.items()}
    raise TypeError(type(value))


def cond_cpu(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu()
    return {k: cond_cpu(v) for k, v in value.items()}


def save_sparse(path, value, **extra):
    save_torch(dict(feats=value.feats.detach().cpu(), coords=value.coords.detach().cpu(), **extra), path)


def main():
    recipe = read_json(REPO / 'configs/recovery_experiments.json')['supplemental'][1]
    r1 = OUTPUT_ROOT / 'experiments/20261013-R1-object-qual-v1'
    root = OUTPUT_ROOT / 'experiments' / recipe['id']
    root.mkdir(parents=True, exist_ok=True)
    (root / 'validation.json').unlink(missing_ok=True)
    atomic_json(root / 'experiment.json', dict(schema_version=SCHEMA_VERSION, experiment_id=root.name))
    sample_id = recipe['sample']
    sample = read_json(r1 / 'samples' / sample_id / 'input.json')
    atomic_json(root / 'samples' / sample_id / 'input.json', sample)
    checkpoint = WEIGHTS_ROOT / 'huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt'
    backend = InferenceBackend(checkpoint, WEIGHTS_ROOT / 'local-pipelines/TRELLIS.2')
    sources, reports, condition_reference = {}, [], None
    backend.load_trellis(include_stage1=False, modes={'1024_cascade'})
    pipeline = backend.pipeline
    try:
        for config_id in recipe['configs']:
            old_dir = run_directory(r1, sample_id, 'wt_trellis2', config_id, recipe['wt_seed'])
            assert read_json(old_dir / 'run.json')['status'] == 'complete'
            config = read_json(old_dir / 'config.json')
            assert config['provenance'] == backend.provenance
            cfg = config['parameters']
            parent = read_json(old_dir / 'wt_parent.json')
            parent_file = resolve_reference(old_dir, parent['path']).resolve()
            assert file_digest(parent_file) == parent['sha256']
            for path in [old_dir / n for n in ('run.json', 'config.json', 'decoded_mesh.ply', 'mesh.glb', 'mesh.json', 'wt_parent.json')] + [parent_file, parent_file.parent / 'rgba.png']:
                sources[str(path)] = file_digest(path)
            with np.load(parent_file, allow_pickle=False) as data:
                xyz, mask = data['xyz'], data['mask']
            tf = compute_canonical_transform(aggregate_camera_cloud(xyz, mask))
            coords, raw_voxels = v4_ray_fill(xyz, mask, tf.apply,
                res=sparse_structure_resolution(cfg['pipeline_type']), ray_steps=cfg['ray_steps'])
            backend.reset_seed(recipe['shape_seed'])
            with Image.open(parent_file.parent / 'rgba.png') as image:
                condition_image = pipeline.preprocess_image(image.copy())
            coords4 = np.concatenate([np.zeros((len(coords), 1), dtype=np.int64), coords.astype(np.int64)], 1)
            coordinates = torch.from_numpy(coords4).cuda().to(torch.int32).contiguous()
            torch.manual_seed(recipe['shape_seed'])
            torch.cuda.manual_seed(recipe['shape_seed'])
            cache = root / '_cache' / config_id
            cache.mkdir(parents=True, exist_ok=True)
            shape_started = time.monotonic()
            with torch.no_grad():
                cond512 = pipeline.get_cond([condition_image], 512)
                cond1024 = pipeline.get_cond([condition_image], 1024)
                condition = {'512': cond_record(cond512), '1024': cond_record(cond1024)}
                if condition_reference is None:
                    condition_reference = condition
                assert condition == condition_reference, 'The two groups must use identical image-condition tensors'
                save_torch({'512': cond_cpu(cond512), '1024': cond_cpu(cond1024)}, cache / 'conditions.pt')
                shape, resolution = pipeline.sample_shape_slat_cascade(
                    cond512, cond1024, pipeline.models['shape_slat_flow_model_512'],
                    pipeline.models['shape_slat_flow_model_1024'], 512, 1024, coordinates,
                    {'steps': cfg['shape_steps']}, cfg['max_num_tokens'])
                save_sparse(cache / 'shape_latent.pt', shape, resolution=resolution)
                shape_signature = dict(feats=tensor_record(shape.feats), coords=tensor_record(shape.coords))
                shape_seconds = time.monotonic() - shape_started
                reference = trimesh.load(old_dir / 'decoded_mesh.ply', process=False)
                for seed in recipe['texture_seeds']:
                    folder = run_directory(root, sample_id, 'wt_trellis2', config_id, seed)
                    folder.mkdir(parents=True, exist_ok=True)
                    params = dict(cfg, wt_seed=recipe['wt_seed'], shape_seed=recipe['shape_seed'], texture_seed=seed,
                        texture_seed_policy='reset-python-numpy-torch-cuda-immediately-before-texture-sampler')
                    historical = read_json(REPO / 'configs/historical_workbook_configs.json')
                    expected = next(x['parameters'] for x in historical
                        if x['identity'][:4] == [root.name, 'wt_trellis2', config_id, seed])
                    assert params == expected, 'Supplemental parameters differ from the original workbook'
                    provenance = dict(backend.provenance, r1_parent_sha256=parent['sha256'],
                                      fixed_shape=shape_signature, image_conditions=condition)
                    config_hash = digest(dict(config=params, provenance=provenance))
                    state = dict(schema_version=SCHEMA_VERSION, sample_id=sample_id, method='wt_trellis2',
                        config_id=config_id, seed=seed, config_hash=config_hash, input_sha256=sample['sha256'])
                    atomic_json(folder / 'config.json', dict(parameters=params, provenance=provenance))
                    atomic_json(folder / 'run.json', dict(state, status='running'))
                    atomic_json(folder / 'wt_parent.json', dict(parent, path=str(parent_file)))
                    started = time.monotonic()
                    backend.reset_seed(seed)
                    texture = pipeline.sample_tex_slat(cond1024, pipeline.models['tex_slat_flow_model_1024'],
                        shape, {'steps': cfg['tex_steps']})
                    save_sparse(folder / 'texture_latent.pt', texture)
                    mesh = pipeline.decode_latent(shape, texture, resolution)[0]
                    vertices, faces = mesh.vertices.cpu().numpy(), mesh.faces.cpu().numpy()
                    geometry_equal = np.array_equal(vertices, reference.vertices) and np.array_equal(faces, reference.faces)
                    assert geometry_equal, 'Reconstructed pre-export geometry differs from the new R1 result'
                    assert dict(feats=tensor_record(shape.feats), coords=tensor_record(shape.coords)) == shape_signature
                    trimesh.Trimesh(vertices, faces, process=False).export(folder / 'decoded_mesh.ply')
                    save_torch(dict(vertices=mesh.vertices.cpu(), faces=mesh.faces.cpu(),
                        coords=mesh.coords.cpu(), attrs=mesh.attrs.cpu(), layout=mesh.layout,
                        voxel_size=float(mesh.voxel_size)), folder / 'prebake.pt')
                    save_mesh_glb(folder / 'mesh.glb', mesh, texture_size=cfg['texture_size'],
                        decimation_target=cfg['decimation_target'])
                    atomic_json(folder / 'mesh.json', dict(frame='gltf_yup', pipeline_type=cfg['pipeline_type'],
                        canonical_transform=tf.to_dict(), injected_voxels=raw_voxels, ss_res=32,
                        decoded_vertices=len(vertices), decoded_faces=len(faces), voxel_size=float(mesh.voxel_size),
                        wt_seed=recipe['wt_seed'], shape_seed=recipe['shape_seed'], texture_seed=seed,
                        texture_seed_policy='reset-python-numpy-torch-cuda-immediately-before-texture-sampler'))
                    hashes = {name: file_digest(folder / name) for name in
                              ('decoded_mesh.ply', 'mesh.glb', 'mesh.json', 'texture_latent.pt', 'prebake.pt')}
                    atomic_json(folder / 'runtime.json', dict(shape_seconds=shape_seconds,
                        texture_decode_export_seconds=time.monotonic() - started, shared_shape=True))
                    atomic_json(folder / 'run.json', dict(state, status='complete', artifact_sha256=hashes,
                        artifacts=dict(mesh=dict(path='mesh.glb', kind='mesh', frame='gltf_yup', metadata='mesh.json'),
                                       decoded_mesh=dict(path='decoded_mesh.ply', kind='mesh', frame='canonical_zup', metadata='mesh.json'))))
                    scene = trimesh.load(folder / 'mesh.glb', force='scene', process=False)
                    assert scene.geometry and np.isfinite(scene.bounds).all()
                    assert any(getattr(g.visual, 'material', None) is not None for g in scene.geometry.values())
                    reports.append(dict(config_id=config_id, texture_seed=seed, preexport_geometry_matches_r1=geometry_equal,
                        fixed_shape=shape_signature, image_conditions=condition, artifacts=hashes))
                    print('TEXTURE', len(reports), '/', recipe['runs'], config_id, seed, flush=True)
                    del texture, mesh, scene
                    torch.cuda.empty_cache()
                del shape, cond512, cond1024, reference
    finally:
        backend.unload_trellis()
    assert len(reports) == recipe['runs']
    assert all(file_digest(Path(path)) == checksum for path, checksum in sources.items())
    atomic_json(root / 'validation.json', dict(status='passed', runs=reports, source_sha256=sources,
        recipe=recipe, identical_image_conditions=True, fixed_preexport_geometry=True,
        script_sha256=file_digest(Path(__file__)), glb_topology_identical_not_claimed=True,
        seed_note='Texture RNG is independently reset; texture seed 42 differs from the R1 full-pipeline RNG state.'))
    subprocess.run([sys.executable, '-uB', str(REPO / 'scripts/render_texture_review.py'), '--experiment', str(root)], check=True)
    print(root, flush=True)


if __name__ == '__main__':
    with (REPO / '.runtime/recovery-gpu.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main()
