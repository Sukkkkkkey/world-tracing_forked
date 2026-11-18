"""Inference adapters that freeze each model's spatial preprocessing for group B."""
from contextlib import contextmanager
from pathlib import Path

from evaluation.camera_ablation import frozen_mesh_image, frozen_wt_image
from wt.batch import InferenceBackend
from wt.baselines.pixal3d import Pixal3DBackend
from wt.data import preprocess_rgba_for_model
from wt.experiment import file_digest, read_json


def spatial_record(image):
    path = Path(image).parent / "input.json"
    if not path.exists():
        return None
    sample = read_json(path)
    if "camera_ablation" not in sample:
        return None
    record_path = Path(sample["camera_ablation"]["spatial"])
    if file_digest(record_path) != sample["artifact_sha256"]["spatial.json"]:
        raise ValueError("Frozen preprocessing record changed")
    record = read_json(record_path)
    return record["spatial"] if record["frozen"] else None


@contextmanager
def fixed_mesh_preprocessing(pipeline, spatial, method):
    if spatial is None:
        yield
        return
    original = pipeline.preprocess_image
    pipeline.preprocess_image = lambda image: frozen_mesh_image(image, spatial, method)
    try:
        yield
    finally:
        pipeline.preprocess_image = original


class CameraInferenceBackend(InferenceBackend):
    def prepare_wt_inputs(self, image, rgba, cfg):
        spatial = spatial_record(image)
        if spatial is None:
            return super().prepare_wt_inputs(image, rgba, cfg)
        return preprocess_rgba_for_model(
            frozen_wt_image(rgba, spatial), image_size=self.model_cfg["image_size"],
            num_layers=6, center_crop=False, alpha_erode_px=cfg["alpha_erode"],
            bg_color=tuple(cfg["bg_color"]))

    def generate_mesh(self, image, cfg, seed, directory, parent):
        with fixed_mesh_preprocessing(self.pipeline, spatial_record(image), "trellis2"):
            return super().generate_mesh(image, cfg, seed, directory, parent)


class CameraPixalBackend(Pixal3DBackend):
    def infer(self, image_path, directory, seed):
        with fixed_mesh_preprocessing(self.pipeline, spatial_record(image_path), "pixal3d"):
            return super().infer(image_path, directory, seed)


from scripts.recovery_memory import MemoryBoundBackend


class CameraMemoryBackend(MemoryBoundBackend, CameraInferenceBackend):
    """Apply the component-verified memory policy to all new mesh inference."""
    def __init__(self, *args, **kwargs):
        from scripts.recovery_memory import AUDIT, CHUNK
        from wt.paths import REPO_ROOT
        CameraInferenceBackend.__init__(self, *args, **kwargs)
        path = AUDIT / "memory-component-checks.json"
        report = read_json(path)
        if report["status"] != "passed":
            raise ValueError("Memory component checks are not valid")
        sources = {}
        for name in ("recovery_memory.py", "r2_layernorm_memory.py", "r2_topology_memory.py"):
            old = [value for key, value in report["source_sha256"].items()
                   if Path(key).name == name]
            actual = file_digest(REPO_ROOT / "scripts" / name)
            if old != [actual]:
                raise ValueError("Memory implementation differs from checked sources")
            sources["scripts/" + name] = actual
        for evidence, checksum in report["evidence_sha256"].items():
            if file_digest(Path(evidence)) != checksum:
                raise ValueError("Memory component evidence changed")
        self.provenance["runtime_memory_policy"] = dict(
            name="historical-v6-independent-row-topology-cache-release",
            source_sha256=sources, component_checks=str(path),
            component_checks_sha256=file_digest(path),
            layernorm_max_elements=16_777_216, topology_chunk=CHUNK,
            decoder_parameter_requires_grad=False,
            invariants=["input", "seed", "weights", "precision", "sampling steps",
                        "resolution", "channel-axis reductions", "topology ordering"])
