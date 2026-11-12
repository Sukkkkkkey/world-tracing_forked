"""Install the pinned private GCC runtimes required by image-built CUDA extensions."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request

root = Path(__file__).resolve().parents[1]
prefix = root / '.venv'
if Path(sys.prefix).resolve() != prefix.resolve():
    raise RuntimeError('Run with the project .venv Python')
kind, version = platform.libc_ver()
if kind != 'glibc' or tuple(map(int, version.split('.')[:2])) < (2, 28):
    raise RuntimeError('Pinned runtime requires glibc >= 2.28')
lock = json.loads((root / 'configs/conda_runtime.lock.json').read_text())
installed = {x['name']: x for x in (json.loads(p.read_text()) for p in (prefix / 'conda-meta').glob('*.json'))}
ready = all(installed.get(x['name'], {}).get('version') == x['version'] and
            installed.get(x['name'], {}).get('build') == x['build'] for x in lock['packages'])
if not ready:
    cache = root / '.runtime/downloads/conda-runtime'
    cache.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    paths = []
    for item in lock['packages']:
        path = cache / item['filename']
        def valid():
            return path.is_file() and path.stat().st_size == item['size'] and hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
        if not valid():
            assert item['url'].startswith('https://repo.anaconda.com/pkgs/main/linux-64/')
            assert item['size'] < 5 * 10**9
            print('DOWNLOAD', item['url'], item['size'], flush=True)
            partial = path.with_suffix(path.suffix + '.partial')
            with opener.open(item['url'], timeout=60) as src, partial.open('wb') as dst:
                while block := src.read(1024 * 1024):
                    dst.write(block)
            assert partial.stat().st_size == item['size']
            assert hashlib.sha256(partial.read_bytes()).hexdigest() == item['sha256']
            partial.replace(path)
        assert valid()
        paths.append(str(path))
    subprocess.run([str(prefix / 'bin/conda'), 'install', '--prefix', str(prefix), '--offline',
        '--solver', 'classic', '--yes', '--no-deps', *paths], check=True)
installed = {x['name']: x for x in (json.loads(p.read_text()) for p in (prefix / 'conda-meta').glob('*.json'))}
assert all(installed[x['name']]['version'] == x['version'] and
           installed[x['name']]['build'] == x['build'] for x in lock['packages'])
library = (prefix / 'lib/libstdc++.so.6').resolve()
assert b'GLIBCXX_3.4.30' in library.read_bytes()
report = dict(status='passed', prefix=str(prefix), packages=lock['packages'],
    libstdcxx=str(library), libstdcxx_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
    glibc=version, lock_sha256=hashlib.sha256((root / 'configs/conda_runtime.lock.json').read_bytes()).hexdigest())
out = root / '.runtime/logs/recovery-20261105/cpp-runtime.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2) + '\n')
subprocess.run([str(prefix / 'bin/conda'), 'list', '--prefix', str(prefix), '--explicit'],
    check=True, stdout=(root / 'conda-linux-64.lock').open('w'))
# Export official URLs rather than machine-local archive locations.
explicit = root / 'conda-linux-64.lock'
lines = explicit.read_text().splitlines()
for i, line in enumerate(lines):
    for item in lock['packages']:
        if line.split('#', 1)[0].endswith('/' + item['filename']):
            lines[i] = item['url']
explicit.write_text(chr(10).join(lines) + chr(10))
print('Pinned C++ runtime installed and symbol compatibility checked.', flush=True)
