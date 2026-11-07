"""Rebuild verified GSO originals, derived copies, frozen splits and input views."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["raw", "derive", "render", "all"], default="all")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    raw = Path(os.environ["WT_DATA_ROOT"]) / "raw/gso"
    processed = Path(os.environ["WT_PROCESSED_ROOT"]) / "gso"
    assets, dataset = processed / "assets", processed / "v1"
    def run(*command):
        print("RUN", *command, flush=True)
        subprocess.run([sys.executable, "-uB", *map(str, command)], cwd=root, check=True)
    complete = raw / "archives/download.complete.json"
    if not complete.is_file():
        raise RuntimeError("All original ZIPs must be downloaded and hash-verified first")
    if args.stage in ("raw", "all") and not (raw / "COMPLETE.json").is_file():
        run("examples/verify_gso_raw.py", "--root", raw)
    from examples.verify_gso_raw import require_complete
    require_complete(raw)
    if args.stage in ("derive", "all"):
        if not (dataset / "split.json").is_file():
            run("examples/import_gso_mirror.py", "--source", raw / "archives",
                "--out", assets, "--dataset", dataset, "--workers", "4")
        import numpy as np
        from examples.prepare_gso_inventory import split_ids
        recipe = json.loads((root / "configs/gso_recovery.json").read_text())
        old = json.loads((root / "configs/historical_gso_samples.json").read_text())
        frozen = json.loads((dataset / "split.json").read_text())
        expected = split_ids(recipe["canonical_ids"])
        if np.__version__ != "1.26.4" or frozen["numpy"] != "1.26.4":
            raise ValueError("The migrated NumPy version is required for split replay")
        if (frozen["total"], frozen["valid"], frozen["excluded"]) != (1030, 1030, 0):
            raise ValueError("The recovered inventory must have 1030 valid originals with no exclusions")
        if frozen["splits"] != expected:
            raise ValueError("Frozen split differs from exact PCG64 replay")
        if any(set(frozen["splits"][name]) != set(old[name]) for name in ("pilot", "eval100")):
            raise ValueError("Recovered evaluation sample IDs differ from the historical workbook")
        from wt.experiment import atomic_json
        atomic_json(dataset / "recovery_audit.json", dict(status="passed",
            originals=1030, numpy=np.__version__, seed=20261013,
            exact_pcg64_replay=True, historical_pilot_ids=True, historical_eval100_ids=True,
            recipe_sha256=hashlib.sha256((root / "configs/gso_recovery.json").read_bytes()).hexdigest(),
            original_archive_comparison="not rerun; inaccessible historical reference ZIP"))
    if args.stage in ("render", "all"):
        storage = json.loads((Path(os.environ['WT_OUTPUT_ROOT']) / 'validation/artifact-storage.json').read_text())
        if storage['status'] != 'passed' or storage['source_sha256'] != hashlib.sha256((root / 'wt/artifacts.py').read_bytes()).hexdigest():
            raise ValueError('Current artifact writer has not passed the real-storage roundtrip check')
        audit = json.loads((dataset / "recovery_audit.json").read_text())
        if audit.get("status") != "passed":
            raise ValueError("Historical split verification is required before rendering")
        for split in ("pilot", "eval100"):
            run("examples/prepare_gso_views.py", "--dataset", dataset,
                "--split", split, "--asset-up", "z", "--raw-root", raw)
        print("All 110 historical GSO evaluation inputs and ground truth views are ready.", flush=True)
    print(dataset, flush=True)

if __name__ == "__main__":
    main()
