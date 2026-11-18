"""Check actual camera transforms and original-versus-frozen preprocessing."""
import argparse
import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from evaluation.camera_ablation import (
    camera_match, crop_transform, frozen_mesh_image, frozen_wt_image,
)
from wt.data import preprocess_rgba_for_model
from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import REPO_ROOT


def original_preprocessor(path):
    source = path.read_text()
    node = next(node for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.FunctionDef) and node.name == "preprocess_image")
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"np": np, "Image": Image}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["preprocess_image"]


def validate(root):
    upstream = {
        "trellis2": REPO_ROOT / "dependencies/TRELLIS.2/trellis2/pipelines/trellis2_image_to_3d.py",
        "pixal3d": REPO_ROOT / "compare_methods/Pixal3D/pixal3d/pipelines/pixal3d_image_to_3d.py",
    }
    preprocessors = {name: original_preprocessor(path) for name, path in upstream.items()}
    rows = []
    for label in ("GSO", "OOD"):
        for condition in ("A1", "B0", "B1"):
            directory = root / label / condition
            assert read_json(directory / "complete.json")["status"] == "complete"
            for path in sorted((directory / "samples").glob("*/input.json")):
                sample = read_json(path)
                old = Path(sample["camera_ablation"]["source"])
                camera = read_json(path.parent / "camera.json")
                original = read_json(old / "camera.json")
                spatial_record = read_json(path.parent / "spatial.json")
                spatial = spatial_record["spatial"]
                for name, checksum in sample["artifact_sha256"].items():
                    assert file_digest(path.parent / name) == checksum
                for name in ("gt_points.npz", "gt_world.ply"):
                    assert file_digest(path.parent / name) == file_digest(old / name)
                np.testing.assert_array_equal(np.asarray(camera["T_world_to_camera"])[:3, :3],
                                              np.asarray(original["T_world_to_camera"])[:3, :3])
                np.testing.assert_allclose(crop_transform(camera["crop_y_x_side"]) @ np.asarray(camera["K"]),
                                           camera["K_crop"], atol=1e-12, rtol=0)
                row = dict(dataset=label, condition=condition, sample_id=sample["sample_id"],
                           diagnostics=spatial_record["diagnostics"])
                if condition != "B0":
                    assert camera_match(camera["K_crop"])["passed"]
                if condition.startswith("B"):
                    np.testing.assert_array_equal(camera["T_world_to_camera"], original["T_world_to_camera"])
                    assert spatial_record["frozen"]
                    with Image.open(old / "input.png") as image:
                        baseline = np.array(image.convert("RGBA"))
                    for background, erosion in (((128, 128, 128), 0), ((0, 0, 0), 2)):
                        kwargs = dict(image_size=504, num_layers=6, bg_color=background, alpha_erode_px=erosion)
                        a = preprocess_rgba_for_model(baseline, center_crop=True, **kwargs)
                        b = preprocess_rgba_for_model(frozen_wt_image(baseline, spatial), center_crop=False, **kwargs)
                        for x, y in zip(a, b):
                            np.testing.assert_array_equal(x.numpy(), y.numpy())
                    for method, function in preprocessors.items():
                        image = Image.fromarray(baseline)
                        expected = function(SimpleNamespace(), image)
                        actual = frozen_mesh_image(image, spatial, method)
                        np.testing.assert_array_equal(np.asarray(actual), np.asarray(expected))
                    row["all_model_control_preprocessing_equal"] = True
                if condition == "B0":
                    assert file_digest(path.parent / "input.png") == file_digest(old / "input.png")
                    np.testing.assert_allclose(camera["K_crop"], original["K_crop"], atol=1e-12, rtol=0)
                    row["control_intrinsic_max_abs"] = float(np.max(np.abs(np.asarray(camera["K_crop"]) - original["K_crop"])))
                    with np.load(path.parent / "gt_depth.npz", allow_pickle=False) as new, np.load(old / "gt_depth.npz", allow_pickle=False) as prior:
                        np.testing.assert_array_equal(new["mask"], prior["mask"])
                        error = float(np.max(np.abs(new["depth"] - prior["depth"])))
                        assert error < 1e-5, error
                        row["control_gt_depth_max_abs"] = error
                rows.append(row)
    return {"status": "passed", "records": rows, "camera_conditions": len(rows),
            "upstream_preprocessing_sha256": {name: file_digest(path) for name, path in upstream.items()},
            "validator_sha256": file_digest(Path(__file__))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.root)
    atomic_json(args.output, report)
    print({k: report[k] for k in ("status", "camera_conditions")})


if __name__ == "__main__":
    main()
