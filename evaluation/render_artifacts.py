"""Deterministic PNG views exported from the numerical evaluation arrays."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io

import cv2
import numpy as np
from PIL import Image, ImageDraw

from wt.artifacts import atomic_artifact
from wt.experiment import atomic_json, digest, file_digest, read_json


def load_render_groups(path):
    with np.load(path, allow_pickle=False) as saved:
        return {group: {name: saved[f"{group}_{name}"] for name in
                       ("depth", "mask", "normals", "normal_valid")}
                for group in ("input", "multiview")}


def depth_limits(reference):
    valid = reference["mask"] & np.isfinite(reference["depth"]) & (reference["depth"] > 0)
    values = reference["depth"][valid]
    if not len(values):
        raise ValueError("GT view has no finite depth")
    low, high = float(values.min()), float(values.max())
    padding = max((high - low) * .1, .01)
    return [max(0., low - padding), high + padding]


def colour_scalar(values, valid, limits):
    fraction = np.clip((values - limits[0]) / (limits[1] - limits[0]), 0, 1)
    encoded = np.rint(np.nan_to_num(fraction) * 255).astype(np.uint8)
    colour = cv2.applyColorMap(encoded, cv2.COLORMAP_TURBO)[..., ::-1].copy()
    colour[~valid] = 127
    return colour


def frame_images(prediction, reference, config, *, reference_only=False):
    p = prediction["mask"] & np.isfinite(prediction["depth"]) & (prediction["depth"] > 0)
    g = reference["mask"] & np.isfinite(reference["depth"]) & (reference["depth"] > 0)
    pn = p & prediction["normal_valid"]
    gn = g & reference["normal_valid"]
    overlap, normal_overlap = p & g, pn & gn
    limits = depth_limits(reference)
    normal = np.rint(np.clip((prediction["normals"] + 1) * 127.5, 0, 255)).astype(np.uint8)
    normal[~pn] = 127
    images = {
        "normal.png": normal,
        "depth.png": colour_scalar(prediction["depth"], p, limits),
        "mask.png": prediction["mask"].astype(np.uint8) * 255,
        "depth_valid.png": p.astype(np.uint8) * 255,
        "normal_valid.png": pn.astype(np.uint8) * 255,
    }
    if reference_only:
        return images, limits
    depth_error = np.abs(prediction["depth"].astype(np.float64) - reference["depth"])
    angles = np.zeros(p.shape, dtype=np.float64)
    if normal_overlap.any():
        a = prediction["normals"][normal_overlap].astype(np.float64)
        b = reference["normals"][normal_overlap].astype(np.float64)
        a /= np.linalg.norm(a, axis=1, keepdims=True)
        b /= np.linalg.norm(b, axis=1, keepdims=True)
        angles[normal_overlap] = np.degrees(np.arctan2(
            np.linalg.norm(np.cross(a, b), axis=1), np.sum(a * b, axis=1)))
    silhouettes = np.full((*p.shape, 3), 127, dtype=np.uint8)
    silhouettes[g & ~p] = [64, 128, 255]
    silhouettes[p & ~g] = [255, 96, 64]
    silhouettes[overlap] = [230, 230, 230]
    images.update({
        "depth_overlap.png": overlap.astype(np.uint8) * 255,
        "normal_overlap.png": normal_overlap.astype(np.uint8) * 255,
        "depth_error.png": colour_scalar(depth_error, overlap, [0, config["depth_error_max"]]),
        "normal_error.png": colour_scalar(angles, normal_overlap, [0, 180]),
        "silhouette_error.png": silhouettes,
    })
    gt_normal = np.rint(np.clip((reference["normals"] + 1) * 127.5, 0, 255)).astype(np.uint8)
    gt_normal[~gn] = 127
    gt_depth = colour_scalar(reference["depth"], g, limits)
    panels = [
        ("GT normal", gt_normal), ("Prediction normal", normal),
        ("Normal error 0..180 deg", images["normal_error.png"]),
        ("Mask: blue GT-only, red pred-only", silhouettes),
        (f"GT depth {limits[0]:.4f}..{limits[1]:.4f} D", gt_depth),
        ("Prediction depth / same scale", images["depth.png"]),
        (f"Depth error 0..{config['depth_error_max']} D", images["depth_error.png"]),
        ("Valid normal comparison", images["normal_overlap.png"]),
    ]
    height, width = p.shape
    canvas = Image.new("RGB", (4 * width, 2 * (height + 24)), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)
    for index, (label, array) in enumerate(panels):
        x, y = (index % 4) * width, (index // 4) * (height + 24)
        canvas.paste(Image.fromarray(array).convert("RGB"), (x, y + 24))
        draw.text((x + 4, y + 5), label, fill="white")
    images["comparison.png"] = np.asarray(canvas)
    return images, limits


def export_render_images(directory, representations, reference, cameras, metadata, config,
                         *, reference_only=False):
    config = {"save_multiview": False, **config}
    signature = digest({"metadata": metadata, "config": config, "cameras": cameras,
                        "reference_only": reference_only})
    manifest_path = directory / "render_manifest.json"
    previous = {}
    if manifest_path.exists():
        try:
            previous = read_json(manifest_path)
        except (OSError, ValueError):
            pass
    verified = {}
    if previous.get("signature") == signature:
        for name, checksum in previous.get("files", {}).items():
            path = directory / name
            if path.is_file() and file_digest(path) == checksum:
                verified[name] = checksum
        if verified == previous.get("files") and previous.get("frames"):
            return {"manifest": str(manifest_path), "sha256": file_digest(manifest_path),
                    "file_count": len(verified), "frame_count": len(previous["frames"])}
    files, frames = {}, []
    previous_frames = {frame["directory"]: frame for frame in previous.get("frames", [])}
    def write_image(item):
        name, array = item
        if name in verified:
            return name, verified[name]
        buffer = io.BytesIO()
        Image.fromarray(array).save(buffer, format="PNG", compress_level=3)
        payload = buffer.getvalue()
        with atomic_artifact(directory / name) as temporary:
            temporary.write_bytes(payload)
        return name, hashlib.sha256(payload).hexdigest()
    with ThreadPoolExecutor(max_workers=4) as executor:
        for representation, groups in representations.items():
            view_groups = ("input", "multiview") if config.get("save_multiview", False) else ("input",)
            for group in view_groups:
                for index in range(len(groups[group]["depth"])):
                    prefix = f"renders/{representation}/{group}/{index:03d}"
                    old_frame = previous_frames.get(prefix)
                    if old_frame and all(name in verified for name in old_frame["files"]):
                        files.update({name: verified[name] for name in old_frame["files"]})
                        frames.append(old_frame)
                        continue
                    prediction = {name: values[index] for name, values in groups[group].items()}
                    truth = {name: values[index] for name, values in reference[group].items()}
                    images, limits = frame_images(prediction, truth, config,
                                                  reference_only=reference_only)
                    items = [(f"{prefix}/{name}", array) for name, array in images.items()]
                    files.update(executor.map(write_image, items))
                    frames.append({"directory": prefix, "representation": representation,
                                   "group": group, "view": index,
                                   "camera_index": 0 if group == "input" else index + 1,
                                   "depth_limits": limits, "files": [name for name, _ in items]})
    manifest = {"signature": signature, "metadata": metadata, "config": config,
                "cameras": cameras, "frames": frames, "files": files,
                "colour": {"palette": "turbo", "background": [127, 127, 127],
                           "normal": "(camera normal + 1) / 2",
                           "normal_error_degrees": [0, 180],
                           "depth_error_D": [0, config["depth_error_max"]]}}
    atomic_json(manifest_path, manifest)
    return {"manifest": str(manifest_path), "sha256": file_digest(manifest_path),
            "file_count": len(files), "frame_count": len(frames)}
