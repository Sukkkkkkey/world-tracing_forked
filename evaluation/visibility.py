"""Input-camera visibility on fixed GT samples and region geometry metrics."""
import numpy as np
from rtree.index import Index
from trimesh import triangles
from trimesh.constants import tol
from scipy.spatial import cKDTree
from trimesh.ray.ray_triangle import RayMeshIntersector

from evaluation.baseline import shape_metrics
from evaluation.geometry import transform_points

REGIONS = {"visible": 1, "occluded": 2, "out_of_view": 0}
INVALID = 3



def first_hits(mesh, points, camera, selected, batch_size, parallel_epsilon=1e-12):
    """Use projected triangle bounds to accelerate fixed-camera exact ray queries."""
    matrix = np.asarray(camera["T_world_to_camera"], dtype=np.float64)
    intrinsics = np.asarray(camera["K"], dtype=np.float64)
    origin = np.linalg.inv(matrix)[:3, 3]
    offsets = points - origin
    distance = np.linalg.norm(offsets, axis=1)
    directions = np.divide(offsets, distance[:, None], out=np.zeros_like(offsets),
                           where=distance[:, None] > 0)
    result = np.full(len(points), np.nan, dtype=np.float64)
    vertices = transform_points(mesh.vertices, matrix)
    if np.any(vertices[:, 2] <= 0):
        intersector = RayMeshIntersector(mesh)
        for start in range(0, len(selected), batch_size):
            indices = selected[start:start + batch_size]
            _, rays, hits = intersector.intersects_id(
                np.broadcast_to(origin, (len(indices), 3)).copy(), directions[indices],
                return_locations=True, multiple_hits=False)
            hits = np.asarray(hits, dtype=np.float64).reshape(-1, 3)
            result[indices[rays]] = np.linalg.norm(hits - origin, axis=1)
        return result
    projected = vertices @ intrinsics.T
    pixels = projected[:, :2] / projected[:, 2, None]
    triangle_pixels = pixels[mesh.faces]
    bounds = np.concatenate((triangle_pixels.min(axis=1), triangle_pixels.max(axis=1)), axis=1)
    # Positive camera-space depths make the projected triangle bounds conservative.
    index = Index((i, tuple(bound), None) for i, bound in enumerate(bounds))
    point_pixels = transform_points(points, matrix) @ intrinsics.T
    point_pixels = point_pixels[:, :2] / point_pixels[:, 2, None]
    padding = 1e-7
    for start in range(0, len(selected), batch_size):
        indices = selected[start:start + batch_size]
        face_ids, ray_ids = [], []
        for ray in indices:
            u, v = point_pixels[ray]
            candidates = list(index.intersection((u-padding, v-padding, u+padding, v+padding)))
            face_ids.extend(candidates)
            ray_ids.extend([ray] * len(candidates))
        if not face_ids:
            continue
        face_ids = np.asarray(face_ids, dtype=np.int64)
        ray_ids = np.asarray(ray_ids, dtype=np.int64)
        candidate_triangles = mesh.triangles[face_ids]
        normals = mesh.face_normals[face_ids]
        denominator = np.sum(normals * directions[ray_ids], axis=1)
        numerator = np.sum(normals * (candidate_triangles[:, 0] - origin), axis=1)
        valid = np.abs(denominator) > parallel_epsilon
        parameter = numerator[valid] / denominator[valid]
        hits = origin + parameter[:, None] * directions[ray_ids[valid]]
        barycentric = triangles.points_to_barycentric(candidate_triangles[valid], hits, method="cross")
        contained = ((barycentric > -tol.zero).all(axis=1)
                     & (barycentric < 1 + tol.zero).all(axis=1))
        rays = ray_ids[valid][contained]
        offsets_hit = hits[contained] - origin
        forward = np.sum(offsets_hit * directions[rays], axis=1) > 0
        distances = np.linalg.norm(offsets_hit[forward], axis=1)
        nearest = np.full(len(points), np.inf, dtype=np.float64)
        np.minimum.at(nearest, rays[forward], distances)
        found = np.isfinite(nearest)
        result[found] = nearest[found]
    index.close()
    return result


def surface_anchors(mesh, points, selected, tolerance):
    """Find bounded closest triangle points with scale-independent float64 arithmetic."""
    anchors = points.copy()
    distances = np.zeros(len(points), dtype=np.float64)
    distances[selected] = np.inf
    tree = mesh.triangles_tree
    for start in range(0, len(selected), 1024):
        face_ids, point_ids = [], []
        for index in selected[start:start + 1024]:
            bounds = np.concatenate((points[index] - tolerance, points[index] + tolerance))
            candidates = list(tree.intersection(bounds))
            face_ids.extend(candidates)
            point_ids.extend([index] * len(candidates))
        if not face_ids:
            continue
        face_ids = np.asarray(face_ids, dtype=np.int64)
        point_ids = np.asarray(point_ids, dtype=np.int64)
        faces = mesh.triangles[face_ids]
        targets = points[point_ids]
        normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
        squared_norm = np.sum(normals * normals, axis=1)
        factor = np.divide(np.sum((targets - faces[:, 0]) * normals, axis=1), squared_norm,
                           out=np.zeros(len(faces)), where=squared_norm > 0)
        plane_points = targets - factor[:, None] * normals
        with np.errstate(invalid="ignore", divide="ignore"):
            barycentric = triangles.points_to_barycentric(faces, plane_points, method="cross")
        interior = np.isfinite(barycentric).all(axis=1) & (barycentric >= -tol.zero).all(axis=1)
        edge = np.roll(faces, -1, axis=1) - faces
        denominator = np.sum(edge * edge, axis=2)
        parameters = np.divide(np.sum((targets[:, None] - faces) * edge, axis=2), denominator,
                               out=np.zeros_like(denominator), where=denominator > 0)
        edge_points = faces + np.clip(parameters, 0, 1)[..., None] * edge
        edge_distance = np.sum((edge_points - targets[:, None]) ** 2, axis=2)
        closest = edge_points[np.arange(len(faces)), edge_distance.argmin(axis=1)]
        closest[interior] = plane_points[interior]
        squared_distance = np.sum((closest - targets) ** 2, axis=1)
        order = np.lexsort((face_ids, squared_distance, point_ids))
        ordered_ids = point_ids[order]
        first = np.concatenate(([True], ordered_ids[1:] != ordered_ids[:-1]))
        choices = order[first]
        anchors[point_ids[choices]] = closest[choices]
        distances[point_ids[choices]] = np.sqrt(squared_distance[choices])
    return anchors, distances

def gt_visibility(mesh, points, camera, tolerance=1e-4, batch_size=256,
                  surface_tolerance=1e-6, parallel_epsilon=1e-12):
    """Trace double-precision first hits without face-winding culling."""
    points = np.asarray(points, dtype=np.float64)
    matrix = np.asarray(camera["T_world_to_camera"], dtype=np.float64)
    local = transform_points(points, matrix)
    projected = local @ np.asarray(camera["K"], dtype=np.float64).T
    with np.errstate(divide="ignore", invalid="ignore"):
        pixels = projected[:, :2] / projected[:, 2, None]
    inside = (np.isfinite(pixels).all(axis=1)
              & (local[:, 2] >= camera["near"]) & (local[:, 2] <= camera["far"])
              & (pixels >= 0).all(axis=1)
              & (pixels < camera["resolution"]).all(axis=1))
    ray_targets, surface_distance = surface_anchors(mesh, points, np.flatnonzero(inside),
                                                      surface_tolerance)
    on_surface = surface_distance <= surface_tolerance
    origin = np.linalg.inv(matrix)[:3, 3]
    target_distance = np.linalg.norm(ray_targets - origin, axis=1)
    first_distance = first_hits(mesh, ray_targets, camera, np.flatnonzero(inside & on_surface),
                                batch_size, parallel_epsilon=parallel_epsilon)
    gap = target_distance - first_distance
    hit = inside & np.isfinite(first_distance) & (first_distance > 0)
    consistent = hit & on_surface & (gap >= -tolerance)
    labels = np.zeros(len(points), dtype=np.uint8)
    labels[inside] = INVALID
    labels[consistent] = REGIONS["occluded"]
    labels[consistent & (np.abs(gap) <= tolerance)] = REGIONS["visible"]
    sensitivity = {}
    for threshold in (5e-5, 1e-4, 2e-4):
        visible = hit & (np.abs(gap) <= threshold)
        sensitivity[str(threshold)] = {
            "visible": int(visible.sum()),
            "changed_from_default": int((visible != (labels == REGIONS["visible"])).sum()),
        }
    diagnostics = {
        "status": "complete" if not np.any(labels == INVALID) else "invalid",
        "backend": "trimesh-float64-projected-rtree",
        "tolerance": tolerance, "batch_size": batch_size,
        "surface_tolerance": surface_tolerance, "parallel_epsilon": parallel_epsilon,
        "surface_projection_max": (float(surface_distance[np.isfinite(surface_distance)].max())
                                   if np.isfinite(surface_distance).any() else None),
        "surface_projection_p95": (float(np.quantile(surface_distance[np.isfinite(surface_distance)], .95))
                                   if np.isfinite(surface_distance).any() else None),
        "off_surface": int((inside & ~on_surface).sum()),
        "counts": {name: int((labels == code).sum()) for name, code in REGIONS.items()},
        "invalid": int((labels == INVALID).sum()),
        "missed": int((inside & ~np.isfinite(first_distance)).sum()),
        "hit_beyond_target": int((hit & (gap < -tolerance)).sum()),
        "sensitivity": sensitivity,
    }
    arrays = {"labels": labels, "first_hit_distance": first_distance,
              "target_distance": target_distance, "in_frustum": inside,
              "ray_targets": ray_targets, "surface_projection_distance": surface_distance}
    return diagnostics, arrays


def region_metrics(prediction, reference, gt_labels):
    """Transfer GT labels once, then recompute both distances within each region."""
    prediction = np.asarray(prediction)
    reference = np.asarray(reference)
    gt_labels = np.asarray(gt_labels)
    if gt_labels.shape != (len(reference),):
        raise ValueError("GT labels must match the frozen evaluation samples")
    nearest = cKDTree(reference).query(prediction, workers=1)[1]
    prediction_labels = gt_labels[nearest]
    arrays = {"prediction_labels": prediction_labels, "gt_labels": gt_labels}
    results = {}
    for name, code in REGIONS.items():
        pred = prediction[prediction_labels == code]
        gt = reference[gt_labels == code]
        row = {"prediction_points": len(pred), "gt_points": len(gt)}
        if len(gt) and len(pred):
            metrics, forward, backward = shape_metrics(pred, gt, return_distances=True)
            row.update(status="complete", metrics=metrics)
        else:
            forward, backward = np.empty(0), np.empty(0)
            metrics = {"cd_euclidean_mean": None, "cd_squared_mean": None,
                       "pred_to_gt_mean": None, "gt_to_pred_mean": None}
            for threshold in (.01, .05):
                metrics[f"precision@{threshold:.2f}"] = None
                metrics[f"recall@{threshold:.2f}"] = 0. if len(gt) else None
                metrics[f"f@{threshold:.2f}"] = 0. if len(gt) else None
            row.update(status="empty_prediction" if len(gt) else "not_applicable",
                       metrics=metrics)
        if np.any(gt_labels == INVALID):
            row.update(status="invalid_visibility", metrics={key: None for key in row["metrics"]})
        results[name] = row
        arrays[f"{name}_pred_to_gt"] = forward
        arrays[f"{name}_gt_to_pred"] = backward
    return results, arrays


def paired_export_geometry(evaluation, reference, labels, decoded, native_area, gt_area):
    """Measure GLB in the exact decoded transform and retain both operands."""
    matrix = np.asarray(decoded["registration"]["matrix"], dtype=np.float64)
    aligned = transform_points(evaluation, matrix)
    shape, forward, backward = shape_metrics(aligned, reference, return_distances=True)
    regions, arrays = region_metrics(aligned, reference, labels)
    arrays.update(full_pred_to_gt=forward, full_gt_to_pred=backward)
    scale = float(np.cbrt(np.linalg.det(matrix[:3, :3])))
    result = {
        "matrix": matrix.tolist(),
        "decoded": {name: decoded[name] for name in ("shape", "regions", "geometry")},
        "glb": {"shape": shape, "regions": regions,
                "geometry": {"native_area": native_area,
                             "aligned_area": native_area * scale ** 2,
                             "area_gt_ratio": native_area * scale ** 2 / gt_area}},
    }
    return result, arrays
