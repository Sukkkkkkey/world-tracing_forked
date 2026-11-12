"""Verify downloaded files against pinned Hub metadata, entirely offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from huggingface_hub import hf_hub_download


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', nargs='+', required=True)
    args = parser.parse_args()
    root = Path(os.environ['WT_WEIGHTS_ROOT'])
    manifest = json.loads((root / 'download-manifest.json').read_text())
    results = {}
    for name in args.models:
        record = manifest[name]
        files = []
        for entry in record['files']:
            path = Path(hf_hub_download(record['repo'], entry['name'],
                        revision=record['revision'], local_files_only=True, token=False))
            if path.stat().st_size != entry['bytes']:
                raise ValueError(f'Size mismatch: {path}')
            digest = None
            if entry['sha256']:
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest != entry['sha256']:
                    raise ValueError(f'SHA256 mismatch: {path}')
            files.append(dict(path=str(path), bytes=path.stat().st_size, sha256=digest))
            print(f"{name}: verified {entry['name']}", flush=True)
        results[name] = dict(repo=record['repo'], revision=record['revision'],
                             status='passed', files=files)
    out = Path(os.environ['WT_OUTPUT_ROOT']) / 'validation/weights-integrity.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + '\n')
    print(out, flush=True)


if __name__ == '__main__':
    main()
