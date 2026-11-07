"""Real-CUDA equivalence checks for the recorded historical memory policy."""
import datetime
import json
from pathlib import Path
from wt.experiment import atomic_json, file_digest, read_json
from scripts.recovery_memory import AUDIT, source_digests

def check_cache():
    """Verify selective cache eviction preserves sparse tensors and recomputed outputs."""
    import json
    from pathlib import Path
    import torch
    from trellis2.modules.sparse import SparseTensor, SparseConv3d
    from scripts.recovery_memory import release_conv_caches

    torch.manual_seed(42)
    coords = torch.cartesian_prod(torch.arange(16), torch.arange(16), torch.arange(16))
    coords = torch.cat([torch.zeros(len(coords), 1, dtype=torch.long), coords], dim=1).int().cuda()
    cases = []
    for channels in (16, 32, 64):
        for sparse in (False, True):
            xyz = coords[torch.randperm(len(coords), device='cuda')[:2053]].contiguous() if sparse else coords
            feats = torch.randn(len(xyz), channels, device='cuda', dtype=torch.float16)
            conv = SparseConv3d(channels, channels, 3).cuda().half().eval().requires_grad_(False)
            x = SparseTensor(feats=feats, coords=xyz)
            shape, layout = x.spatial_shape, x.layout
            with torch.no_grad():
                first = conv(x)
                stats = release_conv_caches(x, first)
                assert stats['entries'] > 0 and stats['cached_tensor_bytes'] > 0
                assert x.spatial_shape == shape and x.layout == layout
                assert torch.equal(x.feats, feats) and torch.equal(x.coords, xyz)
                second = conv(x)
                assert torch.equal(first.feats, second.feats)
            cases.append(dict(channels=channels, sparse=sparse, bitwise_equal=True, release=stats))
    result = dict(status='passed', seed=42, torch=torch.__version__, cases=cases,
                  policy='Only derived SubMConv3d neighbor caches removed; coords/features/layout/shape preserved; recomputed convolution identical')
    path = AUDIT / 'cache-release-check.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


def check_grad():
    """Verify FlexGEMM forward equivalence when inference parameters do not require grad."""
    import json
    from pathlib import Path
    import torch
    from trellis2.modules.sparse import SparseTensor, SparseConv3d

    torch.manual_seed(42)
    cases = []
    coords = torch.cartesian_prod(torch.arange(16), torch.arange(16), torch.arange(16))
    coords = torch.cat([torch.zeros(len(coords), 1, dtype=torch.long), coords], dim=1).int().cuda()
    for channels in (16, 32, 64):
        for sparse in (False, True):
            xyz = coords[torch.randperm(len(coords), device='cuda')[:2053]].contiguous() if sparse else coords
            feats = torch.randn(len(xyz), channels, device='cuda', dtype=torch.float16)
            conv = SparseConv3d(channels, channels, 3).cuda().half().eval()
            def run():
                x = SparseTensor(feats=feats.clone(), coords=xyz.clone())
                with torch.no_grad():
                    output = conv(x).feats
                cache = next(v for k, v in x.get_spatial_cache().items() if k.startswith('SubMConv3d_neighbor_cache_'))
                sizes = {k: v.numel() * v.element_size() for k, v in vars(cache).items() if isinstance(v, torch.Tensor)}
                return output, sizes
            expected, training_cache = run()
            conv.requires_grad_(False)
            actual, inference_cache = run()
            assert torch.equal(expected, actual), (channels, sparse, (expected-actual).abs().max().item())
            assert 'valid_signal_i' in training_cache and 'valid_signal_i' not in inference_cache
            assert sum(inference_cache.values()) < sum(training_cache.values())
            cases.append(dict(channels=channels, sparse=sparse, bitwise_equal=True,
                              original_cache_bytes=sum(training_cache.values()), inference_cache_bytes=sum(inference_cache.values()),
                              removed_fields=sorted(set(training_cache)-set(inference_cache))))
    result = dict(status='passed', seed=42, torch=torch.__version__, cases=cases,
                  policy='Decoder parameters require_grad=False during inference; unchanged forward parameters and outputs')
    path = AUDIT / 'inference-grad-check.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


def check_topology():
    import json
    from pathlib import Path
    import torch
    import trimesh
    from scripts import r2_topology_memory as bounded
    from o_voxel.convert import flexible_dual_grid_to_mesh
    from cumesh.remeshing import remesh_narrow_band_dc

    torch.manual_seed(42)
    bounded.CHUNK = 37  # Force many boundaries on small real CUDA cases.
    fdg, remesh = bounded.build_functions()
    cases = []
    with torch.no_grad():
        for size in (5, 8, 13):
            for sparse in (False, True):
                coords = torch.cartesian_prod(*[torch.arange(size, device='cuda', dtype=torch.int)] * 3)
                if sparse:
                    coords = coords[torch.rand(len(coords), device='cuda') > .2]
                vertices = torch.rand((len(coords), 3), device='cuda')
                flags = torch.rand((len(coords), 3), device='cuda') > .35
                weights = torch.rand((len(coords), 1), device='cuda')
                args = (coords, vertices, flags, weights, [[-.5] * 3, [.5] * 3])
                original = flexible_dual_grid_to_mesh(*args, grid_size=size)
                changed = fdg(*args, grid_size=size)
                assert all(torch.equal(a, b) for a, b in zip(original, changed)), (size, sparse)
                cases.append(dict(kind='fdg', size=size, sparse=sparse, bitwise_equal=True))
        for shape in ('box', 'sphere'):
            mesh = trimesh.creation.box() if shape == 'box' else trimesh.creation.icosphere(subdivisions=2, radius=.4)
            vertices = torch.tensor(mesh.vertices, dtype=torch.float32, device='cuda')
            faces = torch.tensor(mesh.faces, dtype=torch.int32, device='cuda')
            for resolution in (16, 32):
                args = (vertices, faces, torch.zeros(3, device='cuda'), 1.2, resolution)
                original = remesh_narrow_band_dc(*args)
                changed = remesh(*args)
                assert all(torch.equal(a, b) for a, b in zip(original, changed)), (shape, resolution)
                cases.append(dict(kind='remesh', shape=shape, resolution=resolution, bitwise_equal=True))
    path = AUDIT / 'topology-check.json'
    path.write_text(json.dumps(dict(status='passed', chunk=bounded.CHUNK, cases=cases), indent=2) + '\n')
    print('PASS', len(cases), 'CUDA cases: identical vertices and face indices')

def main():
    AUDIT.mkdir(parents=True, exist_ok=True)
    layernorm = read_json(AUDIT / 'layernorm-check.json')
    assert layernorm['status'] == 'passed'
    assert layernorm['large_case_bitwise_equal'] and layernorm['autograd_fallback']
    check_grad()
    check_cache()
    check_topology()
    reports = {str(AUDIT / name): file_digest(AUDIT / name) for name in (
        'layernorm-check.json', 'inference-grad-check.json',
        'cache-release-check.json', 'topology-check.json')}
    for path in reports:
        assert read_json(Path(path))['status'] == 'passed'
    result = dict(status='passed', finished=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_sha256=source_digests(), evidence_sha256=reports,
        validator_sha256=file_digest(Path(__file__)),
        checks=dict(layernorm_cases=36, large_layernorm_case=1, inference_grad_cases=6,
                    cache_eviction_cases=6, topology_cases=10, autograd_fallback=True),
        limitations='Operation-level bitwise checks; full pretrained output comparison is a separate required gate.')
    atomic_json(AUDIT / 'memory-component-checks.json', result)
    print('MEMORY COMPONENT CHECKS PASSED', flush=True)

if __name__ == '__main__':
    main()
