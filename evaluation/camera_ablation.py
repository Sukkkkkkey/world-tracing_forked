"""Camera and frozen spatial transforms for the two controlled camera experiments."""
import numpy as np
from PIL import Image
from scipy.optimize import least_squares

from wt.data import compute_object_crop, crop_with_padding, make_default_intrinsics


def crop_transform(crop, resolution=504):
    y, x, side = map(float, crop)
    if side <= 0 or resolution <= 0:
        raise ValueError("Crop and output dimensions must be positive")
    scale = resolution / side
    return np.array([[scale, 0, -x * scale],
                     [0, scale, -y * scale], [0, 0, 1]], dtype=np.float64)


def training_intrinsics(resolution):
    return make_default_intrinsics(resolution, resolution).astype(np.float64)


def mesh_crop_box(rgba, expansion):
    rows, columns = np.where(np.asarray(rgba)[..., 3] > .8 * 255)
    if not len(rows):
        raise ValueError("Empty foreground at the mesh preprocessing threshold")
    center = np.array([columns.min() + columns.max(), rows.min() + rows.max()]) / 2
    size = int(max(np.ptp(columns), np.ptp(rows)) * expansion)
    if size < 2:
        raise ValueError("Foreground too small for mesh conditioning")
    half = size // 2
    return [float(center[0] - half), float(center[1] - half),
            float(center[0] + half), float(center[1] + half)]


def frozen_spatial_spec(rgba):
    rgba = np.asarray(rgba)
    if rgba.shape != (1024, 1024, 4):
        raise ValueError("Camera ablation expects the frozen 1024-square RGBA canvas")
    return {
        "input_size": [1024, 1024],
        "wt_crop_y_x_side": list(map(int, compute_object_crop(rgba))),
        "trellis_crop_ltrb": mesh_crop_box(rgba, 1.0),
        "pixal_crop_ltrb": mesh_crop_box(rgba, 1.1),
    }


def frozen_mesh_image(image, spec, method):
    if image.mode != "RGBA" or list(image.size) != spec["input_size"]:
        raise ValueError("Frozen preprocessing requires the recorded RGBA canvas")
    key = {"trellis2": "trellis_crop_ltrb", "pixal3d": "pixal_crop_ltrb"}[method]
    output = np.array(image.crop(spec[key])).astype(np.float32) / 255
    rgb = output[..., :3] * output[..., 3:4]
    if method == "pixal3d":
        rgb = np.clip(rgb, 0, 1)
    return Image.fromarray((rgb * 255).astype(np.uint8))


def frozen_wt_image(rgba, spec):
    if list(np.asarray(rgba).shape[:2][::-1]) != spec["input_size"]:
        raise ValueError("Frozen WT preprocessing canvas changed")
    return crop_with_padding(np.asarray(rgba), *spec["wt_crop_y_x_side"])


def fixed_crop_intrinsics(original_camera, spatial):
    """Return a raw-image K whose recorded WT crop maps to the training K."""
    transform = crop_transform(spatial["wt_crop_y_x_side"])
    target = training_intrinsics(504)
    matrix = np.linalg.solve(transform, target)
    if not np.allclose(transform @ matrix, target, atol=1e-10, rtol=0):
        raise ValueError("Crop intrinsic transform failed")
    return matrix


def framed_camera(vertices, original_camera, resolution=1024):
    """Fit camera translation at fixed rotation to a centered 2/3-frame object."""
    vertices = np.asarray(vertices, dtype=np.float64)
    original = np.asarray(original_camera["T_world_to_camera"], dtype=np.float64)
    rotation = original[:3, :3]
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
        raise ValueError("Expected finite world-space vertices")
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-6) or np.linalg.det(rotation) < 0:
        raise ValueError("Expected a proper world-to-camera rotation")
    rotated = vertices @ rotation.T
    K = training_intrinsics(resolution)
    target_span = resolution * 2 / 3
    z_min = -float(rotated[:, 2].min()) + .02

    def residual(translation):
        xyz = rotated + translation
        projected = xyz[:, :2] / xyz[:, 2:3]
        projected = projected * np.diag(K)[:2] + K[:2, 2]
        lower, upper = projected.min(axis=0), projected.max(axis=0)
        center = (lower + upper) / 2
        return np.array([center[0] - resolution / 2,
                         center[1] - resolution / 2,
                         max(upper - lower) - target_span]) / resolution

    initial = original[:3, 3].copy()
    initial[2] = max(initial[2], z_min + .01)
    fit = least_squares(residual, initial,
                        bounds=([-np.inf, -np.inf, z_min], [np.inf, np.inf, np.inf]),
                        xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=100)
    if not fit.success or np.max(np.abs(residual(fit.x))) > 1e-5:
        raise ValueError(f"Framing solver failed: {fit.message}")
    transform = original.copy()
    transform[:3, 3] = fit.x
    eye = -rotation.T @ fit.x
    camera = dict(original_camera, K=K.tolist(), T_world_to_camera=transform.tolist(),
                  distance=float(np.linalg.norm(eye)),
                  horizontal_fov_degrees=float(np.rad2deg(2 * np.arctan(resolution / (2 * K[0, 0])))),
                  resolution=resolution)
    return camera, {"solver_residual_pixels": (residual(fit.x) * resolution).tolist(),
                    "solver_evaluations": fit.nfev, "camera_position_world": eye.tolist()}


def camera_match(K):
    matrix = np.asarray(K, dtype=np.float64)
    target = training_intrinsics(504)
    focal_error = np.abs(np.diag(matrix)[:2] / np.diag(target)[:2] - 1)
    principal_error = np.abs(matrix[:2, 2] - target[:2, 2])
    return {"focal_relative_error": focal_error.tolist(),
            "principal_error_pixels": principal_error.tolist(),
            "passed": bool(max(focal_error) <= .002 and max(principal_error) <= 1)}
