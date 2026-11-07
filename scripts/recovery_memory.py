"""Reviewed runtime memory policy recovered from the October R2 implementation.

Model weights, coordinates, channel reductions, topology ordering, seeds and
precision remain unchanged. Only independent-row temporaries and completed
convolution caches are bounded; installed dependencies and wt sources stay intact.
"""
from contextlib import ExitStack, contextmanager
import gc
import inspect
import json
from pathlib import Path
import torch
from wt.batch import InferenceBackend
from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import OUTPUT_ROOT
from scripts.r2_layernorm_memory import bounded_layernorm
from scripts.r2_topology_memory import build_functions, CHUNK

REPO = Path(__file__).resolve().parents[1]
AUDIT = OUTPUT_ROOT / 'validation/recovery-20261105/20261013-R2-gso-quant-v1'
DECODERS = ('shape_slat_decoder', 'tex_slat_decoder')

def source_digests():
    return {str(REPO / name): file_digest(REPO / name) for name in (
        'scripts/recovery_memory.py', 'scripts/r2_layernorm_memory.py',
        'scripts/r2_topology_memory.py')}

def policy_record():
    report = read_json(AUDIT / 'memory-component-checks.json')
    assert report['status'] == 'passed'
    assert report['source_sha256'] == source_digests()
    for path, checksum in report['evidence_sha256'].items():
        assert file_digest(Path(path)) == checksum, path
    return dict(name='historical-v6-independent-row-topology-cache-release',
        source_sha256=source_digests(),
        component_checks=str(AUDIT / 'memory-component-checks.json'),
        component_checks_sha256=file_digest(AUDIT / 'memory-component-checks.json'),
        layernorm_max_elements=16_777_216, topology_chunk=CHUNK,
        decoder_parameter_requires_grad=False,
        invariants=['input', 'seed', 'weights', 'precision', 'sampling steps',
                    'resolution', 'channel-axis reductions', 'topology ordering'])

def release_conv_caches(*tensors):
    torch.cuda.synchronize()
    before = dict(allocated=torch.cuda.memory_allocated(), reserved=torch.cuda.memory_reserved())
    seen_caches, seen_storage = set(), set()
    entries = byte_count = 0
    def count_bytes(cached):
        total = 0
        for value in vars(cached).values():
            if isinstance(value, torch.Tensor):
                storage = value.untyped_storage()
                identity = (str(value.device), storage.data_ptr())
                if identity not in seen_storage:
                    seen_storage.add(identity)
                    total += storage.nbytes()
        return total
    for tensor in tensors:
        cache = tensor._spatial_cache
        if id(cache) in seen_caches:
            continue
        seen_caches.add(id(cache))
        for scale_cache in cache.values():
            for key in list(scale_cache):
                if key.startswith('SubMConv3d_neighbor_cache_'):
                    cached = scale_cache.pop(key)
                    byte_count += count_bytes(cached)
                    entries += 1
                    del cached
    # Keep coordinates, features, layout, shape and subdivision maps intact.
    gc.collect()
    torch.cuda.empty_cache()
    return dict(entries=entries, cached_tensor_bytes=byte_count, before=before,
                after=dict(allocated=torch.cuda.memory_allocated(), reserved=torch.cuda.memory_reserved()))

@contextmanager
def release_after_decode(pipeline, records):
    original = pipeline.decode_tex_slat
    existed, prior = 'decode_tex_slat' in pipeline.__dict__, pipeline.__dict__.get('decode_tex_slat')
    def decode(slat, subs):
        result = original(slat, subs)
        records.append(dict(stage='before_fill_holes', **release_conv_caches(slat, *subs, result)))
        return result
    import wt.textured_mesh as mesh_module
    export = mesh_module.save_mesh_glb
    def save(*args, **kwargs):
        torch.cuda.synchronize()
        gc.collect()
        before = torch.cuda.memory_reserved()
        torch.cuda.empty_cache()
        records.append(dict(stage='before_glb_export', reserved_before=before, reserved_after=torch.cuda.memory_reserved()))
        return export(*args, **kwargs)
    pipeline.decode_tex_slat = decode
    mesh_module.save_mesh_glb = save
    try:
        yield
    finally:
        mesh_module.save_mesh_glb = export
        if existed:
            pipeline.decode_tex_slat = prior
        else:
            del pipeline.decode_tex_slat


@contextmanager
def inference_parameters(module):
    parameters = [(p, p.requires_grad) for p in module.parameters()]
    try:
        module.requires_grad_(False)
        yield
    finally:
        for parameter, previous in parameters:
            parameter.requires_grad_(previous)


class MemoryBoundBackend(InferenceBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.provenance['runtime_memory_policy'] = policy_record()

    def generate_mesh(self, image, cfg, seed, directory, parent):
        import cumesh
        import cumesh.remeshing
        import trellis2.models.sc_vaes.fdg_vae as fdg_module
        fdg, remesh = build_functions()
        original_fdg = fdg_module.flexible_dual_grid_to_mesh
        original_remesh = cumesh.remeshing.remesh_narrow_band_dc
        original_init, original_simplify = cumesh.CuMesh.init, cumesh.CuMesh.simplify
        events = []
        def release_then_call(method, label):
            def call(mesh, *args, **kwargs):
                torch.cuda.synchronize()
                gc.collect()
                before = torch.cuda.memory_reserved()
                torch.cuda.empty_cache()
                event = dict(stage=label, reserved_before=before,
                    reserved_after=torch.cuda.memory_reserved(), free_bytes=torch.cuda.mem_get_info()[0])
                if label == 'before_cumesh_simplify':
                    event['faces'] = mesh.num_faces
                events.append(event)
                print('CuMesh memory boundary:', event, flush=True)
                return method(mesh, *args, **kwargs)
            return call
        def release_before_topology(module, args, output):
            events.append(dict(stage='before_shape_topology', **release_conv_caches(output)))
        def fdg_record(*args, **kwargs):
            events.append(dict(stage='bounded_fdg', voxels=len(args[0])))
            return fdg(*args, **kwargs)
        def remesh_record(*args, **kwargs):
            events.append(dict(stage='bounded_remesh', vertices=len(args[0]), faces=len(args[1])))
            return remesh(*args, **kwargs)
        hook = self.pipeline.models['shape_slat_decoder'].output_layer.register_forward_hook(release_before_topology)
        fdg_module.flexible_dual_grid_to_mesh = fdg_record
        cumesh.remeshing.remesh_narrow_band_dc = remesh_record
        cumesh.CuMesh.init = release_then_call(original_init, 'before_cumesh_init')
        cumesh.CuMesh.simplify = release_then_call(original_simplify, 'before_cumesh_simplify')
        records, releases = {}, []
        try:
            with ExitStack() as stack:
                stack.enter_context(release_after_decode(self.pipeline, releases))
                for name in DECODERS:
                    stack.enter_context(inference_parameters(self.pipeline.models[name]))
                    records[name] = stack.enter_context(bounded_layernorm(self.pipeline.models[name]))
                return super().generate_mesh(image, cfg, seed, directory, parent)
        finally:
            hook.remove()
            cumesh.CuMesh.init, cumesh.CuMesh.simplify = original_init, original_simplify
            fdg_module.flexible_dual_grid_to_mesh = original_fdg
            cumesh.remeshing.remesh_narrow_band_dc = original_remesh
            atomic_json(directory / 'memory-policy.json', dict(
                policy=self.provenance['runtime_memory_policy'],
                actual=dict(decoders=records, cache_release=releases, topology=events,
                    tiled_calls=sum(v['tiled_calls'] for v in records.values()))))
