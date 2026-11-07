"""Download DINOv3/RMBG anonymously from ModelScope and verify every file."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
from urllib.parse import urlencode

import requests


# Cross-checked against the official HF metadata on 2026-10-12. Keeping these
# references here also permits a fresh download without a prior HF cache.
MODELS = {
    'dinov3': dict(repo='facebook/dinov3-vitl16-pretrain-lvd1689m',
                   revision='ea8dc2863c51be0a264bab82070e3e8836b02d51',
                   weight_sha256='dcb2e45127cccbf1601e5f42fef165eea275c8e5213197e8dcf3f48822718179',
                   files=['LICENSE.md', 'README.md', 'config.json', 'model.safetensors', 'preprocessor_config.json']),
    'rmbg': dict(repo='briaai/RMBG-2.0', revision='5df4c9c76d8170882c34f6986e848ee07fd0ba43',
                 weight_sha256='566ed80c3d95f87ada6864d4cbe2290a1c5eb1c7bb0b123e984f60f76b02c3a7',
                 files=['BiRefNet_config.py', 'README.md', 'birefnet.py', 'config.json',
                        'model.safetensors', 'preprocessor_config.json']),
}


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', help='Optional proxy for this task only')
    args = parser.parse_args()
    root = Path(os.environ['WT_WEIGHTS_ROOT'])
    output = root / 'modelscope'
    output.mkdir(parents=True, exist_ok=True)

    def session():
        client = requests.Session()
        client.trust_env = False  # Never use ambient credentials or proxies.
        if args.proxy:
            client.proxies = dict(http=args.proxy, https=args.proxy)
        return client

    records = {}
    for name in ('dinov3', 'rmbg'):
        ref = MODELS[name]
        repo = ref['repo']
        url = f'https://modelscope.cn/api/v1/models/{repo}/repo/files'
        with session() as client:
            response = client.get(url, params=dict(Revision='master', Recursive='true'), timeout=(15, 60))
            response.raise_for_status()
            entries = response.json()['Data']['Files']
        selected = set(ref['files'])
        files = [entry for entry in entries if entry['Path'] in selected]
        if {entry['Path'] for entry in files} != set(selected):
            raise ValueError(f'{repo}: incomplete model files')
        for entry in files:
            expected = ref['weight_sha256'] if entry['Path'] == 'model.safetensors' else None
            if expected and entry['Sha256'] != expected:
                raise ValueError(f'{repo}/{entry["Path"]}: differs from official HF weight hash')
        destination = output / repo
        destination.mkdir(parents=True, exist_ok=True)
        records[name] = dict(repo=repo, source='https://modelscope.cn', directory=str(destination),
                             hf_revision=ref['revision'], files=files, status='downloading')

    def download(item):
        name, entry = item
        record = records[name]
        target = Path(record['directory']) / entry['Path']
        if target.exists() and target.stat().st_size == entry['Size'] and sha256(target) == entry['Sha256']:
            print(f'{name}: verified cached {entry["Path"]}', flush=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.partial')
        query = urlencode(dict(Revision=entry['Revision'], FilePath=entry['Path']))
        url = f'https://modelscope.cn/api/v1/models/{record["repo"]}/repo?{query}'
        if entry['Size'] > 10_000_000 and shutil.which('aria2c'):
            command = ['aria2c', '--no-conf=true', '--input-file=-', '--continue=true',
                       '--split=8', '--max-connection-per-server=8', '--min-split-size=20M',
                       '--file-allocation=none', '--max-tries=5', '--retry-wait=2',
                       '--timeout=60', '--connect-timeout=15', '--auto-file-renaming=false',
                       '--console-log-level=warn', '--summary-interval=30', '--show-console-readout=false',
                       '--download-result=hide', '--dir=' + str(target.parent)]
            if args.proxy:
                command.append('--all-proxy=' + args.proxy)
            env = {k: v for k, v in os.environ.items() if 'proxy' not in k.lower()
                   and k not in ('HF_TOKEN', 'MODELSCOPE_API_TOKEN')}
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, env=env)
            proc.stdin.write(url + '\n  out=' + partial.name + '\n')
            proc.stdin.close()
            for line in proc.stdout:
                print(re.sub(r'https?://\S+', '<URL>', line.rstrip()), flush=True)
            if proc.wait():
                raise RuntimeError(f'aria2 failed for {name}/{entry["Path"]}; partial retained')
        else:
            with session() as client:
                with client.get(url, timeout=(15, 120), stream=True) as response:
                    response.raise_for_status()
                    with partial.open('wb') as stream:
                        for chunk in response.iter_content(4 * 1024 * 1024):
                            stream.write(chunk)
        if partial.stat().st_size != entry['Size'] or sha256(partial) != entry['Sha256']:
            raise ValueError(f'{name}/{entry["Path"]}: size or SHA256 mismatch')
        partial.replace(target)
        print(f'{name}: SHA256 verified {entry["Path"]}', flush=True)

    # Download small configuration/code files first, then the two weights in parallel.
    jobs = [(name, entry) for name, record in records.items() for entry in record['files']]
    jobs.sort(key=lambda item: item[1]['Size'])
    manifest = output / 'download-manifest.json'
    manifest.write_text(json.dumps(records, indent=2) + '\n')
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download, jobs))
    for record in records.values():
        record['status'] = 'verified'
        record['bytes'] = sum(entry['Size'] for entry in record['files'])
        record['matches_official_hf_weight_sha256'] = True
    manifest.write_text(json.dumps(records, indent=2) + '\n')
    print(manifest, flush=True)


if __name__ == '__main__':
    main()
