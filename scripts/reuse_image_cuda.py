"""Copy exact, Python-independent CUDA runtime distributions into an isolated environment.

Run with the image Python. Validate installed RECORD hashes while copying; never
link to or modify the shared image. Compiled Python packages are not eligible.
"""
import argparse
import base64
import csv
import hashlib
import importlib.metadata as metadata
import io
import json
from pathlib import Path
import subprocess

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-python", type=Path, required=True)
    parser.add_argument("--exclude", nargs="*", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = Path(subprocess.check_output([str(args.target_python.resolve()), "-c",
        "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip()).resolve()
    if not target.is_relative_to(root / ".venv"):
        raise ValueError("Target must be the isolated project .venv")
    expected = dict(line.split("==", 1) for line in
        (root / "requirements.recovery.txt").read_text().splitlines()
        if line.startswith("nvidia-"))
    distributions = []
    for name, version in expected.items():
        if name in args.exclude:
            print("download from package index instead:", name, flush=True)
            continue
        dist = metadata.distribution(name)
        tags = [line[5:] for line in dist.read_text("WHEEL").splitlines() if line.startswith("Tag: ")]
        if dist.version != version or not tags or any(not t.startswith("py3-none-") for t in tags):
            raise ValueError("Image runtime version or ABI mismatch: " + name)
        distributions.append((name, dist))
    report = []
    for name, dist in distributions:
        records = []
        total = 0
        for entry in dist.files:
            relative = Path(str(entry))
            if "__pycache__" in relative.parts or relative.suffix == ".pyc":
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unexpected installed path: " + str(relative))
            destination = target / relative
            source = Path(dist.locate_file(entry))
            if relative.name == "RECORD":
                records.append([str(relative), "", ""])
                continue
            if not entry.hash or entry.hash.mode != "sha256":
                raise ValueError("Missing SHA256 in installed RECORD: " + str(relative))
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(destination.name + ".runtime-copy")
            digest = hashlib.sha256()
            size = 0
            with source.open("rb") as src, partial.open("wb") as dst:
                for chunk in iter(lambda: src.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
                    dst.write(chunk)
                    size += len(chunk)
            actual = base64.urlsafe_b64encode(digest.digest()).decode().rstrip("=")
            if actual != entry.hash.value or size != entry.size:
                partial.unlink()
                raise ValueError("Image RECORD verification failed: " + str(relative))
            if destination.exists():
                with destination.open("rb") as current:
                    same = hashlib.file_digest(current, "sha256").digest() == digest.digest()
                if not same:
                    partial.unlink()
                    raise ValueError("Conflicting target file: " + str(relative))
                partial.unlink()
            else:
                partial.replace(destination)
            records.append([str(relative), "sha256=" + actual, str(size)])
            total += size
        record_path = next(target / row[0] for row in records if Path(row[0]).name == "RECORD")
        stream = io.StringIO()
        csv.writer(stream, lineterminator="\n").writerows(records)
        record_path.write_text(stream.getvalue())
        report.append(dict(package=name, version=dist.version, source=str(dist.locate_file("")),
                           destination=str(target), files=len(records), bytes=total,
                           verification="installed RECORD SHA256"))
        print("verified and copied", name, dist.version, total, flush=True)
    report_path = root / ".runtime/logs/recovery-20261105/image-cuda-reuse.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

if __name__ == "__main__":
    main()
