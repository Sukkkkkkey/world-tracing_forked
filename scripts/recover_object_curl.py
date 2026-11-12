"""Resume the pinned authorized WT checkpoint via a direct official CDN connection."""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import urlsplit
from filelock import FileLock
from huggingface_hub import get_hf_file_metadata

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def main():
    logging.getLogger("huggingface_hub").setLevel(logging.CRITICAL)
    root = Path(__file__).resolve().parents[1]
    spec = json.loads((root / "configs/recovery_object.lock.json").read_text())
    weights = Path(os.environ["WT_WEIGHTS_ROOT"])
    token = os.environ.get("HF_TOKEN") or (root / ".runtime/hf_token").read_text().strip()
    item = next(f for f in spec["files"] if f["name"] == "model.pt")
    folder = "models--" + spec["repo"].replace("/", "--")
    cache = Path(os.environ["HF_HOME"]) / "hub"
    snapshot = cache / folder / "snapshots" / spec["revision"]
    target = snapshot / item["name"]
    work = root / ".runtime/downloads/object-model.pt.partial"
    old_partial = cache / folder / "blobs" / (item["sha256"] + ".incomplete")
    lock = cache / ".locks" / folder / (item["sha256"] + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock)):
        ready = target.is_file() and target.stat().st_size == item["bytes"] and sha(target) == item["sha256"]
        if not ready:
            if not work.exists() and old_partial.exists():
                shutil.copyfile(old_partial, work)
                if work.stat().st_size != old_partial.stat().st_size or sha(work) != sha(old_partial):
                    raise ValueError("Existing download prefix was not copied intact")
            for attempt in range(12):
                if work.exists() and work.stat().st_size == item["bytes"]:
                    break
                print("attempt", attempt + 1, "resume_bytes", work.stat().st_size if work.exists() else 0, flush=True)
                try:
                    url = f'https://huggingface.co/{spec["repo"]}/resolve/{spec["revision"]}/{item["name"]}?download=true&recovery={time.time_ns()}'
                    meta = get_hf_file_metadata(url, token=token, timeout=30)
                    if meta.etag != item["sha256"] or meta.size != item["bytes"] or meta.commit_hash != spec["revision"]:
                        raise ValueError("Official metadata differs from the pinned object checkpoint")
                    host = urlsplit(meta.location).hostname or ""
                    if urlsplit(meta.location).scheme != "https" or not (
                        host.endswith(".hf.co") or host.endswith(".huggingface.co")):
                        raise ValueError("Unexpected official CDN destination")
                    print("authorized official CDN", host, "expected_bytes", meta.size, flush=True)
                    command = ["curl", "--disable", "--silent", "--show-error", "--fail", "--location",
                        "--noproxy", "*", "--continue-at", "-", "--connect-timeout", "20",
                        "--speed-time", "90", "--speed-limit", "1024", "--max-time", "900",
                        "--output", str(work), "--config", "-"]
                    environment = {k:v for k,v in os.environ.items() if k != "HF_TOKEN"}
                    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, env=environment)
                    if any(c in meta.location for c in ("\n", "\r", '"', "\\")):
                        child.terminate()
                        raise ValueError("Unexpected characters in CDN URL")
                    child.stdin.write('url = "' + meta.location + '"\n')
                    child.stdin.close()
                    for line in child.stdout:
                        print(re.sub(r"https?://\S+", "<URL>", line.rstrip()), flush=True)
                    result = child.wait()
                    print("transfer_exit", result, "bytes", work.stat().st_size if work.exists() else 0, flush=True)
                    if result == 0:
                        break
                except ValueError:
                    raise
                except Exception as error:
                    status = getattr(getattr(error, "response", None), "status_code", None)
                    print("resolve_retry", type(error).__name__, status, flush=True)
                    if status in (401, 403):
                        raise RuntimeError("Official access authorization failed") from None
                time.sleep(min(2 ** attempt, 30))
            if not work.is_file() or work.stat().st_size != item["bytes"] or sha(work) != item["sha256"]:
                raise RuntimeError("Object weight is incomplete or failed SHA256; partial retained")
            snapshot.mkdir(parents=True, exist_ok=True)
            published = target.with_name(target.name + ".partial")
            shutil.copyfile(work, published)
            if sha(published) != item["sha256"]:
                raise ValueError("Copied checkpoint failed SHA256")
            published.replace(target)
        for file in spec["files"]:
            path = snapshot / file["name"]
            if not path.is_file() or path.stat().st_size != file["bytes"]:
                raise ValueError("Missing pinned checkpoint file: " + file["name"])
            if not file.get("sha256"):
                data = path.read_bytes()
                actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
                if actual != file["blob_id"]:
                    raise ValueError("Configuration/readme differs from pinned official content")
    record = dict(spec, status="downloaded", integrity="verified", snapshot=str(snapshot),
        endpoint="https://huggingface.co", metadata_endpoint="https://huggingface.co", gated="auto",
        local_files=[str(snapshot / f["name"]) for f in spec["files"]],
        transport="official authenticated metadata via task proxy; direct official CDN curl")
    part = root / ".runtime/logs/recovery-20261105/object.weights.json"
    part.write_text(json.dumps({"object": record}, indent=2) + "\n")
    manifest_path = weights / "download-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["object"] = record
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(manifest_path)
    print("Object checkpoint and official content checks passed:", target, flush=True)

if __name__ == "__main__":
    main()
