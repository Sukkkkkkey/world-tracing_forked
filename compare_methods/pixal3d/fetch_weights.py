"""Download pinned public weights, verify bytes, then create local descriptors.

Run inside screen after sourcing env.sh. No credentials are sent to mirrors.
Existing TRELLIS weights are reused only after matching their SHA-256.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import errno
import shutil
import uuid
import time
from urllib.parse import urlencode

# Keep the downloader independent of WT/PyTorch environment initialization.
def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def verify(path, record):
    if not path.is_file() or path.stat().st_size != record['size']:
        return False
    if record.get('sha256'):
        return file_digest(path) == record['sha256']
    data = path.read_bytes()
    return hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest() == record['blob_id']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', default='https://huggingface.co')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--modelscope', action='store_true', help='Use checked ModelScope copies for Pixal3D files')
    args = parser.parse_args()
    if not (os.environ.get('STY') or os.environ.get('TMUX')):
        raise RuntimeError('Run in a dedicated screen/tmux session')
    lock = json.loads(Path(__file__).with_name('weights.lock.json').read_text())
    modelscope = json.loads(Path(__file__).with_name('modelscope.lock.json').read_text()) if args.modelscope else {}
    weights = Path(os.environ['WT_WEIGHTS_ROOT'])
    root = weights / 'pixal3d'
    root.mkdir(parents=True, exist_ok=True)
    # Previously downloaded blobs are immutable; link rather than duplicate them.
    candidates = {}
    old = json.loads((weights / 'download-manifest.json').read_text())
    for value in old.values():
        for item in value.get('files', []):
            if item.get('sha256') and value.get('snapshot'):
                candidates[item['sha256']] = Path(value['snapshot']) / item['name']
    aux = json.loads((weights / 'modelscope/download-manifest.json').read_text())
    for value in aux.values():
        for item in value['files']:
            candidates[item['Sha256']] = Path(value['directory']) / item['Path']

    def fetch(record):
        dest = root / record['path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not verify(dest, record):
            reuse = candidates.get(record.get('sha256'))
            if not reuse and record['path'].startswith('dinov3/'):
                auxiliary = Path(aux['dinov3']['directory']) / Path(record['path']).name
                if verify(auxiliary, record):
                    reuse = auxiliary
            if reuse and verify(reuse, record):
                if dest.exists() or dest.is_symlink():
                    raise ValueError(f'Refusing to replace existing invalid file: {dest}')
                try:
                    dest.symlink_to(reuse)
                except OSError as error:
                    if error.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS):
                        raise
                    partial = dest.with_name(dest.name + '.partial')
                    shutil.copyfile(reuse, partial)
                    if not verify(partial, record):
                        raise ValueError('Copied weight failed verification')
                    partial.replace(dest)
            else:
                url = record.get('url') or f"{args.endpoint}/{record['repo']}/resolve/{record['revision']}/{record['filename']}"
                proxy_args = []
                if url.startswith("https://hf-mirror.com/"):
                    url += "?download=true&recovery=" + str(time.time_ns())
                    proxy_args = ["--noproxy", "*"]
                if record['path'] in modelscope:
                    mirror = modelscope[record['path']]
                    if mirror['size'] != record['size'] or (record.get('sha256') and mirror['sha256'] != record['sha256']):
                        raise ValueError('ModelScope lock differs from official weight: ' + record['path'])
                    query = urlencode(dict(Revision=mirror['revision'], FilePath=record['filename']))
                    url = f"https://modelscope.cn/api/v1/models/{record['repo']}/repo?{query}"
                    proxy_args = ['--noproxy', '*']
                partial = dest.with_name(dest.name + '.partial')
                subprocess.run(['curl', '--disable', *proxy_args, '-fL', '--retry', '5', '--retry-all-errors',
                                '--retry-delay', '5', '--connect-timeout', '30', '--speed-time', '90',
                                '--speed-limit', '1024', '-C', '-', '-o', str(partial), url], check=True)
                if not verify(partial, record):
                    raise ValueError(f'Checksum mismatch: {record["path"]}')
                partial.replace(dest)
        print('verified', record['path'], flush=True)
        return dict(record, local_path=str(dest), status='verified', modelscope=modelscope.get(record['path']))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        files = list(pool.map(fetch, lock['files']))
    config = json.loads((root / 'model/pipeline.json').read_text())
    for name, reference in config['args']['models'].items():
        local = root / 'model' / reference
        for suffix in ('.json', '.safetensors'):
            if not Path(str(local) + suffix).is_file():
                raise FileNotFoundError(local)
        config['args']['models'][name] = str(local)
    # Preserve the already verified RMBG model and custom code used by TRELLIS.
    for item in aux['rmbg']['files']:
        if file_digest(Path(aux['rmbg']['directory']) / item['Path']) != item['Sha256']:
            raise ValueError('Existing RMBG checksum mismatch')
    config['args']['rembg_model']['args']['model_name'] = aux['rmbg']['directory']
    atomic_json(root / 'pipeline/pipeline.json', config)
    manifest = dict(status='verified', files=files, rmbg=aux['rmbg'],
                    pipeline=str(root / 'pipeline'), dinov3=str(root / 'dinov3'),
                    moge=str(root / 'moge/model.pt'), naf=str(root / 'naf/naf_release.pth'))
    atomic_json(root / 'manifest.json', manifest)
    print('All weights verified:', root / 'manifest.json', flush=True)


if __name__ == '__main__':
    main()
