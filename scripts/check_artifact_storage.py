"""Exercise NPZ, PyTorch, PNG and textured GLB roundtrips on the actual output mount."""
from pathlib import Path
import numpy as np
from PIL import Image
import torch
import trimesh

from wt.artifacts import atomic_artifact, save_npz, save_torch
from wt.experiment import atomic_json, file_digest
from wt.paths import OUTPUT_ROOT

root = OUTPUT_ROOT / 'validation/storage'
root.mkdir(parents=True, exist_ok=True)
report = OUTPUT_ROOT / 'validation/artifact-storage.json'
report.unlink(missing_ok=True)
rng = np.random.default_rng(42)
points = rng.normal(size=(6, 128, 128, 3)).astype(np.float32)
mask = rng.random(points.shape[:-1]) > .25
save_npz(root / 'roundtrip.npz', xyz=points, mask=mask)
with np.load(root / 'roundtrip.npz', allow_pickle=False) as data:
    np.testing.assert_array_equal(data['xyz'], points)
    np.testing.assert_array_equal(data['mask'], mask)
tensor = torch.from_numpy(points[:1])
save_torch({'values': tensor}, root / 'roundtrip.pt')
torch.testing.assert_close(torch.load(root / 'roundtrip.pt', weights_only=True)['values'], tensor, rtol=0, atol=0)
image = Image.new('RGB', (16, 16), (40, 120, 220))
image.save(root / 'roundtrip.png')
np.testing.assert_array_equal(np.asarray(Image.open(root / 'roundtrip.png')), np.asarray(image))
mesh = trimesh.creation.box()
mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices), 2)), image=image)
with atomic_artifact(root / 'roundtrip.glb') as staged:
    trimesh.Scene(mesh).export(str(staged), extension_webp=True)
scene = trimesh.load(root / 'roundtrip.glb', process=False, force='scene')
assert len(scene.geometry) == 1 and np.isfinite(scene.bounds).all()
assert next(iter(scene.geometry.values())).visual.material.baseColorTexture.size == (16, 16)
atomic_json(report, dict(status='passed', seed=42, numpy_exact=True, torch_exact=True,
    png_exact=True, glb_reload=True, storage=str(root),
    source_sha256=file_digest(Path(__file__).resolve().parents[1] / 'wt/artifacts.py'),
    artifacts={p.name: file_digest(p) for p in root.iterdir() if p.is_file()}))
print(report, flush=True)
