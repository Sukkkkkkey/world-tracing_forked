"""Download and verify a frozen category sample of the official OmniObject3D scans."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time

import requests

from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import PROCESSED_ROOT

INDEX_URL = ("https://openxlab.org.cn/datasets/api/v2/datasets/"
             "omniobject3d%2COmniObject3D-New/r/main")
DOWNLOAD_ROOT = "https://openxlab.org.cn/datasets/resolve/6639/main"
MAX_FILE_BYTES = 5_000_000_000


def download(entry, directory):
    destination = directory / Path(entry["path"]).name
    expected = entry["sha256"]
    if destination.exists():
        if destination.stat().st_size != entry["size"] or file_digest(destination) != expected:
            raise ValueError(f"Existing source archive failed verification: {destination}")
        print(f"VERIFIED {destination.name}", flush=True)
        return
    partial = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(4):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == entry["size"]:
            break
        if offset > entry["size"]:
            raise ValueError(f"Partial download exceeds official size: {partial}")
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with requests.get(DOWNLOAD_ROOT + entry["path"], headers=headers,
                              stream=True, timeout=(30, 60)) as response:
                response.raise_for_status()
                if offset and (response.status_code != 206 or
                               not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-")):
                    raise ValueError("Server did not honor the resume range")
                with partial.open("ab" if offset else "wb") as output:
                    for block in response.iter_content(4 * 1024 * 1024):
                        output.write(block)
            if partial.stat().st_size != entry["size"]:
                raise IOError("Downloaded size differs from official metadata")
            break
        except (requests.RequestException, OSError) as error:
            print(f"RETRY {destination.name} {attempt + 1} {type(error).__name__}", flush=True)
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    actual = file_digest(partial)
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch, partial retained: {partial}")
    partial.replace(destination)
    print(f"DOWNLOADED {destination.name} {entry['size']} {actual}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=PROCESSED_ROOT / "omniobject3d/ood-v1")
    parser.add_argument("--categories", type=int, default=25)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.categories < 1 or args.workers < 1:
        parser.error("Positive category and worker counts are required")
    root = args.dataset.resolve()
    if not root.is_relative_to(PROCESSED_ROOT.resolve()):
        parser.error("Dataset must be under the project processed-data directory")
    root.mkdir(parents=True, exist_ok=True)
    plan_path = root / "download_plan.json"
    if plan_path.exists():
        plan = read_json(plan_path)
        if len(plan["archives"]) != args.categories:
            raise ValueError("Frozen category count changed")
    else:
        response = requests.get(INDEX_URL, params={"recursive": "true", "needContent": "true",
                                "limit": 500, "prefix": "/raw/raw_scans"}, timeout=30)
        response.raise_for_status()
        index = response.json()["data"]
        if index["hasNext"]:
            raise ValueError("Official index is paginated, refusing an incomplete sampling frame")
        files = [entry for entry in index["list"] if entry["schema"] == "file"]
        eligible = [entry for entry in files if 0 < entry["size"] < MAX_FILE_BYTES]
        eligible.sort(key=lambda entry: hashlib.sha256(
            ("20261111:" + entry["path"]).encode()).hexdigest())
        if args.categories > len(eligible):
            raise ValueError("Insufficient eligible categories")
        plan = {
            "dataset": "omniobject3d-ood-v1",
            "source": "official OpenXLab repository omniobject3d/OmniObject3D-New",
            "source_url": INDEX_URL,
            "selection": "First categories ranked by SHA256('20261111:' + official archive path)",
            "category_count_in_index": len(files),
            "eligible_category_count": len(eligible),
            "file_limit_bytes": MAX_FILE_BYTES,
            "excluded_archives": [entry for entry in files if entry not in eligible],
            "archives": eligible[:args.categories],
            "download_bytes": sum(entry["size"] for entry in eligible[:args.categories]),
            "destination": str(root / "source_archives"),
            "overlap_status": "Independent scan source absent from published 3D training source lists; asset overlap unverified",
        }
        atomic_json(root / "official_index.json", index)
        atomic_json(plan_path, plan)
    exclusion_path = root / "acquisition_exclusions.json"
    exclusions = read_json(exclusion_path) if exclusion_path.exists() else []
    excluded_paths = {entry["path"] for entry in exclusions}
    if excluded_paths - {entry["path"] for entry in plan["archives"]}:
        raise ValueError("Acquisition exclusion is outside the frozen download plan")
    archives = [entry for entry in plan["archives"] if entry["path"] not in excluded_paths]
    archive_dir = root / "source_archives"
    archive_dir.mkdir(exist_ok=True)
    print(json.dumps({"categories": len(plan["archives"]), "download_bytes": plan["download_bytes"],
                      "destination": str(archive_dir)}), flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(lambda entry: download(entry, archive_dir), archives))
    atomic_json(root / "download_complete.json", {
        "plan_sha256": file_digest(plan_path),
        "verified_archives": len(archives),
        "verified_bytes": sum(entry["size"] for entry in archives),
        "acquisition_exclusions": exclusions,
    })


if __name__ == "__main__":
    main()
