import numpy as np
import pytest
import trimesh

from evaluation.geometry import (chamfer, cube_rotations, depth_metrics, fit_similarity,
                                  register_sim3, surface_points, transform_points)
from evaluation.render import Rasterizer, make_camera, normalize_parts


def test_positive_similarity_and_no_reflection():
    points = np.random.default_rng(2).normal(size=(100, 3)) * [1, .5, .2]
    rotation = list(cube_rotations())[7]
    target = points @ rotation.T * 2.4 + [3, -2, 1]
    matrix = fit_similarity(points, target)
    assert np.linalg.det(matrix[:3, :3]) > 0
    np.testing.assert_allclose(transform_points(points, matrix), target, atol=1e-12)
    mirrored = points * [-1, 1, 1]
    matrix = fit_similarity(points, mirrored)
    assert np.linalg.det(matrix[:3, :3]) > 0
    assert np.mean((transform_points(points, matrix)-mirrored)**2) > .001


def test_metrics_sampling_registration_and_gt_units():
    mesh = trimesh.creation.box(extents=[1, .7, .3])
    points = surface_points(mesh, 400, 42)
    np.testing.assert_array_equal(points, surface_points(mesh, 400, 42))
    assert len(list(cube_rotations())) == 24
    predicted = points @ list(cube_rotations())[3].T * 4 + [5, 3, -2]
    matrix, info = register_sim3(predicted, points, iterations=30)
    metrics = chamfer(transform_points(predicted, matrix), points)
    assert metrics['cd_euclidean_mean'] < 1e-8
    assert metrics['f@0.01'] == 1
    assert info['loss'] < 1e-16
    normalized, transform, diagonal = normalize_parts([mesh], 'y')
    assert np.linalg.det(transform[:3, :3]) > 0
    assert diagonal == pytest.approx(np.linalg.norm([1, .7, .3]))
    assert np.linalg.norm(normalized[0].extents) == pytest.approx(1)


def test_depth_fit_and_missing_pixels_are_not_silently_dropped():
    gt = np.linspace(1, 2, 100).reshape(10, 10)
    mask = np.ones((10, 10), bool)
    output = depth_metrics((gt-.3)/2, gt, mask, mask)
    assert output['status'] == 'complete'
    assert output['scale'] == pytest.approx(2)
    assert output['mae'] < 1e-12 and output['delta1'] == 1
    partial = mask.copy(); partial[0] = False
    output = depth_metrics(gt, gt, partial, mask)
    assert output['status'] == 'failed' and output['depth_coverage'] == .9
    assert depth_metrics(np.ones_like(gt), gt, mask, mask)['status'] == 'failed'
    assert depth_metrics(3-gt, gt, mask, mask)['status'] == 'failed'


def test_camera_is_proper_rdf_rotation():
    camera = make_camera(83)
    T = np.asarray(camera['T_world_to_camera'])
    np.testing.assert_allclose(T[:3, :3] @ T[:3, :3].T, np.eye(3), atol=1e-12)
    assert np.linalg.det(T[:3, :3]) == pytest.approx(1)
    np.testing.assert_allclose(T[:2, 3], 0, atol=1e-12)
    assert T[2, 3] > .5


def test_invalid_native_runs_fail_in_isolated_workers(tmp_path):
    from examples.evaluate_gso import evaluate
    from wt.experiment import atomic_json, read_json
    for sample in ['a','b']:
        run=tmp_path/'samples'/sample/'trellis2/defaults-v1/seed-0042'
        atomic_json(run/'run.json',dict(status='complete',method='trellis2'))
        atomic_json(run/'wt_parent.json',dict(path='unexpected.npz'))
    assert evaluate(tmp_path,workers=2)==dict(complete=0,failed=2)
    for error in tmp_path.glob('samples/*/*/*/seed-*/evaluation_error.json'):
        assert 'unexpected WT parent' in read_json(error)['error']
        metrics=read_json(error.parent/'metrics.json')
        assert metrics['evaluation_status']=='failed'
        assert all(x['value'] is None for x in metrics['metrics'])


def test_gpu_raster_z_pixel_orientation_and_uv():
    import torch
    from PIL import Image
    if not torch.cuda.is_available():
        pytest.skip('CUDA renderer requires GPU')
    mesh = trimesh.Trimesh([[-.5,-.5,2],[.5,-.5,2],[.5,.5,2],[-.5,.5,2]], [[0,1,2],[0,2,3]], process=False)
    pixels = np.zeros((8,8,3), np.uint8)
    pixels[:4,:4]=[255,0,0]; pixels[:4,4:]=[0,255,0]
    pixels[4:,:4]=[0,0,255]; pixels[4:,4:]=[255,255,0]
    mesh.visual = trimesh.visual.texture.TextureVisuals(uv=[[0,1],[1,1],[1,0],[0,0]], image=Image.fromarray(pixels))
    renderer = Rasterizer()
    K=np.array([[32,0,16],[0,32,16],[0,0,1]])
    rgba, depth, mask, _ = renderer.render([mesh], K, np.eye(4), 32)
    assert mask.sum() == 256
    np.testing.assert_allclose(depth[mask], 2, atol=1e-6)
    assert rgba[11,11,0] > 240 and rgba[11,11,2] < 10
    assert rgba[20,11,2] > 240 and rgba[20,11,0] < 10
    assert rgba[11,20,1] > 240
    # Face batching preserves UVs, nearest depth and occlusion independent of order.
    nearer = mesh.copy(); nearer.vertices[:, 2] -= .5
    combined = trimesh.util.concatenate([mesh, nearer])
    full = renderer.render([combined], K, np.eye(4), 32, texture=False)
    chunked = Rasterizer(max_faces_per_pass=1).render([combined], K, np.eye(4), 32, texture=False)
    for a,b in zip(full,chunked):
        np.testing.assert_allclose(a,b,atol=1e-6)
    chunked_texture = Rasterizer(max_faces_per_pass=1).render([mesh], K, np.eye(4), 32)
    np.testing.assert_array_equal(chunked_texture[0],rgba)
    # Principal-point/crop translation must move the projected shape by exact pixels.
    shifted=K.copy(); shifted[0,2] -= 3
    _, _, mask2, _=renderer.render([mesh], shifted, np.eye(4), 32)
    np.testing.assert_array_equal(mask2[:, :-3], mask[:, 3:])
