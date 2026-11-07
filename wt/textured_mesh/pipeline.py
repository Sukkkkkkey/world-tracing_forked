"""TRELLIS.2 hybrid driver — inject our voxel coords into stages 2+3.

This module is the only place that imports ``trellis2`` / ``o_voxel``.  The
import is deferred until you actually call :func:`load_trellis2_pipeline`
so that ``wt`` itself stays usable without the heavy TRELLIS.2 stack.

Use the project environment and ``scripts/setup_all.sh`` (see README).
The default checkout is ``dependencies/TRELLIS.2``; prepared local model
descriptors are preferred over Hub downloads. Stage 1 is skipped by default;
batch workers can explicitly include it to share native/hybrid model instances.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from wt.paths import TRELLIS2_ROOT, WEIGHTS_ROOT


def sparse_structure_resolution(pipeline_type: str) -> int:
    """Grid consumed by the first shape flow (cascade starts at 512)."""
    resolutions = {"512": 32, "1024": 64, "1024_cascade": 32, "1536_cascade": 32}
    if pipeline_type not in resolutions:
        raise ValueError(f"Unknown pipeline_type {pipeline_type!r}; expected {tuple(resolutions)}")
    return resolutions[pipeline_type]


def _ensure_trellis2_importable(trellis2_path: str | os.PathLike | None) -> None:
    """Prepend the local TRELLIS.2 checkout to ``sys.path`` if needed.

    Does nothing if ``trellis2`` is already importable (e.g. installed
    into the active conda env via ``setup.sh``).
    """
    if trellis2_path is not None:
        p = Path(trellis2_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(
                f"--trellis2-path does not exist: {p}.  Did you clone "
                f"https://github.com/microsoft/TRELLIS.2 ?"
            )
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def load_trellis2_pipeline(
    model_id: str | os.PathLike | None = None,
    device: str | torch.device = "cuda",
    trellis2_path: str | os.PathLike | None = None,
    attn_backend: str | None = None,
    pipeline_type: str | None = None,
    include_stage1: bool = False,
):
    """Load selected shape/texture models and optional Stage 1 from local descriptors.

    Args:
        model_id: HF repo id or local descriptor directory. None prefers
            ``WT_WEIGHTS_ROOT/local-pipelines/TRELLIS.2`` when present,
            otherwise uses ``microsoft/TRELLIS.2-4B``.
        device: torch device.
        trellis2_path: optional path to a local TRELLIS.2 checkout.  Use
            this if ``trellis2`` is not already on ``sys.path``.
        attn_backend: optional override for ``SPARSE_ATTN_BACKEND``
            (``"flash_attn"`` or ``"xformers"``).  ``None`` keeps the
            TRELLIS.2 default (``flash_attn``).
        pipeline_type: optional variant to limit which flow models load.
        include_stage1: also load Stage 1 for a shared native/hybrid batch worker.

    Returns:
        The loaded ``Trellis2ImageTo3DPipeline`` instance, already moved
        to ``device``.
    """
    if pipeline_type is not None:
        sparse_structure_resolution(pipeline_type)
    if trellis2_path is None and TRELLIS2_ROOT.is_dir():
        trellis2_path = TRELLIS2_ROOT
    _ensure_trellis2_importable(trellis2_path)
    if model_id is None:
        local = WEIGHTS_ROOT / "local-pipelines/TRELLIS.2"
        model_id = local if (local / "pipeline.json").is_file() else "microsoft/TRELLIS.2-4B"
    if attn_backend is not None:
        os.environ["SPARSE_ATTN_BACKEND"] = attn_backend

    try:
        from trellis2.pipelines import Trellis2ImageTo3DPipeline  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Could not import `trellis2`.  Install the public TRELLIS.2 "
            "repo (https://github.com/microsoft/TRELLIS.2) via its "
            "`setup.sh`, then either activate that conda env or pass "
            "`--trellis2-path /path/to/TRELLIS.2`."
        ) from exc

    # Do not mutate the upstream class: regular TRELLIS pipelines may coexist
    # with WT. Batch workers opt into Stage 1; hybrid-only calls skip it.
    names = ["shape_slat_decoder", "tex_slat_decoder"]
    if include_stage1:
        names.extend(["sparse_structure_flow_model", "sparse_structure_decoder"])
    if pipeline_type is None or pipeline_type == "512" or "cascade" in pipeline_type:
        names.append("shape_slat_flow_model_512")
    if pipeline_type is None or pipeline_type != "512":
        names.extend(["shape_slat_flow_model_1024", "tex_slat_flow_model_1024"])
    if pipeline_type is None or pipeline_type == "512":
        names.append("tex_slat_flow_model_512")

    class HybridPipeline(Trellis2ImageTo3DPipeline):
        model_names_to_load = names

    pipeline = HybridPipeline.from_pretrained(str(model_id))
    pipeline.to(device)
    return pipeline


@torch.no_grad()
def inject_coords_into_trellis2(
    pipeline,
    pil_rgba: Image.Image,
    coords_xyz: np.ndarray,
    seed: int = 42,
    pipeline_type: str = "1024",
    preprocess_image: bool = True,
    *,
    ss_res: int | None = None,
    shape_slat_sampler_params: dict | None = None,
    tex_slat_sampler_params: dict | None = None,
    max_num_tokens: int = 49152,
):
    """Run TRELLIS.2 stages 2+3 with our voxel coords as the Stage-1 output.

    Args:
        pipeline: ``Trellis2ImageTo3DPipeline`` from
            :func:`load_trellis2_pipeline`.
        pil_rgba: input image (RGBA PIL Image).  If
            ``preprocess_image=True`` (default), TRELLIS.2's own
            ``preprocess_image`` (including rembg + crop + recentre) is
            applied; otherwise cropping/rembg is skipped, but RGBA is
            still composited onto black before feature extraction.
        coords_xyz: ``(M, 3) int32`` voxel coords in ``[0, ss_res-1]``
            from :func:`wt.textured_mesh.v4_ray_fill`.  A leading batch
            index column is added internally.
        seed: random seed for the diffusion samplers.
        pipeline_type: one of ``"512"``, ``"1024"``, ``"1024_cascade"``,
            ``"1536_cascade"`` (see TRELLIS.2 README).  Higher resolution
            = better detail, more VRAM / time.
        ss_res: coordinate grid resolution, validated against the variant.
            512 and both cascades require 32; direct 1024 requires 64.
        shape_slat_sampler_params: overrides for the upstream shape sampler.
        tex_slat_sampler_params: overrides for the upstream texture sampler.
        max_num_tokens: upstream cascade token budget (not a hard cap at 1024).

    Returns:
        ``list[MeshWithVoxel]`` -- typically length 1.  Each entry has
        ``.vertices, .faces, .attrs, .coords, .layout, .voxel_size``,
        ready for :func:`save_mesh_glb`.
    """
    expected_res = sparse_structure_resolution(pipeline_type)
    if ss_res is not None and ss_res != expected_res:
        raise ValueError(f"{pipeline_type} requires ss_res={expected_res}, got {ss_res}")
    coords_xyz = np.asarray(coords_xyz)
    if coords_xyz.ndim != 2 or coords_xyz.shape[1] not in (3, 4) or len(coords_xyz) == 0:
        raise ValueError("coords_xyz must be a nonempty (M, 3) or (M, 4) array")
    if not np.issubdtype(coords_xyz.dtype, np.integer):
        raise ValueError("coords_xyz must contain integer voxel indices")
    if coords_xyz.shape[1] == 4 and np.any(coords_xyz[:, 0] != 0):
        raise ValueError("Single-image injection requires batch indices equal to zero")
    spatial = coords_xyz[:, -3:]
    if np.any(spatial < 0) or np.any(spatial >= expected_res):
        raise ValueError(f"Voxel coordinates must be in [0, {expected_res - 1}] for {pipeline_type}")
    if len(np.unique(spatial, axis=0)) != len(spatial):
        raise ValueError("Voxel coordinates must be unique")
    if max_num_tokens <= 0:
        raise ValueError("max_num_tokens must be positive")
    shape_params = dict(shape_slat_sampler_params or {})
    tex_params = dict(tex_slat_sampler_params or {})
    for params in (shape_params, tex_params):
        if "steps" in params and params["steps"] <= 0:
            raise ValueError("Sampler steps must be positive")
    device = pipeline.device
    if pil_rgba.mode == "RGBA" and not np.any(np.asarray(pil_rgba)[..., 3] > 204):
        raise ValueError("Input alpha contains no foreground above the TRELLIS threshold")
    if preprocess_image:
        pil_rgba = pipeline.preprocess_image(pil_rgba)
    elif pil_rgba.mode == "RGBA":
        # Skipping crop/rembg must not expose hidden RGB to the image encoder.
        background = Image.new("RGB", pil_rgba.size, (0, 0, 0))
        background.paste(pil_rgba, mask=pil_rgba.getchannel("A"))
        pil_rgba = background
    else:
        pil_rgba = pil_rgba.convert("RGB")
    if coords_xyz.shape[1] == 4:
        coords4 = coords_xyz.astype(np.int64)
    else:
        batch = np.zeros((coords_xyz.shape[0], 1), dtype=np.int64)
        coords4 = np.concatenate([batch, coords_xyz.astype(np.int64)], axis=1)
    coords = torch.from_numpy(coords4).to(device=device, dtype=torch.int32).contiguous()

    torch.manual_seed(int(seed))
    if torch.cuda.is_available():
        torch.cuda.manual_seed(int(seed))
    cond_512 = pipeline.get_cond([pil_rgba], 512)
    cond_1024 = (
        pipeline.get_cond([pil_rgba], 1024) if pipeline_type != "512" else None
    )

    if pipeline_type == "512":
        shape_slat = pipeline.sample_shape_slat(
            cond_512, pipeline.models["shape_slat_flow_model_512"], coords, shape_params
        )
        tex_slat = pipeline.sample_tex_slat(
            cond_512, pipeline.models["tex_slat_flow_model_512"], shape_slat, tex_params
        )
        res = 512
    elif pipeline_type == "1024":
        shape_slat = pipeline.sample_shape_slat(
            cond_1024, pipeline.models["shape_slat_flow_model_1024"], coords, shape_params
        )
        tex_slat = pipeline.sample_tex_slat(
            cond_1024, pipeline.models["tex_slat_flow_model_1024"], shape_slat, tex_params
        )
        res = 1024
    elif pipeline_type == "1024_cascade":
        shape_slat, res = pipeline.sample_shape_slat_cascade(
            cond_512,
            cond_1024,
            pipeline.models["shape_slat_flow_model_512"],
            pipeline.models["shape_slat_flow_model_1024"],
            512,
            1024,
            coords,
            shape_params,
            max_num_tokens,
        )
        tex_slat = pipeline.sample_tex_slat(
            cond_1024, pipeline.models["tex_slat_flow_model_1024"], shape_slat, tex_params
        )
    elif pipeline_type == "1536_cascade":
        shape_slat, res = pipeline.sample_shape_slat_cascade(
            cond_512,
            cond_1024,
            pipeline.models["shape_slat_flow_model_512"],
            pipeline.models["shape_slat_flow_model_1024"],
            512,
            1536,
            coords,
            shape_params,
            max_num_tokens,
        )
        tex_slat = pipeline.sample_tex_slat(
            cond_1024, pipeline.models["tex_slat_flow_model_1024"], shape_slat, tex_params
        )
    else:
        raise ValueError(
            f"Unknown pipeline_type {pipeline_type!r}; expected one of "
            "'512', '1024', '1024_cascade', '1536_cascade'."
        )

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return pipeline.decode_latent(shape_slat, tex_slat, res)


def save_mesh_glb(
    path: str | os.PathLike,
    mesh,
    texture_size: int = 4096,
    decimation_target: int = 1_000_000,
    aabb: tuple[tuple[float, float, float], tuple[float, float, float]] = (
        (-0.5, -0.5, -0.5),
        (0.5, 0.5, 0.5),
    ),
) -> Path:
    """Bake canonical Z-up geometry to glTF Y-up via ``o_voxel.postprocess.to_glb``.

    Args:
        path: output path (``.glb``).
        mesh: a ``MeshWithVoxel`` from
            :func:`inject_coords_into_trellis2` (must expose ``.vertices,
            .faces, .attrs, .coords, .layout, .voxel_size``).
        texture_size: baked texture resolution (square).  4096 is the
            public-example default.
        decimation_target: target face count for the post-bake
            decimation pass.  1M ≈ web-friendly; raise to keep more detail.
        aabb: bounding box used for GLB scaling; default is the TRELLIS
            canonical cube.

    Returns:
        ``Path`` of the written GLB.
    """
    if mesh.vertices.numel() == 0 or mesh.faces.numel() == 0:
        raise ValueError("Cannot export an empty decoded mesh")
    if not torch.isfinite(mesh.vertices).all() or not torch.isfinite(mesh.attrs).all():
        raise ValueError("Cannot export nonfinite mesh geometry or texture attributes")
    try:
        import o_voxel  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "save_mesh_glb requires `o_voxel`.  It ships with the TRELLIS.2 "
            "setup (`bash setup.sh --o-voxel`).  Make sure your TRELLIS.2 "
            "conda env is active."
        ) from exc

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[list(aabb[0]), list(aabb[1])],
        decimation_target=int(decimation_target),
        texture_size=int(texture_size),
        remesh=True,
        remesh_band=1,
        remesh_project=0,
        verbose=False,
    )
    glb.export(str(out), extension_webp=True)
    return out


__all__ = [
    "inject_coords_into_trellis2",
    "load_trellis2_pipeline",
    "save_mesh_glb",
    "sparse_structure_resolution",
]
