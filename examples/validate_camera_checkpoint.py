"""Audit every finished candidate in the first camera batch before releasing the queue."""
import argparse
from pathlib import Path

import numpy as np

from evaluation.render_artifacts import load_render_groups
from examples.validate_baseline_v05 import check_manifest
from examples.validate_ood_results import verify_camera, verify_distances
from scripts.run_camera_ablation_batch import PAIRS
from wt.experiment import atomic_json, file_digest, read_json, resolve_reference


def check_experiment(entry):
    root = Path(entry["evaluation"])
    index = read_json(root / "index.json")
    summary = read_json(root / "summary.json")
    expected = {(method, config, stage) for method, config in PAIRS
                for stage in (["points"] if method == "wt" else ["decoded", "glb"])}
    actual = {(row["method"], row["config_id"], row["stage"]) for row in index["results"]}
    assert actual == expected and len(index["results"]) == 9
    assert len({row["sample_id"] for row in index["results"]}) == 1
    assert summary["pending_stages"] == 891
    assert summary["status_counts"] == {"complete": 9, "failed": 0}
    assert summary["index_sha256"] == file_digest(root / "index.json")
    assert len(summary["groups"]) == 9
    profile = read_json(root.parent / "profile.json")
    config = read_json(Path(profile["multiview_profile"]))["config"]
    references, checked = {}, []
    wt = next(row for row in index["results"] if row["method"] == "wt")
    wt_record = read_json(Path(wt["result_path"]))
    wt_prediction = Path(wt_record["source_directory"]) / "prediction.npz"
    for row in index["results"]:
        path = Path(row["result_path"])
        assert file_digest(path) == row["result_sha256"]
        record = read_json(path)
        assert record["status"] == "complete" and record["seed"] == 42
        for source, checksum in record["inputs"].items():
            assert file_digest(Path(source)) == checksum
        for name, checksum in record["files"].items():
            assert file_digest(path.parent / name) == checksum
        source = Path(record["source_directory"])
        sample = read_json(source.parents[2] / "input.json")
        reference_path = Path(record["reference"])
        if str(reference_path) not in references:
            reference = read_json(reference_path)
            for name, checksum in reference["files"].items():
                assert file_digest(reference_path.parent / name) == checksum
            assert len(reference["cameras"]) == 31
            maps = load_render_groups(reference_path.parent / "geometry.npz")
            surfel = load_render_groups(reference_path.parent / "surfel.npz")
            pngs = check_manifest(reference_path.parent, reference["artifacts"],
                                  {"native": maps, "surfel": surfel}, maps, reference_only=True)
            camera_check = verify_camera(sample, {**reference, "directory": str(reference_path.parent)}, maps)
            references[str(reference_path)] = {
                "maps": maps, "png_count": pngs, "camera": camera_check,
                "reference_sha256": file_digest(reference_path)}
            del surfel
        truth = references[str(reference_path)]["maps"]
        representations = {name: load_render_groups(path.parent / (name + ".npz"))
                           for name in ("surfel", "native") if name + ".npz" in record["files"]}
        pngs = check_manifest(path.parent, record["artifacts"], representations, truth,
                              comparisons=record["comparisons"], metric_config=config)
        with np.load(path.parent / "distances.npz", allow_pickle=False) as saved:
            verify_distances(saved, "full", record["shape"])
            for name, region in record["regions"].items():
                if region["status"] == "complete":
                    verify_distances(saved, name, region["metrics"])
        if record["stage"] == "glb":
            pair = record["export_pair"]
            assert pair["status"] == "complete"
            decoded_path = Path(pair["decoded_result"])
            assert file_digest(decoded_path) == pair["decoded_result_sha256"]
            decoded = read_json(decoded_path)
            np.testing.assert_array_equal(pair["matrix"], decoded["registration"]["matrix"])
        if record["config_id"] == "shared-wt-v1":
            parent = read_json(source / "wt_parent.json")
            parent_path = resolve_reference(source, parent["path"])
            assert file_digest(parent_path) == file_digest(wt_prediction)
        checked.append({key: row[key] for key in ("sample_id", "method", "config_id", "stage")})
        checked[-1]["png_count"] = pngs
        del representations
    return {"status": "passed", "evaluated_scope": "one-asset first batch",
            "checked_stages": len(checked), "remaining_stages": summary["pending_stages"],
            "index_sha256": file_digest(root / "index.json"), "results": checked,
            "references": {name: {k: v for k, v in value.items() if k != "maps"}
                           for name, value in references.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    state = read_json(args.state)
    assert state["status"] == "checkpoint"
    expected = {dataset + "/" + condition for dataset in ("GSO", "OOD") for condition in ("A0", "A1", "B0", "B1")}
    assert set(state["experiments"]) == expected
    reports = {}
    for label, entry in state["experiments"].items():
        reports[label] = check_experiment(entry)
        print("CHECKPOINT AUDIT", label, "passed", flush=True)
        atomic_json(args.output.with_suffix(".progress.json"), {"status": "running", "reports": reports})
    atomic_json(args.output, {"status": "passed", "checked_stages": 72, "experiments": reports,
                             "source_sha256": file_digest(Path(__file__))})


if __name__ == "__main__":
    main()
