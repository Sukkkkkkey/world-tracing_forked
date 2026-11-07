"""Resume a large official HF weight with aria2, verifying SHA256 before caching.

Stop any other downloader for the same file first. HF_TOKEN stays in this
process; aria2 receives only the official CDN URL on stdin, never the token.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import time
import re

from wt.paths import configure_cache_paths, OUTPUT_ROOT

configure_cache_paths()

from filelock import FileLock
from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--filename', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--public', action='store_true')
    args = parser.parse_args()
    token = False if args.public else os.environ.get('HF_TOKEN', False)
    endpoint = 'https://huggingface.co'
    url = hf_hub_url(args.repo, args.filename, revision=args.revision, endpoint=endpoint)
    meta = get_hf_file_metadata(url, token=token)
    digest = meta.etag
    if not digest or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Expected an LFS SHA256 checksum from the official endpoint')
    folder = 'models--' + args.repo.replace('/', '--')
    cache = Path(os.environ.get('HF_HUB_CACHE', str(Path(os.environ['HF_HOME']) / 'hub')))
    blob = cache / folder / 'blobs' / digest
    lock = cache / '.locks' / folder / f'{digest}.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    work = OUTPUT_ROOT / 'tmp/aria2' / digest
    work.mkdir(parents=True, exist_ok=True)
    target = work / 'weight.bin'
    partial = blob.with_suffix('.incomplete')
    started = time.monotonic()
    with FileLock(str(lock)):
        if not blob.exists():
            if partial.exists() and not target.exists():
                partial.rename(target)
            print(f'Resuming {args.repo}/{args.filename}, expected bytes {meta.size}', flush=True)
            child_env = {k: v for k, v in os.environ.items() if k != 'HF_TOKEN'}
            command = [
                'aria2c', '--input-file=-', '--continue=true', '--split=8',
                '--max-connection-per-server=8', '--min-split-size=20M',
                '--file-allocation=none', '--max-tries=10', '--retry-wait=2',
                '--timeout=60', '--connect-timeout=20', '--auto-file-renaming=false',
                '--console-log-level=warn', '--summary-interval=10', '--download-result=hide',
                '--dir=' + str(work), '--out=weight.bin',
            ]
            proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
            if proxy:
                command.append('--all-proxy=' + proxy)
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, env=child_env)
            # With --input-file, out must be a per-URI option.
            process.stdin.write(meta.location + '\n  out=weight.bin\n')
            process.stdin.close()
            for line in process.stdout:
                # Signed CDN URLs must not be persisted in diagnostics.
                print(re.sub(r'https?://\S+', '<URL>', line.rstrip()), flush=True)
            result = process.wait()
            if result:
                raise RuntimeError(f'aria2 exit {result}; partial file retained at {target}')
            if target.stat().st_size != meta.size:
                raise ValueError('File size mismatch; file not added to Hub cache')
            with target.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != digest:
                raise ValueError('SHA256 mismatch; file not added to Hub cache')
            blob.parent.mkdir(parents=True, exist_ok=True)
            target.rename(blob)
            print(f'SHA256 verified, {time.monotonic()-started:.1f}s', flush=True)
    path = hf_hub_download(args.repo, args.filename, revision=args.revision,
                           endpoint=endpoint, token=token)
    print(path, flush=True)


if __name__ == '__main__':
    main()
