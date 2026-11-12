"""Independent projection, scale, and frame checks (not just inverse pairs)."""
import json

import numpy as np
import pytest
import torch

from wt.data import (compute_object_crop, compute_clip_shared_crop,
                     preprocess_rgba_for_model, preprocess_clip_for_model)
from wt.inference import _depth_to_xyz, denormalize_xyz_torch, XYZ_MEAN, XYZ_STD
from wt.intrinsics import solve_intrinsics_from_xyz
from wt.textured_mesh import (CanonicalTransform, GLB_TO_CANONICAL,
                             aggregate_camera_cloud, compute_canonical_transform,
                             glb_to_camera)
from wt.textured_mesh.voxelise import _xyz_to_grid, _grid_to_coords


@pytest.mark.parametrize("clip", [False, True])
@pytest.mark.parametrize("crop", [False, True])
def test_original_camera_projection_survives_crop_resize(clip, crop):
    rgba = np.zeros((60, 100, 4), dtype=np.uint8)
    rgba[2:22, 3:33, 3] = 255  # asymmetric crop, includes padding
    K = np.array([[120., 0, 47.], [0, 110., 28.], [0, 0, 1.]])
    before = K.copy()
    if clip:
        frames = [rgba, rgba.copy()]
        if crop:
            y, x, side = compute_clip_shared_crop(frames)
        else:
            y, x, side = 0, 20, 60
        result = preprocess_clip_for_model(frames, 42, 2, intrinsics_override=K, center_crop=crop)
        h = w = side
    else:
        if crop:
            y, x, side = compute_object_crop(rgba)
            h = w = side
        else:
            x = y = 0
            h, w = rgba.shape[:2]
        result = preprocess_rgba_for_model(rgba, 42, 2, intrinsics_override=K, center_crop=crop)
    rays = np.array([[.1, .2, 1], [-.2, .1, 1], [0, 0, 1]])
    original_pixels = rays @ K.T
    expected = (original_pixels[:, :2] - [x, y]) * [42 / w, 42 / h]
    actual = rays @ result[2][0].numpy().T
    np.testing.assert_allclose(actual[:, :2], expected, atol=2e-6)
    np.testing.assert_array_equal(K, before)


def test_pixel_centres_project_and_solve_back_without_half_pixel_shift():
    K = torch.tensor([[20., 0, 4.2], [0, 23., 3.7], [0, 0, 1.]])
    depth = torch.linspace(1, 3, 80).reshape(1, 1, 8, 10)
    mask = torch.ones_like(depth, dtype=torch.bool)
    xyz = _depth_to_xyz(depth, K, mask)[0, 0].numpy()
    pixels = xyz @ K.numpy().T
    pixels = pixels[..., :2] / pixels[..., 2:]
    v, u = np.mgrid[:8, :10]
    np.testing.assert_allclose(pixels, np.stack([u + .5, v + .5], -1), atol=1e-6)
    solved, _ = solve_intrinsics_from_xyz(xyz, mask[0, 0].numpy())
    np.testing.assert_allclose(solved, K.numpy(), atol=2e-6)
    xyz[0, 0, 0] = np.nan
    solved, _ = solve_intrinsics_from_xyz(xyz, mask[0, 0].numpy())
    np.testing.assert_allclose(solved, K.numpy(), atol=2e-6)


def test_degenerate_camera_fit_returns_fallback():
    xyz = np.ones((8, 8, 3))
    assert solve_intrinsics_from_xyz(xyz, np.ones((8, 8), dtype=bool))[0] is None


def test_axes_and_serialized_scale_restore_camera_points():
    tf = CanonicalTransform(centroid=[.2, .3, .4], scale=2.0)
    # Camera +x/right, +y/down, +z/forward -> canonical +x, -z, +y.
    basis = np.eye(3)
    expected = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
    np.testing.assert_allclose(tf.apply(basis), (expected - tf.centroid) * 2)
    assert np.linalg.det(expected) == pytest.approx(1)
    assert np.linalg.det(GLB_TO_CANONICAL) == pytest.approx(1)
    # Independent known mapping from canonical to glTF: (x, z, -y).
    canonical = tf.apply(basis)
    glb = np.stack([canonical[:, 0], canonical[:, 2], -canonical[:, 1]], -1)
    restored_tf = CanonicalTransform(**json.loads(json.dumps(tf.to_dict())))
    np.testing.assert_allclose(glb_to_camera(glb, restored_tf), basis, atol=1e-6)
    assert tf.apply(np.zeros(3)).shape == (3,)


def test_full_cloud_fit_preserves_extrema_and_is_scale_invariant():
    xyz = np.zeros((1, 1, 400_001, 3), dtype=np.float32)
    xyz[0, 0, -1] = [100, 10, 2]
    cloud = aggregate_camera_cloud(xyz, np.ones(xyz.shape[:-1], dtype=bool))
    assert len(cloud) == 400_001  # scale fitting must not silently subsample
    fit = compute_canonical_transform(cloud)
    assert np.abs(fit.apply(cloud)).max() <= .45000001
    cloud = np.random.default_rng(42).normal(size=(100, 3))
    first = compute_canonical_transform(cloud)
    second = compute_canonical_transform(cloud * 7 + [2, 3, 4])
    np.testing.assert_allclose(first.apply(cloud), second.apply(cloud * 7 + [2, 3, 4]), atol=1e-12)
    assert second.scale == pytest.approx(first.scale / 7)


@pytest.mark.parametrize("grid", [32, 64, 96])
def test_quantization_uses_xyz_order_and_voxel_centres(grid):
    indices = np.array([[0, 2, 3], [grid - 1, grid - 2, 1]])
    points = (indices + .5) / grid - .5
    actual = _grid_to_coords(_xyz_to_grid(points, grid))
    np.testing.assert_array_equal(actual, indices)
    assert np.max(np.abs((actual + .5) / grid - .5 - points)) < 1e-12


@pytest.mark.parametrize("scale", [0, -1, np.inf, np.nan])
def test_invalid_similarity_scale_rejected(scale):
    with pytest.raises(ValueError, match="scale"):
        CanonicalTransform([0, 0, 0], scale)


def test_released_normalizations_are_not_interchangeable():
    values = torch.tensor([[[.2, -.3, .7]]])
    metric = denormalize_xyz_torch(values, "zscore")
    np.testing.assert_allclose(metric, values.numpy() * XYZ_STD + XYZ_MEAN, atol=1e-6)
    relative = denormalize_xyz_torch(values, "median_log_global")
    assert relative[..., 2].item() == pytest.approx(np.exp(.7))
    assert not torch.allclose(metric, relative)
