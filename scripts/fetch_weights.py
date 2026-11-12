"""Inspect/download inference weights; tokens are read only from the environment."""
import argparse
import json
import os
from pathlib import Path
import time
import logging
from concurrent.futures import ThreadPoolExecutor

from huggingface_hub import HfApi, hf_hub_download
from requests.exceptions import ChunkedEncodingError, ConnectionError, Timeout

REPOS = {
    'object': 'haoz19/object-model-6layer',
    'trellis2': 'microsoft/TRELLIS.2-4B',
    'structure_decoder': 'microsoft/TRELLIS-image-large',
    'dinov3': 'facebook/dinov3-vitl16-pretrain-lvd1689m',
    'rmbg': 'briaai/RMBG-2.0',
}


REVISIONS = {
    'object': 'e9da924a0e00bb46569cc5e351bddb9d020b927f',
    'trellis2': 'af44b45f2e35a493886929c6d786e563ec68364d',
    'structure_decoder': '25e0d31ffbebe4b5a97464dd851910efc3002d96',
    'dinov3': 'ea8dc2863c51be0a264bab82070e3e8836b02d51',
    'rmbg': '5df4c9c76d8170882c34f6986e848ee07fd0ba43',
}

def selected(name, filename):
    if name == 'object':
        return filename in ('model.pt', 'README.md')
    if name == 'structure_decoder':
        return filename.startswith('ckpts/ss_dec_conv3d_16l8_fp16.') or filename == 'README.md'
    if filename.startswith('.'):
        return False
    # These repositories also carry ONNX/examples that inference does not use.
    return filename.endswith(('.json', '.safetensors', '.pt', '.py', '.md', '.txt'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inspect', action='store_true')
    p.add_argument('--manifest', type=Path, help='Separate manifest for concurrent independent download jobs')
    p.add_argument('--public', action='store_true', help='Never send a token, including implicit cached tokens')
    p.add_argument('--download-endpoint', help='Override file endpoint if the mirror only redirects')
    p.add_argument('--workers', type=int, default=3)
    p.add_argument('--models', nargs='+', choices=REPOS, required=True)
    args = p.parse_args()
    logging.getLogger('huggingface_hub').setLevel(logging.CRITICAL)
    endpoint = os.environ.get('HF_ENDPOINT', 'https://huggingface.co')
    download_endpoint = args.download_endpoint or endpoint
    root = Path(os.environ['WT_WEIGHTS_ROOT'])
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or root / 'download-manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    token = False if args.public else os.environ.get('HF_TOKEN', False)
    token_file = Path(__file__).resolve().parents[1] / '.runtime/hf_token'
    if not args.public and not token and token_file.is_file():
        token = token_file.read_text().strip()
    if token and (endpoint != 'https://huggingface.co' or download_endpoint != 'https://huggingface.co'):
        raise ValueError('Authenticated downloads are restricted to the official Hugging Face endpoint')
    api = HfApi(endpoint=endpoint, token=token)
    for name in args.models:
        repo = REPOS[name]
        record = dict(repo=repo, endpoint=download_endpoint, metadata_endpoint=endpoint, status='inspecting')
        manifest[name] = record
        try:
            for attempt in range(6):
                try:
                    info = api.model_info(repo, revision=REVISIONS[name], files_metadata=True)
                    break
                except (ConnectionError, Timeout):
                    if attempt == 5:
                        raise
                    time.sleep(min(2 ** (attempt + 1), 30))
            files = [s for s in info.siblings if selected(name, s.rfilename)]
            record.update(revision=info.sha, gated=info.gated,
                          bytes=sum(s.size or 0 for s in files),
                          files=[dict(name=s.rfilename, bytes=s.size,
                                      sha256=getattr(s.lfs, 'sha256', None), blob_id=s.blob_id) for s in files])
            print(json.dumps(dict(model=name, revision=info.sha, gated=info.gated,
                                  gb=round(record['bytes']/1e9, 3), files=len(files))), flush=True)
            if not args.inspect:
                def download(file):
                    started = time.monotonic()
                    for attempt in range(5):
                        try:
                            path = hf_hub_download(repo, file['name'], revision=info.sha,
                                                   endpoint=download_endpoint, token=token)
                            break
                        except (ChunkedEncodingError, ConnectionError, Timeout) as exc:
                            if attempt == 4:
                                raise
                            print(f"{name}: resume {file['name']} after {type(exc).__name__}", flush=True)
                            time.sleep(2)
                    print(f"{name}: downloaded {file['name']} ({time.monotonic()-started:.1f}s)", flush=True)
                    return path
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    paths = list(pool.map(download, record['files']))
                snapshot = Path(paths[0]) if paths else None
                if snapshot:
                    for _ in Path(record['files'][0]['name']).parts:
                        snapshot = snapshot.parent
                record.update(status='downloaded', snapshot=str(snapshot) if snapshot else None,
                              local_files=paths)
            else:
                record['status'] = 'metadata_available'
        except Exception as exc:
            # Avoid logging headers, bearer tokens or signed download URLs.
            record.update(status='failed', error=type(exc).__name__,
                          http_status=getattr(getattr(exc, 'response', None), 'status_code', None))
            print(json.dumps(dict(model=name, status=record['status'], error=record['error'],
                                  http_status=record['http_status'])), flush=True)
        # Inspection must not replace pinned download records (including
        # snapshot paths consumed by prepare_trellis2_local.py).
        if not args.inspect:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    raise SystemExit(any(manifest[name]['status'] == 'failed' for name in args.models))


if __name__ == '__main__':
    main()
