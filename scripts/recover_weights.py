"""Restore pinned HF weights independently, then merge and verify manifests."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import hashlib
import os
import subprocess
import sys
import argparse

root = Path(__file__).resolve().parents[1]
weights = Path(os.environ["WT_WEIGHTS_ROOT"])
live = root / ".runtime/logs/recovery-20261105"
live.mkdir(parents=True, exist_ok=True)
jobs = [("public", ["--workers", "2"]),
        ("object", ["--models", "object", "--workers", "1"])]
def run(job):
    name, args = job
    manifest = live / (name + ".weights.json")
    script = "fetch_modelscope_public.py" if name == "public" else "fetch_weights.py"
    command = [sys.executable, "-uB", str(root / "scripts" / script),
               "--manifest", str(manifest), *args]
    with (live / (name + ".weights.log")).open("a", buffering=1) as log:
        code = subprocess.call(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    return name, code, manifest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--models", nargs="+", choices=["public", "object"], default=["public", "object"])
args = parser.parse_args()
jobs = [job for job in jobs if job[0] in args.models]
failed = False
with ThreadPoolExecutor(max_workers=2) as pool:
    for f in as_completed([pool.submit(run, job) for job in jobs]):
        name, code, path = f.result()
        failed |= code != 0
        merged = {}
        for part in live.glob("*.weights.json"):
            merged.update(json.loads(part.read_text()))
        (weights / "download-manifest.json").write_text(json.dumps(merged, indent=2) + "\n")
        print(name, "exit", code, flush=True)

manifest = json.loads((weights / "download-manifest.json").read_text())
for name, record in manifest.items():
    if record["status"] != "downloaded":
        failed = True
        continue
    if record.get("integrity") == "verified":
        continue
    for item in record["files"]:
        file = Path(record["snapshot"]) / item["name"]
        if file.stat().st_size != item["bytes"]:
            raise ValueError("Size mismatch: " + name + "/" + item["name"])
        if item.get("sha256"):
            with file.open("rb") as source:
                actual = hashlib.file_digest(source, "sha256").hexdigest()
            if actual != item["sha256"]:
                raise ValueError("SHA256 mismatch: " + name + "/" + item["name"])
        print("verified", name, item["name"], flush=True)
    record["integrity"] = "verified"
(weights / "download-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
raise SystemExit(int(failed))
