"""Runtime-only, order-preserving topology chunking for the two large R2 meshes.

Compile guarded copies of installed functions; do not edit installed dependencies.
All sampling, coordinates, grid sizes, winding and quad split tests stay unchanged.
"""
import inspect
import torch

CHUNK = 262144


def connectivity(coords, flags, offsets, lookup, hashmap, grid, signed=False):
    quads, directions = [], []
    for start in range(0, len(coords), CHUNK):
        xyz, flag = coords[start:start + CHUNK], flags[start:start + CHUNK]
        active = flag != 0 if signed else flag
        connected = (xyz[:, None, None, :] + offsets)[active]
        keys = torch.cat([torch.zeros((len(connected) * 4, 1), dtype=torch.int,
                                      device=coords.device), connected.reshape(-1, 3)], dim=1)
        indices = lookup(*hashmap, keys, *grid).reshape(-1, 4).int()
        valid = (indices != 0xffffffff).all(dim=1)
        quads.append(indices[valid].int())
        if signed:
            directions.append(flag[active][valid].int())
    result = torch.cat(quads) if quads else torch.empty((0, 4), dtype=torch.int, device=coords.device)
    if signed:
        return result, torch.cat(directions) if directions else flags.new_empty((0,))
    return result


def weighted_triangles(quads, weights, split1, split2):
    result = torch.empty((len(quads), 6), dtype=quads.dtype, device=quads.device)
    for start in range(0, len(quads), CHUNK):
        q = quads[start:start + CHUNK]
        w = weights[q]
        result[start:start + CHUNK] = torch.where(w[:, 0] * w[:, 2] > w[:, 1] * w[:, 3],
                                                q[:, split1], q[:, split2])
    return result.reshape(-1, 3)


def oriented_triangles(vertices, quads, directions, fn):
    result = torch.empty((len(quads), 6), dtype=quads.dtype, device=quads.device)
    def alignment(t):
        n0 = torch.cross(vertices[t[:, 1]] - vertices[t[:, 0]], vertices[t[:, 2]] - vertices[t[:, 0]], dim=1)
        n1 = torch.cross(vertices[t[:, 2]] - vertices[t[:, 1]], vertices[t[:, 3]] - vertices[t[:, 1]], dim=1)
        return (n0 * n1).sum(dim=1).abs()
    for start in range(0, len(quads), CHUNK):
        q, d = quads[start:start + CHUNK], directions[start:start + CHUNK]
        t0 = torch.where((d == 1)[:, None], q[:, fn.quad_split_1_p], q[:, fn.quad_split_1_n])
        t1 = torch.where((d == 1)[:, None], q[:, fn.quad_split_2_p], q[:, fn.quad_split_2_n])
        result[start:start + CHUNK] = torch.where((alignment(t0) > alignment(t1))[:, None], t0, t1)
    return result.reshape(-1, 3)


def replace_between(source, first, last, replacement):
    assert source.count(first) == source.count(last) == 1
    begin, end = source.index(first), source.index(last)
    return source[:begin] + replacement + source[end:]


def build_functions():
    from o_voxel.convert import flexible_dual_grid_to_mesh as fdg
    from cumesh.remeshing import remesh_narrow_band_dc as remesh
    source = inspect.getsource(fdg)
    source = replace_between(source, '    edge_neighbor_voxel = coords.reshape', '    # Construct triangles',
        '    quad_indices = connectivity(coords, intersected_flag, flexible_dual_grid_to_mesh.edge_neighbor_voxel_offset, '
        '_C.hashmap_lookup_3d_cuda, hashmap, grid_size.tolist())\n'
        '    L = len(quad_indices)\n    del hashmap\n\n')
    source = replace_between(source, '            split_weight_ws = split_weight[quad_indices]', '    else:\n        assert split_weight is not None',
        '            mesh_triangles = weighted_triangles(quad_indices, split_weight, '
        'flexible_dual_grid_to_mesh.quad_split_1, flexible_dual_grid_to_mesh.quad_split_2)\n')
    namespace = dict(fdg.__globals__, connectivity=connectivity, weighted_triangles=weighted_triangles)
    exec(compile(source, '<r2-bounded-fdg>', 'exec'), namespace)
    bounded_fdg = namespace[fdg.__name__]
    source = inspect.getsource(remesh)
    source = replace_between(source, '    edge_neighbor_voxel = coords.reshape', '    # Remove unreferenced vertices',
        '    del pts, distances, subdiv_mask, pts_vert, grid_verts, distances_vert, hashmap_vert\n'
        '    quad_indices, intersected_dir = connectivity(coords, intersected, remesh_narrow_band_dc.edge_neighbor_voxel_offset, '
        '_C.hashmap_lookup_3d_cuda, hashmap_vox, (resolution, resolution, resolution), signed=True)\n'
        '    L = len(quad_indices)\n    del hashmap_vox, intersected, coords\n\n')
    source = replace_between(source, '    # if split 1', '    # --------------------------------------------------------------------------\n    # 8.',
        '    del unique_verts, vert_map, dual_verts\n'
        '    mesh_triangles = oriented_triangles(mesh_vertices, quad_indices, intersected_dir, remesh_narrow_band_dc)\n\n')
    namespace = dict(remesh.__globals__, connectivity=connectivity, oriented_triangles=oriented_triangles)
    exec(compile(source, '<r2-bounded-remesh>', 'exec'), namespace)
    return bounded_fdg, namespace[remesh.__name__]
