"""Recover public model files from ModelScope, matching the pinned official HF bytes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode
import requests

def verify(path, item):
    if not path.is_file() or path.stat().st_size != item["bytes"]:
        return False
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != item["modelscope_sha256"]:
        return False
    if item.get("sha256"):
        return actual == item["sha256"]
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == item["blob_id"]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    lock = json.loads((repo_root / "configs/recovery_weights.lock.json").read_text())
    root = Path(os.environ["WT_WEIGHTS_ROOT"]) / "modelscope"
    records = {}
    for name, record in lock.items():
        directory = root / record["repo"] / record["revision"]
        records[name] = dict(record, snapshot=str(directory), status="downloading",
            endpoint="https://modelscope.cn", metadata_endpoint="https://huggingface.co",
            bytes=sum(item["bytes"] for item in record["files"]))
        print(name, "files", len(record["files"]), "bytes", records[name]["bytes"],
              "largest", max(x["bytes"] for x in record["files"]), "destination", directory, flush=True)
    def save():
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(records, indent=2) + "\n")
    save()
    def fetch(job):
        name, item = job
        record = records[name]
        target = Path(record["snapshot"]) / item["name"]
        if verify(target, item):
            print("verified cached", name, item["name"], flush=True)
            return
        if target.exists():
            raise ValueError("Invalid existing final weight: " + str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        query = urlencode(dict(Revision=item["modelscope_revision"], FilePath=item["name"]))
        url = f'https://modelscope.cn/api/v1/models/{record["repo"]}/repo?{query}'
        for attempt in range(5):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                with requests.Session() as client:
                    client.trust_env = False
                    headers = {"Range": f"bytes={offset}-"} if offset else {}
                    with client.get(url, headers=headers, stream=True, timeout=(20, 120)) as response:
                        if response.status_code == 416 and offset == item["bytes"]:
                            pass
                        else:
                            response.raise_for_status()
                            if response.status_code == 206:
                                if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                                    raise ValueError("Unexpected range response")
                                mode = "ab"
                            else:
                                mode = "wb"
                            with partial.open(mode) as stream:
                                for chunk in response.iter_content(4 * 1024 * 1024):
                                    stream.write(chunk)
                if not verify(partial, item):
                    raise ValueError("Size or checksum mismatch: " + item["name"])
                partial.replace(target)
                print("verified", name, item["name"], flush=True)
                return
            except (requests.RequestException, OSError) as error:
                print("retry", name, item["name"], attempt + 1, type(error).__name__, flush=True)
                if attempt == 4:
                    raise RuntimeError("ModelScope download failed: " + item["name"]) from None
                time.sleep(2 ** attempt)
    jobs = sorted([(name, item) for name, record in records.items() for item in record["files"]],
                  key=lambda x: x[1]["bytes"])
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(fetch, jobs))
    for record in records.values():
        record.update(status="downloaded", integrity="verified",
                      local_files=[str(Path(record["snapshot"]) / item["name"]) for item in record["files"]])
    save()

if __name__ == "__main__":
    main()
