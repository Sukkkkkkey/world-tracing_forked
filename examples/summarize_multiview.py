"""Rebuild multiview statistics from verified per-run results without rendering."""
import argparse
from pathlib import Path

from examples.evaluate_multiview import save_summary, summarize, summary_run, valid_result
from wt.experiment import file_digest, read_json
from wt.paths import OUTPUT_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    args = parser.parse_args()
    paths = sorted(args.experiment.glob("samples/*/*/*/seed-*/run.json"))
    if not paths:
        raise ValueError("No registered runs")
    planned = [summary_run(path) for path in paths]
    records, results, revisions = [], [], set()
    for index, path in enumerate(paths, 1):
        pointer = read_json(path.parent / "multiview.json")
        result_path = path.parent / pointer["result"]
        if file_digest(result_path) != pointer["sha256"]:
            raise ValueError(f"Result checksum mismatch: {result_path}")
        record = read_json(result_path)
        if record["revision"] != pointer["revision"] or valid_result(result_path.parent, record["signature"]) is None:
            raise ValueError(f"Incomplete or corrupt rendering artifacts: {result_path}")
        if record["inputs"]["run.json"] != file_digest(path):
            raise ValueError(f"Result no longer matches registered run: {path}")
        records.append(record)
        results.append({"path": str(result_path), "sha256": pointer["sha256"]})
        revisions.add(record["revision"])
        if index % 50 == 0:
            print(f"Verified {index}/{len(paths)} results", flush=True)
    if len(revisions) != 1:
        raise ValueError("Complete the experiment under one rendering revision before summarizing")
    revision = revisions.pop()
    root = OUTPUT_ROOT / "evaluation/multiview" / revision
    profile = read_json(root / "profile.json")
    summary = summarize(records, planned, profile["config"])
    summary.update(
        revision=revision, results=results, errors=[],
        selection={"sample": None, "method": None, "limit": None},
        status="complete" if not summary["failed_metrics"] else "failed",
    )
    output = root / args.experiment.name / "summary.json"
    save_summary(output, summary, planned)
    print(output, flush=True)
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
