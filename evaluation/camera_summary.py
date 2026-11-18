"""Single-seed camera summaries with configuration-aware candidate identity."""
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from examples.summarize_baseline_v2 import (
    aggregate, asset_group, coverage, distribution, stage_pairs,
)
from wt.experiment import file_digest, read_json


def candidate_key(row):
    return tuple(row[k] for k in ("sample_id", "method", "config_id", "seed", "stage"))


def method_label(method, configuration):
    return method + "/" + configuration


def paired_configurations(assets, configurations):
    output = []
    samples = sorted({key[0] for key in assets})
    for stage in ("decoded", "glb"):
        for first, second in combinations(configurations, 2):
            pairs = []
            for sample in samples:
                a = assets.get((sample, method_label(*first), "points" if first[0] == "wt" else stage), {})
                b = assets.get((sample, method_label(*second), "points" if second[0] == "wt" else stage), {})
                left = a.get("values", {}).get("single_seed", {})
                right = b.get("values", {}).get("single_seed", {})
                if left and right:
                    pairs.append((sample, left, right))
            names = sorted({name for _, a, b in pairs for name in a.keys() & b.keys()
                            if name.startswith(("shape.", "regions.", "surfel."))})
            metrics = {}
            for name in names:
                common = [(sample, a[name], b[name]) for sample, a, b in pairs if name in a and name in b]
                metrics[name] = {**distribution([a-b for _, a, b in common]),
                                 "first_lower": sum(a < b for _, a, b in common),
                                 "first_higher": sum(a > b for _, a, b in common),
                                 "sample_ids": [sample for sample, _, _ in common]}
            if metrics:
                output.append({"stage": stage, "mode": "single_seed", "first": method_label(*first),
                               "second": method_label(*second), "difference": "first-minus-second",
                               "metrics": metrics})
    return output


def summary(directory):
    directory = Path(directory)
    plan = read_json(directory / "plan.json")
    index = read_json(directory / "index.json")
    planned = {candidate_key(row): row for row in plan["candidates"]}
    if len(planned) != len(plan["candidates"]):
        raise ValueError("Duplicate planned method/configuration candidate")
    grouped = defaultdict(list)
    for sample, method, config, seed, stage in planned:
        if seed != 42:
            raise ValueError("Camera experiment uses seed 42 only")
        grouped[(sample, method_label(method, config), stage)]
    records, seen = [], set()
    for entry in index["results"]:
        key = candidate_key(entry)
        if key not in planned or key in seen:
            raise ValueError("Unexpected or duplicate indexed candidate")
        seen.add(key)
        path = Path(entry["result_path"])
        if file_digest(path) != entry["result_sha256"]:
            raise ValueError("Indexed result checksum differs")
        record = read_json(path)
        if candidate_key(record) != key or record["revision"] != index["revision"]:
            raise ValueError("Result identity or revision differs")
        records.append(record)
        grouped[(record["sample_id"], method_label(record["method"], record["config_id"]),
                 record["stage"])].append(record)
    assets = {key: asset_group(rows, [42], 42, calibration=True) for key, rows in grouped.items()}
    configurations = sorted({(r["method"], r["config_id"]) for r in plan["candidates"]})
    labeled = [dict(row, method=method_label(row["method"], row["config_id"])) for row in records]
    return {
        "revision": index["revision"], "config": plan["config"], "mode": "fixed_seed",
        "summary_source_sha256": file_digest(Path(__file__)),
        "index_sha256": file_digest(directory / "index.json"),
        "planned_stages": len(planned), "evaluated_stages": len(records),
        "pending_stages": len(planned) - len(records),
        "status_counts": {status: sum(r["status"] == status for r in records) for status in ("complete", "failed")},
        "assets": [dict(sample_id=sample, method=method, stage=stage, **value)
                   for (sample, method, stage), value in sorted(assets.items())],
        "groups": aggregate(assets), "coverage": coverage(assets),
        "paired_methods": paired_configurations(assets, configurations),
        "paired_stages": stage_pairs(labeled, [42]),
        "render_index": [{key: row.get(key) for key in (
            "sample_id", "method", "config_id", "stage", "seed", "status", "result_path",
            "artifacts", "reference")} for row in labeled],
    }
