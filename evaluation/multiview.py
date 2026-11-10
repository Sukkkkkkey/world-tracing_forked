"""Geometry-only native mesh and shared-density surfel rendering."""
from types import SimpleNamespace

import numpy as np
from scipy.spatial import cKDTree

from evaluation.geometry import surface_points
from evaluation.render import make_camera
from examples.prepare_gso_inventory import asset_seed

METRIC_UNITS = {
    "depth_mae": "GT_diagonal",
    "depth_rmse": "GT_diagonal",
    "silhouette_iou": "ratio",
    "depth_coverage": "ratio",
    "normal_mean_angle": "degree",
    "normal_psnr": "dB",
    "normal_lpips": "distance",
    "normal_coverage": "ratio",
    "normal_mse": "RGB_squared",
}


def cameras(input_camera, config):
    layout = config.get("camera_layout", "orbit")
    if layout == "sphere-hammersley":
        count = config["view_count"]
        if type(count) is not int or count < 1:
            raise ValueError("view_count must be a positive integer")
        polar_offset = config["polar_offset"]
        if not 0 < polar_offset < 1:
            raise ValueError("polar_offset must lie strictly between zero and one")
        indices = np.arange(count, dtype=np.int64)
        remaining = indices.copy()
        radical_inverse = np.zeros(count, dtype=np.float64)
        bit_weight = .5
        while remaining.any():
            radical_inverse += (remaining % 2) * bit_weight
            remaining //= 2
            bit_weight *= .5
        # Equal-area latitude strata with a midpoint offset avoid pole singularities.
        heights = 2 * (indices + polar_offset) / count - 1
        elevations = np.rad2deg(np.arcsin(heights))
        azimuths = input_camera["azimuth_degrees"] + 360 * radical_inverse
    elif layout == "orbit":
        azimuths = [input_camera["azimuth_degrees"] + offset
                    for offset in config["azimuth_offsets_degrees"]]
        elevations = [config["elevation_degrees"]] * len(azimuths)
    else:
        raise ValueError(f"Unsupported camera_layout: {layout}")
    return [make_camera(
        azimuth, elevation=elevation, resolution=config["resolution"],
        fov=config["fov_degrees"], radius=config["radius"],
    ) for azimuth, elevation in zip(azimuths, elevations)]


def voxel_points(points, size):
    """Select an actual point nearest each fixed world-grid cell's center."""
    points = np.asarray(points, dtype=np.float64)
    if size <= 0 or points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("Expected Nx3 points and positive voxel size")
    points = points[np.isfinite(points).all(axis=1)]
    if not len(points):
        return points
    cells = np.floor(points / size).astype(np.int64)
    distances = np.sum((points - (cells + 0.5) * size) ** 2, axis=1)
    order = np.lexsort((points[:, 2], points[:, 1], points[:, 0], distances,
                       cells[:, 2], cells[:, 1], cells[:, 0]))
    cells = cells[order]
    first = np.r_[True, np.any(cells[1:] != cells[:-1], axis=1)]
    return points[order[first]]


def point_normals(points, config):
    """Radius-limited PCA with explicit degeneracy handling and bounded memory."""
    points = np.asarray(points, dtype=np.float64)
    tree = cKDTree(points)
    normals = np.zeros_like(points)
    counts = np.zeros(len(points), dtype=np.int32)
    valid = np.zeros(len(points), dtype=bool)
    maximum = config["normal_max_neighbors"]
    for start in range(0, len(points), 16384):
        query = points[start:start + 16384]
        distances, indices = tree.query(
            query, k=maximum, distance_upper_bound=config["normal_radius"], workers=1,
        )
        present = np.isfinite(distances)
        count = present.sum(axis=1)
        neighbors = points[np.minimum(indices, len(points) - 1)]
        centers = (neighbors * present[..., None]).sum(axis=1) / np.maximum(count[:, None], 1)
        centered = (neighbors - centers[:, None]) * present[..., None]
        covariance = np.einsum("nki,nkj->nij", centered, centered) / np.maximum(count[:, None, None], 1)
        values, vectors = np.linalg.eigh(covariance)
        good = ((count >= config["normal_min_neighbors"])
                & (values[:, 2] > 1e-20)
                & (values[:, 1] >= config["normal_min_tangent_ratio"] * values[:, 2]))
        end = start + len(query)
        counts[start:end] = count
        valid[start:end] = good
        normals[start:end][good] = vectors[good, :, 0]
    return normals, valid, counts


def prepare_surfels(points, config):
    input_count = len(points)
    points = voxel_points(points, config["voxel_size"])
    if not len(points):
        return {"points": points, "normals": points.copy(), "normal_valid": np.zeros(0, dtype=bool),
                "diagnostics": {"input_points": input_count, "retained_points": 0, "valid_normals": 0, "normal_valid_fraction": 0.0,
                                "neighbor_count_quantiles": []}}
    normals, valid, counts = point_normals(points, config)
    return {
        "points": points, "normals": normals, "normal_valid": valid,
        "diagnostics": {
            "input_points": input_count, "retained_points": len(points), "valid_normals": int(valid.sum()),
            "normal_valid_fraction": float(valid.mean()),
            "neighbor_count_quantiles": np.quantile(counts, [0, .1, .5, .9, 1]).tolist(),
        },
    }


def sample_mesh(mesh, asset_id, config):
    return surface_points(mesh, config["mesh_sample_count"], asset_seed("multiview_surface", asset_id))


def surfel_mesh(surfels, camera, config):
    points, normals = surfels["points"], surfels["normals"]
    valid = surfels["normal_valid"]
    transform = np.asarray(camera["T_world_to_camera"])
    eye = -transform[:3, :3].T @ transform[:3, 3]
    orientations = normals.copy()
    orientations[~valid] = eye - points[~valid]
    orientations /= np.maximum(np.linalg.norm(orientations, axis=1, keepdims=True), 1e-12)
    axes = np.eye(3)[np.argmin(np.abs(orientations), axis=1)]
    tangent = np.cross(orientations, axes)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    bitangent = np.cross(orientations, tangent)
    sides = config["surfel_sides"]
    angles = np.arange(sides) * (2 * np.pi / sides)
    offsets = (np.cos(angles)[None, :, None] * tangent[:, None]
               + np.sin(angles)[None, :, None] * bitangent[:, None])
    vertices = points[:, None] + config["surfel_radius"] * offsets
    fan = np.array([[0, k, k + 1] for k in range(1, sides - 1)])
    faces = (np.arange(len(points))[:, None, None] * sides + fan).reshape(-1, 3)
    # Explicit zero attributes preserve invalid normals without hiding geometry.
    return SimpleNamespace(vertices=vertices.reshape(-1, 3), faces=faces,
                           vertex_normals=np.repeat(normals, sides, axis=0))


def render_frame(renderer, mesh, camera, *, face_normals):
    _, depth, mask, normals = renderer.render(
        [mesh], camera["K"], camera["T_world_to_camera"], camera["resolution"],
        near=camera["near"], far=camera["far"], texture=False,
        normal_mode="face" if face_normals else "vertex",
    )
    normal_lengths = np.linalg.norm(normals, axis=-1)
    valid = mask & np.isfinite(normals).all(axis=-1) & (normal_lengths > .5)
    normals[valid] /= normal_lengths[valid, None]
    y, x = np.indices(mask.shape)
    intrinsics = np.asarray(camera["K"])
    rays = np.stack(((x + .5 - intrinsics[0, 2]) / intrinsics[0, 0],
                     (y + .5 - intrinsics[1, 2]) / intrinsics[1, 1],
                     np.ones(mask.shape)), axis=-1)
    away = np.sum(normals * rays, axis=-1) > 0
    normals[away] *= -1
    normals[~valid] = 0
    return {"depth": depth, "mask": mask, "normals": normals, "normal_valid": valid}


def render_views(renderer, mesh_or_surfels, views, config, *, surfel=False):
    frames = []
    for camera in views:
        mesh = surfel_mesh(mesh_or_surfels, camera, config) if surfel else mesh_or_surfels
        frames.append(render_frame(renderer, mesh, camera, face_normals=not surfel))
    return {key: np.stack([frame[key] for frame in frames]) for key in frames[0]}


class NormalLPIPS:
    def __init__(self, device="cuda"):
        import torch
        import lpips
        self.torch, self.device = torch, device
        self.model = lpips.LPIPS(net="alex", version="0.1", verbose=False).to(device).eval()

    def __call__(self, prediction, reference):
        torch = self.torch
        # Camera normals are exactly the [-1, 1] encoding of normal RGB.
        a = torch.as_tensor(prediction.transpose(2, 0, 1).copy(), device=self.device)[None]
        b = torch.as_tensor(reference.transpose(2, 0, 1).copy(), device=self.device)[None]
        with torch.inference_mode():
            return float(self.model(a, b).item())


def frame_metrics(prediction, reference, config, lpips_model=None):
    p = prediction["mask"] & np.isfinite(prediction["depth"]) & (prediction["depth"] > 0)
    g = reference["mask"] & np.isfinite(reference["depth"]) & (reference["depth"] > 0)
    if not np.any(g):
        raise ValueError("GT has no visible geometry")
    overlap, union = p & g, p | g
    normal_overlap = overlap & prediction["normal_valid"] & reference["normal_valid"]
    metrics = {
        "silhouette_iou": float(overlap.sum() / union.sum()),
        "depth_coverage": float(overlap.sum() / g.sum()),
        "normal_coverage": float(normal_overlap.sum() / g.sum()),
        "depth_mae": None, "depth_rmse": None,
        "normal_mean_angle": None, "normal_psnr": None, "normal_mse": None,
        "normal_lpips": None,
    }
    if np.any(overlap):
        error = (prediction["depth"][overlap].astype(np.float64) - reference["depth"][overlap])
        metrics.update(depth_mae=float(np.abs(error).mean()),
                       depth_rmse=float(np.sqrt(np.mean(error * error))))
    if np.any(normal_overlap):
        a = prediction["normals"][normal_overlap].astype(np.float64)
        b = reference["normals"][normal_overlap].astype(np.float64)
        a /= np.linalg.norm(a, axis=1, keepdims=True)
        b /= np.linalg.norm(b, axis=1, keepdims=True)
        angles = np.arctan2(np.linalg.norm(np.cross(a, b), axis=1), np.sum(a * b, axis=1))
        mse = float(np.mean(((a - b) / 2) ** 2))
        metrics.update(normal_mean_angle=float(np.rad2deg(angles).mean()), normal_mse=mse,
                       normal_psnr=float(-10 * np.log10(max(mse, config["psnr_mse_floor"]))))
    if lpips_model is not None:
        a = np.where(prediction["normal_valid"][..., None] & p[..., None], prediction["normals"], 0)
        b = np.where(reference["normal_valid"][..., None] & g[..., None], reference["normals"], 0)
        metrics["normal_lpips"] = lpips_model(a.astype(np.float32), b.astype(np.float32))
    return {
        "metrics": metrics,
        "pixels": {"pred": int(p.sum()), "gt": int(g.sum()), "overlap": int(overlap.sum()),
                   "normal_overlap": int(normal_overlap.sum()),
                   "pred_normal_valid": int((prediction["normal_valid"] & p).sum())},
    }


def compare_views(prediction, reference, config, lpips_model=None):
    views = []
    for index in range(len(reference["depth"])):
        p = {key: value[index] for key, value in prediction.items()}
        g = {key: value[index] for key, value in reference.items()}
        views.append(frame_metrics(p, g, config, lpips_model))
    rows = []
    for name, unit in METRIC_UNITS.items():
        values = [view["metrics"][name] for view in views]
        valid = [value for value in values if value is not None and np.isfinite(value)]
        complete = len(valid) == len(values)
        rows.append({
            "metric": name, "value": float(np.mean(valid)) if complete else None,
            "unit": unit, "status": "complete" if complete else "failed",
            "reason": None if complete else "A view has no valid comparison pixels or metric",
            "valid_views": len(valid), "total_views": len(values),
        })
    return {"views": views, "metrics": rows}
