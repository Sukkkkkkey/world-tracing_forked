"""Geometry and selection rules for the second baseline evaluation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
import trimesh

from evaluation.geometry import chamfer, cube_rotations, register_sim3, transform_points
from wt.experiment import read_json
from wt.textured_mesh.canon import GLB_TO_CANONICAL


def principal_frame(points):
    points = np.asarray(points, dtype=np.float64)
    center = points.mean(axis=0)
    centered = points - center
    eigenvalues, axes = np.linalg.eigh(centered.T @ centered / len(points))
    axes = axes[:, ::-1]
    axes[:, -1] *= np.sign(np.linalg.det(axes))
    frame = np.eye(4)
    frame[:3, :3] = axes
    frame[:3, 3] = center
    return frame, eigenvalues[::-1]


def register_shape(prediction, reference, workers=4):
    """Run the existing 24-start solver in each cloud's principal frame."""
    prediction_frame, prediction_values = principal_frame(prediction)
    reference_frame, reference_values = principal_frame(reference)
    prediction_local = transform_points(prediction, np.linalg.inv(prediction_frame))
    reference_local = transform_points(reference, np.linalg.inv(reference_frame))
    def solve(rotation):
        return register_sim3(prediction_local, reference_local, initial_rotations=[rotation])
    with ThreadPoolExecutor(max_workers=workers) as executor:
        solutions = list(executor.map(solve, cube_rotations()))
    selected = min(range(len(solutions)), key=lambda index: solutions[index][1]["loss"])
    local, diagnostics = solutions[selected]
    diagnostics["starts"] = [
        {**info["starts"][0], "start": index} for index, (_, info) in enumerate(solutions)]
    matrix = reference_frame @ local @ np.linalg.inv(prediction_frame)
    diagnostics.update(initialization="principal-frames-24-proper-rotations",
                       prediction_covariance_eigenvalues=prediction_values.tolist(),
                       reference_covariance_eigenvalues=reference_values.tolist())
    return matrix, diagnostics


def load_stage_mesh(directory, stage):
    directory = Path(directory)
    filename = {"decoded": "decoded_mesh.ply", "glb": "mesh.glb"}[stage]
    mesh = trimesh.load(directory / filename, force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
        raise ValueError("Expected a nonempty triangle mesh")
    if stage == "glb":
        metadata = read_json(directory / "mesh.json")
        state = read_json(directory / "run.json")
        inverse = np.eye(4)
        inverse[:3, :3] = GLB_TO_CANONICAL
        if state["method"] == "pixal3d":
            inverse = np.linalg.inv(np.asarray(metadata["decoded_to_glb"], dtype=float))
        mesh.apply_transform(inverse)
    return mesh


def point_samples(points, registration_seed, evaluation_seed):
    points = np.asarray(points)
    points = np.unique(points[np.isfinite(points).all(axis=1)], axis=0)
    if not len(points):
        raise ValueError("No valid prediction points")
    registration = np.random.default_rng(registration_seed).choice(
        len(points), min(10000, len(points)), replace=False)
    evaluation = np.random.default_rng(evaluation_seed).choice(
        len(points), min(100000, len(points)), replace=False)
    return points, points[registration], points[evaluation]


def shape_metrics(prediction, reference, *, return_distances=False):
    from scipy.spatial import cKDTree
    result = chamfer(prediction, reference)
    forward = cKDTree(reference).query(prediction, workers=1)[0]
    backward = cKDTree(prediction).query(reference, workers=1)[0]
    result["pred_to_gt_mean"] = float(forward.mean())
    result["gt_to_pred_mean"] = float(backward.mean())
    for threshold in (.01, .05):
        result[f"precision@{threshold:.2f}"] = float((forward < threshold).mean())
        result[f"recall@{threshold:.2f}"] = float((backward < threshold).mean())
    if return_distances:
        return result, forward, backward
    return result


def select_best(candidates, seeds):
    """Select one seed by shape CD, with an explicit fixed candidate budget."""
    by_seed = {record["seed"]: record for record in candidates}
    if len(by_seed) != len(candidates):
        raise ValueError("Duplicate candidates for an asset, method and stage")
    if set(by_seed) != set(seeds) or any(
            record["status"] not in ("complete", "failed") for record in candidates):
        return {"status": "pending", "expected_seeds": list(seeds),
                "present_seeds": sorted(by_seed)}
    valid = [record for record in candidates if record["status"] == "complete"
             and np.isfinite(record["shape"]["cd_euclidean_mean"])]
    if not valid:
        return {"status": "failed", "budget": len(seeds), "valid_candidates": 0}
    best = min(valid, key=lambda record: (record["shape"]["cd_euclidean_mean"], record["seed"]))
    return {"status": "complete", "budget": len(seeds), "valid_candidates": len(valid),
            "seed": best["seed"], "selector": "shape.cd_euclidean_mean",
            "cd": best["shape"]["cd_euclidean_mean"], "result": best["result_path"]}
