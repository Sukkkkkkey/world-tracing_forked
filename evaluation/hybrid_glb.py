"""Standalone GLB evaluation for the Hybrid pilot, using v0.5 GLB-to-GT metrics."""
from pathlib import Path
import time
import traceback

from examples.evaluate_baseline_v2 import BaselineEvaluator
from examples.evaluate_multiview import result_lock, valid_result
from wt.experiment import atomic_json, digest, file_digest, read_json


class HybridGlbEvaluator(BaselineEvaluator):
    def evaluate(self, directory, stage, experiment_name):
        if stage != "glb":
            raise ValueError("Hybrid evaluation accepts only exported GLBs")
        directory = Path(directory)
        state = read_json(directory / "run.json")
        sample_path = directory.parents[2] / "input.json"
        sample = read_json(sample_path)
        if state["method"] != "wt_trellis2" or state["status"] != "complete" or state["input_sha256"] != sample["sha256"]:
            raise ValueError("Inconsistent Hybrid inference state")
        dataset = Path(sample["evaluation_dir"])
        parent_record = directory / "wt_parent.json"
        parent = (directory / read_json(parent_record)["path"]).resolve()
        paths = [directory / name for name in ("run.json", "config.json", "mesh.json", "mesh.glb")]
        paths += [sample_path, Path(sample["image"]), dataset / "gt_points.npz", dataset / "gt_depth.npz",
                  parent_record, parent]
        inputs = {str(path): file_digest(path) for path in paths}
        if inputs[str(Path(sample["image"]))] != sample["sha256"] or any(
                inputs[str(dataset / k)] != sample["artifact_sha256"][k] for k in ("gt_points.npz", "gt_depth.npz")):
            raise ValueError("Frozen image or GT changed")
        glb_hash = state["artifacts"]["mesh"].get("sha256")
        if glb_hash and glb_hash != inputs[str(directory / "mesh.glb")]:
            raise ValueError("Exported GLB changed")
        def version():
            return [(s.st_size, s.st_mtime_ns) for s in (path.stat() for path in paths)]
        before = version()
        cameras, reference, truth = self.reference(sample)
        scope = "exported-glb-only-v1"
        signature = digest(dict(inputs=inputs, reference=truth["signature"], revision=self.revision,
                                stage=stage, scope=scope, adapter=file_digest(Path(__file__))))
        dest = (self.root / experiment_name / "samples" / sample["sample_id"] / state["method"]
                / state["config_id"] / f"seed-{state['seed']:04d}" / stage / signature[:20])
        with result_lock(dest):
            cached = valid_result(dest, signature, status_key="numerical_status")
            if cached and cached.get("status") == "complete":
                return cached
            result = dict(revision=self.revision, signature=signature, evaluation_scope=scope,
                          sample_id=sample["sample_id"], method=state["method"], config_id=state["config_id"],
                          seed=state["seed"], stage=stage, source_directory=str(directory), inputs=inputs,
                          result_path=str(dest / "result.json"), reference=str(Path(truth["directory"]) / "result.json"),
                          protocol_version=self.config["protocol_version"], files={})
            started = time.monotonic()
            try:
                # compute loads only the requested mesh. Its optional decoded_record defaults to None.
                result.update(self.compute(directory, state, "glb", sample, cameras, reference, dest))
                result.pop("export_pair", None)
                result["numerical_status"] = "complete"
                result["artifacts"] = self.ensure_images(result, dest, reference, cameras)
                if before != version():
                    raise RuntimeError("Evaluation inputs changed")
                result["status"] = "complete"
            except Exception:
                result.update(status="failed", error=traceback.format_exc())
            result["seconds"] = time.monotonic() - started
            atomic_json(dest / "result.json", result)
            return result
