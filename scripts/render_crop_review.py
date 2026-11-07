"""Create CPU-only input/depth inspection sheets for the restored crop ablation."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import OUTPUT_ROOT

ROOT = OUTPUT_ROOT / "validation/z-root-cause-20261020"
SIZE = 256
# Fixed blue-to-yellow depth palette, shared by prediction and GT in each sheet.
ANCHORS = np.asarray([[40, 35, 110], [35, 120, 145], [75, 185, 105], [250, 230, 65]], dtype=float)


def depth_image(depth, mask, limits):
    unit = np.clip((depth - limits[0]) / (limits[1] - limits[0]), 0, 1)
    rgb = np.stack([np.interp(unit, np.linspace(0, 1, len(ANCHORS)), ANCHORS[:, c])
                    for c in range(3)], axis=-1)
    rgb[~mask] = 240
    return Image.fromarray(rgb.astype(np.uint8)).resize((SIZE, SIZE), Image.Resampling.NEAREST)


def main():
    validation = read_json(ROOT / "recovery-validation.json")
    assert validation["status"] == "passed"
    records = read_json(ROOT / "inference_records.json")
    assert len(records) == 15
    folder = ROOT / "review"
    folder.mkdir(parents=True, exist_ok=True)
    sources, images = {}, {}
    for sample in validation["recipe"]["samples"]:
        rows = [r for r in records if r["sample_id"] == sample]
        assert [r["variant"] for r in rows] == validation["recipe"]["variants"]
        loaded, values = [], []
        for row in rows:
            run = ROOT / "inference" / sample / row["variant"]
            for name, expected in row["artifact_sha256"].items():
                path = run / name
                assert file_digest(path) == expected
                sources[str(path)] = expected
            sources[str(run / "metrics.json")] = file_digest(run / "metrics.json")
            with np.load(run / "prediction.npz", allow_pickle=False) as data:
                pred, mask = data["xyz"][0, ..., 2].copy(), data["mask"][0].copy()
            with np.load(run / "gt_depth.npz", allow_pickle=False) as data:
                gt, gm = data["depth"].copy(), data["mask"].copy()
            assert np.isfinite(pred[mask]).all() and np.isfinite(gt[gm]).all()
            values.extend([pred[mask], gt[gm]])
            loaded.append((run, row, pred, mask, gt, gm))
        limits = (float(min(v.min() for v in values)), float(max(v.max() for v in values)))
        sheet = Image.new("RGB", (5 * SIZE, 3 * (SIZE + 26) + 114), "white")
        draw = ImageDraw.Draw(sheet)
        draw.text((8, 6), sample, fill="black")
        draw.text((8, 24), "Input / WT first-layer Z / visible GT Z; native camera values, no alignment or depth rescaling.", fill="black")
        draw.text((8, 42), "Common depth color scale within this sheet; background = gray. Labels report common-mask means.", fill="black")
        for col, (run, row, pred, mask, gt, gm) in enumerate(loaded):
            x = col * SIZE
            with Image.open(run / "input.png") as image:
                sheet.paste(image.convert("RGB").resize((SIZE, SIZE)), (x, 82))
            draw.text((x + 5, 65), row["variant"], fill="black")
            y = 82 + SIZE + 26
            draw.text((x + 5, y - 20), "WT Z mean: %.4f" % row["pred_mean_z"], fill="black")
            sheet.paste(depth_image(pred, mask, limits), (x, y))
            y += SIZE + 26
            draw.text((x + 5, y - 20), "GT Z mean: %.4f" % row["gt_mean_z"], fill="black")
            sheet.paste(depth_image(gt, gm, limits), (x, y))
        bar_y = sheet.height - 25
        gradient = np.tile(np.linspace(*limits, 1024)[None, :], (12, 1))
        bar = depth_image(gradient, np.ones_like(gradient, dtype=bool), limits).resize((1024, 12))
        sheet.paste(bar, (110, bar_y))
        draw.text((5, bar_y), "Z %.3f" % limits[0], fill="black")
        draw.text((1145, bar_y), "%.3f" % limits[1], fill="black")
        path = folder / (sample + ".png")
        sheet.save(path)
        images[path.name] = file_digest(path)
    for name in ("inference_records.json", "recovery-validation.json"):
        sources[str(ROOT / name)] = file_digest(ROOT / name)
    assert all(file_digest(Path(path)) == sha for path, sha in sources.items())
    atomic_json(folder / "manifest.json", dict(status="rendered-awaiting-visual-review",
        runs=15, images=images, source_sha256=sources, script_sha256=file_digest(Path(__file__)),
        scope="Input and unaligned visible-depth diagnostics only; no full multilayer GT"))
    print(folder, flush=True)


if __name__ == "__main__":
    main()
