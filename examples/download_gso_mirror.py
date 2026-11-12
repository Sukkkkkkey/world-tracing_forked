"""Fetch individually verifiable original GSO ZIPs from a pinned public mirror."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time

from huggingface_hub import HfApi
import requests

from wt.experiment import atomic_json, file_digest

REPO = 'suvadityamuk/google-scanned-objects-raw'
REVISION = '6139aa33f6163a9f1c7352dd386760f40691ce0d'


def download(out, ids, workers=6):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    api = HfApi(token=False)
    files = [x for x in api.list_repo_tree(REPO, repo_type='dataset', revision=REVISION, recursive=True)
             if x.path.endswith('.zip')]
    expected = set(json.loads(Path(ids).read_text()))
    entries = [dict(path=x.path, size=x.size, sha256=x.lfs.sha256) for x in files if Path(x.path).stem in expected]
    found = {Path(x['path']).stem for x in entries}
    if found != expected:
        raise ValueError(f'Mirror is missing original assets: {sorted(expected-found)}')
    if len(entries) != 1030:
        raise ValueError(f'Expected 1030 raw asset ZIPs, got {len(entries)}; inspect before proceeding')
    atomic_json(out/'manifest.json',dict(repo=REPO, revision=REVISION, files=entries,
                original_ids_sha256=file_digest(Path(ids)), unselected_mirror_assets=sorted({Path(x.path).stem for x in files}-expected)))
    print(f'{len(entries)} archives; {sum(x["size"] for x in entries)/2**30:.2f} GiB',flush=True)
    def fetch(value):
        target = out/value['path']
        if target.exists() and target.stat().st_size == value['size'] and file_digest(target) == value['sha256']:
            return value['path']
        url=f'https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{value["path"]}?download=true'
        temporary=target.with_suffix('.zip.part')
        for attempt in range(5):
            try:
                with requests.get(url,stream=True,timeout=(20,60)) as response:
                    response.raise_for_status()
                    with temporary.open('wb') as stream:
                        for chunk in response.iter_content(2**20): stream.write(chunk)
                if temporary.stat().st_size != value['size'] or file_digest(temporary) != value['sha256']:
                    raise ValueError('Downloaded size/hash mismatch')
                temporary.replace(target)
                return value['path']
            except Exception:
                if attempt == 4: raise
                time.sleep(2**attempt)
    failures=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(fetch,value) for value in entries]
        for index, future in enumerate(as_completed(futures),1):
            try:
                name=future.result()
                print(f'{index}/{len(entries)} {name}: sha256 OK',flush=True)
            except Exception as error:
                failures.append(dict(path=entries[futures.index(future)]['path'],error=str(error)))
                print(f'{index}/{len(entries)} FAILED: {error}',flush=True)
            atomic_json(out/'progress.json',dict(finished=index,total=len(entries),failed=failures))
    if failures:
        raise RuntimeError(f'{len(failures)} archives failed; see progress.json and resume')
    atomic_json(out/'download.complete.json',dict(repo=REPO,revision=REVISION,archives=len(entries)))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--ids',type=Path,required=True,help='Original MegaPose valid + invalid asset ID union')
    args=parser.parse_args()
    download(args.out,args.ids,args.workers)
