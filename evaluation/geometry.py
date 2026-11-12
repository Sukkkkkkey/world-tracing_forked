"""Geometry metrics in fixed GT-diagonal units; no camera-pose assumptions."""
import itertools
import numpy as np
from scipy.spatial import cKDTree


def surface_points(mesh, count, seed):
    """Area-weighted triangle sampling with a private RNG (independent of task order)."""
    rng = np.random.Generator(np.random.PCG64(seed))
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    if not np.isfinite(areas).all() or areas.sum() <= 0:
        raise ValueError('Mesh has no finite positive surface area')
    triangles = np.asarray(mesh.triangles)[rng.choice(len(areas), count, p=areas / areas.sum())]
    u, v = rng.random((2, count))
    u = np.sqrt(u)
    return ((1-u)[:, None]*triangles[:, 0] + (u*(1-v))[:, None]*triangles[:, 1]
            + (u*v)[:, None]*triangles[:, 2])


def valid_points(points):
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
        raise ValueError('Expected nonempty finite Nx3 points')
    return points


def chamfer(pred, gt):
    pred, gt = valid_points(pred), valid_points(gt)
    a = cKDTree(gt).query(pred, workers=1)[0]
    b = cKDTree(pred).query(gt, workers=1)[0]
    out = dict(cd_euclidean_mean=float((a.mean()+b.mean())/2),
               cd_squared_mean=float(((a*a).mean()+(b*b).mean())/2))
    for threshold in (.01, .05):
        precision, recall = float((a < threshold).mean()), float((b < threshold).mean())
        out[f'f@{threshold:.2f}'] = 2*precision*recall/(precision+recall) if precision+recall else 0.
    return out


def transform_points(points, matrix):
    return np.asarray(points) @ matrix[:3, :3].T + matrix[:3, 3]


def fit_similarity(source, target):
    """Least-squares positive Sim(3), explicitly excluding reflections."""
    source, target = valid_points(source), valid_points(target)
    x, y = source-source.mean(0), target-target.mean(0)
    variance = np.mean(np.sum(x*x, axis=1))
    if variance < 1e-16:
        raise ValueError('Degenerate similarity fit')
    u, singular, vt = np.linalg.svd(y.T @ x / len(x))
    signs = np.ones(3)
    signs[-1] = 1 if np.linalg.det(u @ vt) > 0 else -1
    rotation = (u * signs) @ vt
    scale = float(singular @ signs / variance)
    if scale <= 0 or not np.isfinite(scale):
        raise ValueError('Nonpositive similarity scale')
    matrix = np.eye(4)
    matrix[:3, :3] = scale*rotation
    matrix[:3, 3] = target.mean(0)-scale*rotation@source.mean(0)
    return matrix


def cube_rotations():
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1, 1), repeat=3):
            matrix = np.eye(3)[list(permutation)] * np.asarray(signs)[:, None]
            if np.linalg.det(matrix) > 0:
                yield matrix


def register_sim3(pred, gt, iterations=100, tolerance=1e-6, *, initial_rotations=None):
    """24 proper starts; symmetric nearest-neighbor ICP, select symmetric squared loss."""
    pred, gt = valid_points(pred), valid_points(gt)
    pred_scale = np.sqrt(np.mean(np.sum((pred-pred.mean(0))**2, axis=1)))
    gt_scale = np.sqrt(np.mean(np.sum((gt-gt.mean(0))**2, axis=1)))
    if min(pred_scale, gt_scale) < 1e-8:
        raise ValueError('Degenerate registration cloud')
    gt_tree = cKDTree(gt)
    best_loss, best_matrix, starts = np.inf, None, []
    rotations = cube_rotations() if initial_rotations is None else initial_rotations
    for index, rotation in enumerate(rotations):
        matrix = np.eye(4)
        matrix[:3, :3] = rotation * (gt_scale/pred_scale)
        matrix[:3, 3] = gt.mean(0)-matrix[:3, :3]@pred.mean(0)
        previous = np.inf
        for iteration in range(iterations+1):
            current = transform_points(pred, matrix)
            a, target_idx = gt_tree.query(current, workers=1)
            b, source_idx = cKDTree(current).query(gt, workers=1)
            loss = float(((a*a).mean()+(b*b).mean())/2)
            if loss < best_loss:
                best_loss, best_matrix = loss, matrix.copy()
            if iteration == iterations or previous**.5-loss**.5 < tolerance:
                break
            previous = loss
            # Both clouds have equal registration counts in the evaluation protocol.
            delta = fit_similarity(np.concatenate([current, current[source_idx]]),
                                   np.concatenate([gt[target_idx], gt]))
            matrix = delta @ matrix
        starts.append(dict(start=index, iterations=iteration, loss=loss))
    return best_matrix, dict(loss=best_loss, starts=starts, tolerance=tolerance, max_iterations=iterations)


def depth_metrics(pred, gt, pred_mask, gt_mask, minimum_coverage=.95):
    pred, gt = np.asarray(pred, float), np.asarray(gt, float)
    p = np.asarray(pred_mask, bool) & np.isfinite(pred) & (pred > 0)
    q = np.asarray(gt_mask, bool) & np.isfinite(gt) & (gt > 0)
    common = p & q
    if not q.any():
        raise ValueError('GT depth has no valid pixels')
    out = dict(depth_coverage=float(common.sum()/q.sum()), silhouette_iou=float(common.sum()/(p|q).sum()),
               valid_pixels=int(common.sum()), status='failed')
    if common.sum() < 3:
        return dict(out, reason='Insufficient valid depth')
    x, y = pred[common], gt[common]
    design = np.stack([x, np.ones_like(x)], axis=1)
    a_b, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    a, b = a_b.tolist()
    out.update(scale=a, shift=b, raw_mae=float(np.abs(x-y).mean()))
    if rank < 2 or a <= 0:
        return dict(out, reason='Rank-deficient or nonpositive scale fit')
    aligned = a*x+b
    if (aligned <= 0).any():
        return dict(out, reason='Nonpositive aligned depth')
    if out['depth_coverage'] < minimum_coverage:
        return dict(out, reason='Depth coverage below protocol threshold')
    error, ratio = np.abs(aligned-y), np.maximum(aligned/y, y/aligned)
    return dict(out, status='complete', mae=float(error.mean()), rmse=float(np.sqrt((error**2).mean())),
                absrel=float((error/y).mean()), delta1=float((ratio < 1.25).mean()), delta2=float((ratio < 1.25**2).mean()))
