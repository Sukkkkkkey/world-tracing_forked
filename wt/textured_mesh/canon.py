"""Camera-frame ↔ TRELLIS.2 canonical-frame transform.

TRELLIS.2 expects 3D content inside the cube ``[-0.5, 0.5]^3`` with **Z-up**
(``utils3d.torch.extrinsics_look_at(origin, (0,0,0), (0,0,1))`` inside
``trellis2/utils/render_utils.py``).  Our multilayer-geometry model emits XYZ
in OpenCV camera space: ``+x`` right, ``+y`` down, ``+z`` forward.

This module provides the bidirectional mapping (forward for voxelisation,
inverse for cam-frame mesh export).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# O-Voxel to_glb maps (x, y, z) canonical to (x, z, -y) in glTF.
# Matrices act on column vectors; row-vector arrays use matrix.T.
GLB_TO_CANONICAL = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64)
GLB_TO_CANONICAL.setflags(write=False)


@dataclass
class CanonicalTransform:
    """Camera XYZ → TRELLIS canonical XYZ.

    The forward map is::

        (x, y, z)_cam  →  (x, z, -y)_canonical_zup
        v_canon = (R @ v_cam - centroid) * scale

    so that the cloud lands inside ``[-half_target, half_target]^3`` ⊂
    ``[-0.5, 0.5]^3`` with its "front" (smallest ``z_cam``) facing the
    negative canonical Y direction.

    Attributes:
        centroid: ``(3,)`` translation in canonical space (applied AFTER
            the axis remap).
        scale: isotropic scale factor.
        axis_map: ``"cam2canonical_zup"`` (default), ``"identity"`` (skip
            the remap entirely), or ``"y_flip"`` (negate y only -- legacy).
    """

    centroid: np.ndarray  # (3,) -- applied AFTER axis remap
    scale: float
    axis_map: str = "cam2canonical_zup"

    def __post_init__(self):
        self.centroid = np.asarray(self.centroid, dtype=np.float64)
        self.scale = float(self.scale)
        if self.centroid.shape != (3,) or not np.isfinite(self.centroid).all():
            raise ValueError("centroid must be a finite 3-vector")
        if not np.isfinite(self.scale) or self.scale <= 0:
            raise ValueError("scale must be finite and positive")
        if self.axis_map not in ("cam2canonical_zup", "identity", "y_flip", None):
            raise ValueError(f"Unknown axis_map: {self.axis_map}")

    def _apply_axis_map(self, xyz: np.ndarray) -> np.ndarray:
        if self.axis_map == "cam2canonical_zup":
            return np.stack([xyz[..., 0], xyz[..., 2], -xyz[..., 1]], axis=-1)
        if self.axis_map in ("identity", None):
            return xyz.copy()
        if self.axis_map == "y_flip":
            out = xyz.copy()
            out[..., 1] = -out[..., 1]
            return out
        raise ValueError(f"Unknown axis_map: {self.axis_map}")

    def apply(self, xyz: np.ndarray) -> np.ndarray:
        """Camera XYZ → canonical XYZ."""
        out = self._apply_axis_map(np.asarray(xyz))
        out = out - self.centroid
        out = out * self.scale
        return out

    def to_dict(self) -> dict:
        return {
            "centroid": self.centroid.tolist(),
            "scale": float(self.scale),
            "axis_map": self.axis_map,
        }


def compute_canonical_transform(
    cloud_cam: np.ndarray,
    half_target: float = 0.45,
    axis_map: str = "cam2canonical_zup",
) -> CanonicalTransform:
    """Fit a ``CanonicalTransform`` that centres + isotropic-scales the
    cloud so it fits in ``[-half_target, half_target]^3``.

    Args:
        cloud_cam: ``(N, 3) float`` cloud in camera space.
        half_target: target half-extent in canonical space (default 0.45,
            keeping a small margin inside the [-0.5, 0.5] cube).
        axis_map: orientation convention (see :class:`CanonicalTransform`).
    """
    cloud_cam = np.asarray(cloud_cam, dtype=np.float64)
    if cloud_cam.ndim != 2 or cloud_cam.shape[1] != 3 or cloud_cam.size == 0:
        raise ValueError("compute_canonical_transform: expected nonempty (N, 3) cloud")
    if not np.isfinite(cloud_cam).all():
        raise ValueError("compute_canonical_transform: nonfinite cloud")
    if not 0 < half_target < 0.5:
        raise ValueError("half_target must be in (0, 0.5)")
    tf = CanonicalTransform(
        centroid=np.zeros(3, dtype=np.float32),
        scale=1.0,
        axis_map=axis_map,
    )
    pts = tf._apply_axis_map(cloud_cam.copy())
    centroid = pts.mean(axis=0)
    centered = pts - centroid[None, :]
    half_extent = float(np.abs(centered).max())
    scale = half_target / max(half_extent, 1e-6)
    return CanonicalTransform(
        centroid=centroid,
        scale=scale,
        axis_map=axis_map,
    )


def canon_inverse(
    v_canon: np.ndarray, tf: CanonicalTransform
) -> np.ndarray:
    """Canonical XYZ → camera XYZ (inverse of :meth:`CanonicalTransform.apply`).

    Useful for rendering the textured mesh in the same world as the input
    camera (e.g. side-by-side comparison with the raw point cloud).
    """
    v = np.asarray(v_canon, dtype=np.float64)
    v = v / float(tf.scale) + tf.centroid
    if tf.axis_map == "cam2canonical_zup":
        v_cam = np.stack([v[..., 0], -v[..., 2], v[..., 1]], axis=-1)
    elif tf.axis_map in ("identity", None):
        v_cam = v
    elif tf.axis_map == "y_flip":
        v_cam = v.copy()
        v_cam[..., 1] = -v_cam[..., 1]
    else:
        raise ValueError(f"Unknown axis_map: {tf.axis_map}")
    return v_cam.astype(np.float32)


def aggregate_camera_cloud(
    xyz_cam: np.ndarray,
    mask: np.ndarray,
    max_points: int | None = None,
    seed: int = 0,
) -> np.ndarray:
    """Flatten ``[L, H, W, 3]`` + ``[L, H, W]`` mask → ``(N, 3)`` cloud.

    Drops non-finite points. By default keeps ALL points so fitting a
    canonical transform cannot miss extrema. Explicit ``max_points``
    enables deterministic subsampling for visualization, not scale fitting.
    """
    xyz_cam = np.asarray(xyz_cam)
    mask = np.asarray(mask, dtype=bool)
    if xyz_cam.ndim != 4 or xyz_cam.shape[-1] != 3 or mask.shape != xyz_cam.shape[:-1]:
        raise ValueError("Expected xyz (L, H, W, 3) and matching mask (L, H, W)")
    if max_points is not None and max_points <= 0:
        raise ValueError("max_points must be positive or None")
    pts = xyz_cam[mask]
    pts = pts[np.isfinite(pts).all(axis=1)]
    if len(pts) == 0:
        return pts
    if max_points is not None and pts.shape[0] > max_points:
        sel = np.random.RandomState(seed).choice(
            pts.shape[0], max_points, replace=False
        )
        pts = pts[sel]
    return pts.astype(np.float32)


def glb_to_camera(vertices: np.ndarray, tf: CanonicalTransform) -> np.ndarray:
    """Undo O-Voxel's glTF axis rotation, then restore WT coordinates/scale.

    ``vertices`` must already include any GLB scene-node transforms. This
    restores the WT frame, not ground-truth geometry or unknown scene units.
    """
    canonical = np.asarray(vertices) @ GLB_TO_CANONICAL.T
    return canon_inverse(canonical, tf)


__all__ = [
    "GLB_TO_CANONICAL",
    "CanonicalTransform",
    "aggregate_camera_cloud",
    "canon_inverse",
    "compute_canonical_transform",
    "glb_to_camera",
]
