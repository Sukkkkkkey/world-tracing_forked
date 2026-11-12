"""Download the frozen GSO originals after matching the historical evaluation split."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import time
import logging
import argparse
import shutil
import requests
from urllib.parse import quote

from huggingface_hub import HfApi

REPO = "suvadityamuk/google-scanned-objects-raw"
REVISION = "6139aa33f6163a9f1c7352dd386760f40691ce0d"

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def immutable_json(path, value):
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Frozen metadata differs: " + str(path))
    else:
        path.write_bytes(data)

def main():
    logging.getLogger("huggingface_hub").setLevel(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="https://huggingface.co")
    parser.add_argument("--direct", action="store_true")
    parser.add_argument("--resolve-proxy", help="Proxy only the public resolve request; download the returned CDN URL directly")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.endpoint not in ("https://huggingface.co", "https://hf-mirror.com"):
        parser.error("Only the reviewed official or mirror endpoint is supported")
    repo = Path(__file__).resolve().parents[1]
    raw = Path(os.environ["WT_DATA_ROOT"]) / "raw/gso"
    archives = raw / "archives"
    logs = repo / ".runtime/logs/recovery-20261105"
    recipe = json.loads((repo / "configs/gso_recovery.json").read_text())
    ids = recipe["canonical_ids"]
    if len(ids) != 1030 or len(set(ids)) != 1030:
        raise ValueError("Expected 1030 unique original IDs")
    audit = json.loads((repo / "configs/recovery_split_audit.json").read_text())
    if not all(audit[name]["same_ids"] for name in ("pilot", "eval100")):
        raise ValueError("Historical sample identity has not been recovered")
    immutable_json(raw / "canonical_ids.json", ids)
    immutable_json(raw / "SOURCE.json", recipe["provenance"])
    manifest_path = archives / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        entries = manifest["files"]
        if (manifest["repo"] != REPO or manifest["revision"] != REVISION
                or manifest["original_ids_sha256"] != sha(raw / "canonical_ids.json")
                or len(entries) != 1030 or {Path(x["path"]).stem for x in entries} != set(ids)):
            raise ValueError("Frozen archive metadata differs")
    else:
        api = HfApi(endpoint="https://huggingface.co", token=False)
        for attempt in range(6):
            try:
                info = api.dataset_info(REPO, revision=REVISION, files_metadata=True)
                break
            except Exception as error:
                print("metadata retry", attempt + 1, type(error).__name__, flush=True)
                if attempt == 5:
                    raise RuntimeError("Dataset metadata remains unavailable") from None
                time.sleep(min(2 ** (attempt + 1), 30))
        if info.sha != REVISION:
            raise ValueError("Dataset revision mismatch")
        selected = set(ids)
        entries = sorted(
            [dict(path=f.rfilename, size=f.size, sha256=f.lfs.sha256)
             for f in info.siblings if f.rfilename.endswith(".zip") and Path(f.rfilename).stem in selected],
            key=lambda x: x["path"])
        if len(entries) != 1030 or {Path(x["path"]).stem for x in entries} != selected:
            raise ValueError("Mirror does not contain the recovered original set")
        manifest = dict(repo=REPO, revision=REVISION, files=entries,
            original_ids_sha256=sha(raw / "canonical_ids.json"),
            unselected_mirror_assets=sorted({Path(f.rfilename).stem for f in info.siblings
                                            if f.rfilename.endswith(".zip")} - selected))
        immutable_json(archives / "manifest.json", manifest)

    if any(Path(item["path"]).name != item["path"] for item in entries):
        raise ValueError("Archive filenames must be flat")
    print(json.dumps(dict(assets=len(entries), total_bytes=sum(x["size"] for x in entries),
                          largest_file_bytes=max(x["size"] for x in entries), destination=str(archives))), flush=True)

    def fetch(item):
        target = archives / item["path"]
        if target.is_file() and target.stat().st_size == item["size"] and sha(target) == item["sha256"]:
            return item["path"]
        if target.exists():
            raise ValueError("Existing original failed verification: " + item["path"])
        for attempt in range(5):
            try:
                staging = repo / ".runtime/downloads/gso"
                staging.mkdir(parents=True, exist_ok=True)
                partial = staging / (item["path"] + ".partial")
                complete = partial.is_file() and partial.stat().st_size == item["size"] and sha(partial) == item["sha256"]
                if not complete:
                    offset = partial.stat().st_size if partial.exists() else 0
                    url = f"{args.endpoint}/datasets/{REPO}/resolve/{REVISION}/{quote(item['path'])}"
                    with requests.Session() as client:
                        client.trust_env = not args.direct
                        params = {"download": "true", "recovery": str(time.time_ns())}
                        if args.resolve_proxy:
                            response = client.head(url, params=params, allow_redirects=False,
                                proxies={"https": args.resolve_proxy}, timeout=(20, 30))
                            response.raise_for_status()
                            if response.status_code not in (301, 302, 303, 307, 308):
                                raise ValueError("Expected a public CDN redirect")
                            url, params = response.headers["Location"], None
                        with client.get(url, params=params,
                                headers={"Range": f"bytes={offset}-"} if offset else {},
                                stream=True, timeout=(20, 60)) as response:
                            response.raise_for_status()
                            if response.status_code == 206:
                                if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                                    raise ValueError("Unexpected archive byte range")
                                mode = "ab"
                            else:
                                mode = "wb"
                            with partial.open(mode) as output:
                                for chunk in response.iter_content(1024 * 1024):
                                    output.write(chunk)
                if partial.stat().st_size != item["size"] or sha(partial) != item["sha256"]:
                    raise ValueError("Archive size or SHA256 mismatch")
                published = target.with_name(target.name + ".partial")
                shutil.copyfile(partial, published)
                if sha(published) != item["sha256"]:
                    raise ValueError("Published archive copy differs")
                published.replace(target)
                partial.unlink()
                return item["path"]
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch, item): item for item in entries}
        for count, future in enumerate(as_completed(futures), 1):
            try:
                print(count, "/1030 verified", future.result(), flush=True)
            except Exception as error:
                failures.append(dict(path=futures[future]["path"], error=type(error).__name__))
                print(count, "/1030 failed", futures[future]["path"], type(error).__name__, flush=True)
            (logs / "gso-download.progress.json").write_text(json.dumps(
                dict(finished=count, total=1030, failures=failures, endpoint=args.endpoint, direct=args.direct, resolve_proxy=args.resolve_proxy), indent=2))
    if failures:
        raise RuntimeError(str(len(failures)) + " archives failed")
    immutable_json(archives / "download.complete.json", dict(repo=REPO, revision=REVISION, archives=1030))
    print("GSO archive download complete; extraction and COMPLETE.json verification follow separately.", flush=True)

if __name__ == "__main__":
    main()
