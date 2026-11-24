"""Single-process, ragged-batch TRELLIS.2 sampling for the fixed 1024 Hybrid pilot."""
from contextlib import contextmanager

import numpy as np
import torch


@contextmanager
def resident(pipeline, module):
    if pipeline.low_vram:
        module.to(pipeline.device)
    try:
        yield module
    finally:
        if pipeline.low_vram:
            module.cpu()


def pack_supports(supports, device):
    packed = []
    for i, support in enumerate(supports):
        xyz = np.asarray(support)
        if (xyz.ndim != 2 or xyz.shape[1] != 3 or not len(xyz)
                or not np.issubdtype(xyz.dtype, np.integer) or xyz.min() < 0 or xyz.max() >= 32
                or len(np.unique(xyz, axis=0)) != len(xyz)):
            raise ValueError(f"Invalid 32-grid support for batch member {i}")
        column = np.full((len(xyz), 1), i, dtype=np.int32)
        packed.append(np.concatenate((column, xyz.astype(np.int32)), axis=1))
    # argwhere-derived supports may be column-major. The sparse convolution kernel
    # requires contiguous rows of [batch, x, y, z] on its first decoder call.
    return torch.from_numpy(np.ascontiguousarray(np.concatenate(packed))).to(device)


def noise_rows(lengths, channels, generators, device):
    # Upstream draws on CPU before copying to the device. Advance each asset's
    # generator across LR shape, HR shape and texture in that same order.
    return torch.cat([torch.randn(n, channels, generator=g, device="cpu")
                      for n, g in zip(lengths, generators, strict=True)]).to(device)


def stats(normalization, device):
    return tuple(torch.tensor(normalization[k], device=device)[None] for k in ("std", "mean"))


def flow(pipeline, name, coords, lengths, generators, cond, cfg, shape=None):
    from trellis2.modules.sparse import SparseTensor
    kind = "tex" if shape is not None else "shape"
    model = pipeline.models[name]
    channels = model.in_channels
    extra = {}
    if shape is not None:
        std, mean = stats(pipeline.shape_slat_normalization, shape.device)
        normalized = (shape - mean) / std
        channels -= normalized.feats.shape[1]
        extra["concat_cond"] = normalized
    rows = noise_rows(lengths, channels, generators, pipeline.device)
    noise = (SparseTensor(feats=rows, coords=coords) if shape is None else normalized.replace(rows))
    sampler = getattr(pipeline, f"{kind}_slat_sampler")
    params = {**getattr(pipeline, f"{kind}_slat_sampler_params"), "steps": cfg[f"{kind}_steps"]}
    with resident(pipeline, model):
        result = sampler.sample(model, noise, **cond, **extra, **params, verbose=True,
                                tqdm_desc=f"Sampling {kind} SLat").samples
    std, mean = stats(getattr(pipeline, f"{kind}_slat_normalization"), result.device)
    return result * std + mean


@torch.no_grad()
def sample_latents(pipeline, images, supports, seeds, cfg):
    """One conditioned forward per flow step for every member of this batch."""
    from scripts.recovery_memory import bounded_layernorm, inference_parameters
    if not images or len(images) != len(supports) or len(images) != len(seeds):
        raise ValueError("Each batch member needs an image, support and seed")
    if cfg["pipeline_type"] != "1024_cascade" or cfg["max_num_tokens"] <= 0:
        raise ValueError("Batched Hybrid requires the 1024 cascade configuration")
    coords = pack_supports(supports, pipeline.device)
    generators = [torch.Generator(device="cpu").manual_seed(int(seed)) for seed in seeds]
    lr_cond = pipeline.get_cond(images, 512)
    hr_cond = pipeline.get_cond(images, 1024)
    for cond in (lr_cond, hr_cond):
        if any(v.shape[0] != len(images) for v in cond.values()):
            raise ValueError("Image conditioner lost batch membership")
    low = flow(pipeline, "shape_slat_flow_model_512", coords, list(map(len, supports)),
               generators, lr_cond, cfg)
    decoder = pipeline.models["shape_slat_decoder"]
    with resident(pipeline, decoder), bounded_layernorm(decoder), inference_parameters(decoder):
        if pipeline.low_vram:
            decoder.low_vram = True
        try:
            up = decoder.upsample(low, upsample_times=4)
        finally:
            if pipeline.low_vram:
                decoder.low_vram = False
    del low, lr_cond
    # The upstream cascade stops at 1024 regardless of token count. Include
    # the batch column in unique() so coincident cells in two objects survive.
    coords = torch.cat((up[:, :1], ((up[:, 1:] + 0.5) / 512 * (1024 // 16)).int()), 1).unique(dim=0).contiguous()
    del up
    lengths = torch.bincount(coords[:, 0].long(), minlength=len(images)).tolist()
    if len(lengths) != len(images) or not all(lengths):
        raise ValueError("Upsampling lost or added a batch member")
    shape = flow(pipeline, "shape_slat_flow_model_1024", coords, lengths, generators, hr_cond, cfg)
    texture = flow(pipeline, "tex_slat_flow_model_1024", coords, lengths, generators, hr_cond, cfg, shape)
    return shape, texture, lengths, [g.get_state() for g in generators]
