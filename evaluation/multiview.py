"""Geometry-only native mesh and shared-density surfel rendering."""
from types import SimpleNamespace

import numpy as np
from scipy.spatial import cKDTree

from evaluation.geometry import surface_points
from evaluation.render import make_camera
from evaluation.render_artifacts import depth_limits
from examples.prepare_gso_inventory import asset_seed

METRIC_UNITS = {
    "depth_mae": "GT_diagonal",
    "depth_rmse": "GT_diagonal",
    "depth_absrel": "ratio",
    "depth_delta1": "ratio",
    "depth_delta2": "ratio",
    "depth_image_rmse": "normalized_intensity",
    "depth_image_psnr": "dB",
    "depth_image_lpips": "distance",
    "depth_image_clipped_fraction": "ratio",
    "normal_rmse": "normalized_intensity",
    "silhouette_iou": "ratio",
    "depth_coverage": "ratio",
    "normal_mean_angle": "degree",
    "normal_psnr": "dB",
    "normal_lpips": "distance",
    "normal_coverage": "ratio",
    "normal_mse": "RGB_squared",
}
PHYSICAL_DEPTH_METRICS = {"depth_mae", "depth_rmse", "depth_absrel", "depth_delta1", "depth_delta2"}


def multiview_metric_units(config):
    include_depth = config.get("multiview_physical_depth_metrics", True)
    return {name: unit for name, unit in METRIC_UNITS.items()
            if include_depth or name not in PHYSICAL_DEPTH_METRICS}


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
        return float(self.batch(prediction[None], reference[None])[0])

    def batch(self, prediction, reference):
        """Score NHWC RGB arrays encoded in [-1, 1]."""
        torch = self.torch
        a = torch.as_tensor(np.ascontiguousarray(prediction.transpose(0, 3, 1, 2)),
                            dtype=torch.float32, device=self.device)
        b = torch.as_tensor(np.ascontiguousarray(reference.transpose(0, 3, 1, 2)),
                            dtype=torch.float32, device=self.device)
        with torch.inference_mode():
            return self.model(a, b).flatten().cpu().numpy()


def depth_image_comparison(prediction, reference, config):
    """Encode both depth maps using the same GT limits and compute image errors."""
    if config.get("depth_image_encoding", "gt_range_grayscale") != "gt_range_grayscale":
        raise ValueError("Unsupported depth image encoding")
    p = prediction["mask"] & np.isfinite(prediction["depth"]) & (prediction["depth"] > 0)
    g = reference["mask"] & np.isfinite(reference["depth"]) & (reference["depth"] > 0)
    low, high = depth_limits(reference)
    images = []
    for frame, valid in ((prediction, p), (reference, g)):
        depth = np.where(valid, frame["depth"], (low + high) / 2).astype(np.float64)
        gray = np.clip((depth - low) / (high - low), 0, 1)
        gray[~valid] = .5
        images.append(np.repeat((gray * 2 - 1)[..., None], 3, axis=-1).astype(np.float32))
    metrics = {"depth_image_rmse": None, "depth_image_psnr": None, "depth_image_lpips": None}
    overlap = p & g
    region = config.get("image_metric_region", "valid_intersection")
    if region == "full_frame":
        difference = (images[0].astype(np.float64) - images[1]) / 2
    elif region == "valid_intersection":
        difference = (images[0][overlap].astype(np.float64) - images[1][overlap]) / 2
    else:
        raise ValueError(f"Unsupported image metric region: {region}")
    if difference.size:
        mse = float(np.mean(difference ** 2))
        metrics.update(depth_image_rmse=float(np.sqrt(mse)),
                       depth_image_psnr=float(-10 * np.log10(max(mse, config["psnr_mse_floor"]))))
    clipped = p & ((prediction["depth"] < low) | (prediction["depth"] > high))
    metrics["depth_image_clipped_fraction"] = float(clipped.sum() / p.sum()) if p.any() else None
    return {
        "metrics": metrics, "prediction_rgb": images[0], "reference_rgb": images[1],
        "encoding": {"depth_limits_D": [low, high], "background_intensity": .5,
                     "metric_region": region,
                     "pred_valid_pixels": int(p.sum()), "pred_clipped_pixels": int(clipped.sum()),
                     "pred_clipped_fraction": float(clipped.sum() / p.sum()) if p.any() else None},
    }


def normal_image_comparison(prediction, reference, config):
    """Compare normal RGB images with an explicit averaging domain."""
    p = (prediction["mask"] & np.isfinite(prediction["depth"]) & (prediction["depth"] > 0)
         & prediction["normal_valid"])
    g = (reference["mask"] & np.isfinite(reference["depth"]) & (reference["depth"] > 0)
         & reference["normal_valid"])
    a = np.where(p[..., None], prediction["normals"], 0).astype(np.float32)
    b = np.where(g[..., None], reference["normals"], 0).astype(np.float32)
    region = config.get("image_metric_region", "valid_intersection")
    if region == "full_frame":
        difference = (a.astype(np.float64) - b) / 2
    elif region == "valid_intersection":
        left = prediction["normals"][p & g].astype(np.float64)
        right = reference["normals"][p & g].astype(np.float64)
        left /= np.linalg.norm(left, axis=1, keepdims=True)
        right /= np.linalg.norm(right, axis=1, keepdims=True)
        difference = (left - right) / 2
    else:
        raise ValueError(f"Unsupported image metric region: {region}")
    metrics = {"normal_mse": None, "normal_rmse": None, "normal_psnr": None}
    if difference.size:
        mse = float(np.mean(difference ** 2))
        metrics.update(normal_mse=mse, normal_rmse=float(np.sqrt(mse)),
                       normal_psnr=float(-10 * np.log10(max(mse, config["psnr_mse_floor"]))))
    return {"metrics": metrics, "prediction_rgb": a, "reference_rgb": b}


def depth_frame_metrics(prediction, reference):
    """Score fixed-camera depth arrays on their finite positive mask intersection."""
    p = prediction["mask"] & np.isfinite(prediction["depth"]) & (prediction["depth"] > 0)
    g = reference["mask"] & np.isfinite(reference["depth"]) & (reference["depth"] > 0)
    if not np.any(g):
        raise ValueError("GT has no visible geometry")
    overlap, union = p & g, p | g
    metrics = {
        "silhouette_iou": float(overlap.sum() / union.sum()),
        "depth_coverage": float(overlap.sum() / g.sum()),
        "depth_mae": None, "depth_rmse": None, "depth_absrel": None,
        "depth_delta1": None, "depth_delta2": None,
    }
    if np.any(overlap):
        predicted = prediction["depth"][overlap].astype(np.float64)
        target = reference["depth"][overlap].astype(np.float64)
        error = predicted - target
        ratio = np.maximum(predicted / target, target / predicted)
        metrics.update(
            depth_mae=float(np.abs(error).mean()),
            depth_rmse=float(np.sqrt(np.mean(error * error))),
            depth_absrel=float((np.abs(error) / target).mean()),
            depth_delta1=float((ratio < 1.25).mean()),
            depth_delta2=float((ratio < 1.25 ** 2).mean()),
        )
    return {
        "metrics": metrics,
        "pixels": {"pred": int(p.sum()), "gt": int(g.sum()), "overlap": int(overlap.sum())},
    }


def frame_metrics(prediction, reference, config, lpips_model=None):
    result = depth_frame_metrics(prediction, reference)
    p = prediction["mask"] & np.isfinite(prediction["depth"]) & (prediction["depth"] > 0)
    g = reference["mask"] & np.isfinite(reference["depth"]) & (reference["depth"] > 0)
    normal_overlap = p & g & prediction["normal_valid"] & reference["normal_valid"]
    metrics = result["metrics"]
    image_comparison = depth_image_comparison(prediction, reference, config)
    metrics.update(image_comparison["metrics"])
    result["depth_image_encoding"] = image_comparison["encoding"]
    result["image_metric_region"] = config.get("image_metric_region", "valid_intersection")
    normal_comparison = normal_image_comparison(prediction, reference, config)
    metrics.update(normal_comparison["metrics"])
    metrics.update(
        normal_coverage=float(normal_overlap.sum() / g.sum()),
        normal_mean_angle=None, normal_lpips=None,
    )
    if np.any(normal_overlap):
        a = prediction["normals"][normal_overlap].astype(np.float64)
        b = reference["normals"][normal_overlap].astype(np.float64)
        a /= np.linalg.norm(a, axis=1, keepdims=True)
        b /= np.linalg.norm(b, axis=1, keepdims=True)
        angles = np.arctan2(np.linalg.norm(np.cross(a, b), axis=1), np.sum(a * b, axis=1))
        metrics["normal_mean_angle"] = float(np.rad2deg(angles).mean())
    if lpips_model is not None:
        metrics["normal_lpips"] = lpips_model(
            normal_comparison["prediction_rgb"], normal_comparison["reference_rgb"],
        )
        metrics["depth_image_lpips"] = lpips_model(
            image_comparison["prediction_rgb"], image_comparison["reference_rgb"],
        )
    result["pixels"].update(
        normal_overlap=int(normal_overlap.sum()),
        pred_normal_valid=int((prediction["normal_valid"] & p).sum()),
    )
    return result


def compare_views(prediction, reference, config, lpips_model=None):
    views = []
    for index in range(len(reference["depth"])):
        p = {key: value[index] for key, value in prediction.items()}
        g = {key: value[index] for key, value in reference.items()}
        views.append(frame_metrics(p, g, config, lpips_model))
    rows = []
    for name, unit in multiview_metric_units(config).items():
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
