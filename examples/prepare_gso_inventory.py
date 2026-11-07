"""Safely extract GSO models_orig, validate inputs, and freeze a reproducible asset split."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

import numpy as np
from PIL import Image
import trimesh

from wt.experiment import atomic_json, file_digest


def asset_seed(purpose, asset_id):
    return int(hashlib.sha256(f'20261013|{purpose}|{asset_id}'.encode()).hexdigest()[:8], 16)


def split_ids(ids):
    ids = sorted(ids)
    if len(ids) != len(set(ids)) or len(ids) < 110:
        raise ValueError('Need at least 110 unique valid assets')
    order = np.random.Generator(np.random.PCG64(20261013)).permutation(ids).tolist()
    return dict(pilot=order[:10], eval100=order[10:110], reserve=order[110:])


def prepare(archive, output, split_output):
    archive, output, split_output = map(Path, (archive, output, split_output))
    if (split_output / 'split.json').exists():
        raise FileExistsError('Split is already frozen; do not overwrite it')
    # Never extract into existing raw data. This is a project-owned derived copy.
    if 'raw' in output.resolve().parts or 'raw' in split_output.resolve().parts:
        raise ValueError('Raw data directories are read-only')
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        members = []
        for info in zf.infolist():
            parts = PurePosixPath(info.filename).parts
            if 'models_orig' not in parts:
                continue
            if '..' in parts or info.filename.startswith('/') or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f'Unsafe archive entry: {info.filename}')
            members.append(info)
        if not members:
            raise ValueError('Archive has no models_orig: inspect the source layout before proceeding')
        needed = sum(x.file_size for x in members if not x.is_dir())
        if shutil.disk_usage(output).free < needed + 20 * 2**30:
            raise OSError(f'Insufficient disk space for {needed} extracted bytes plus 20 GiB headroom')
        atomic_json(output / 'archive.json', dict(path=str(archive.resolve()), sha256=file_digest(archive),
                    compressed_bytes=archive.stat().st_size, selected_bytes=needed,
                    selected_members=len(members), source='MegaPose GSO models_orig',
                    preparer_sha256=file_digest(Path(__file__)), numpy=np.__version__, trimesh=trimesh.__version__))
        shutil.copyfile(Path(__file__), output / 'prepare_gso_inventory.py')
        for info in members:
            target = output / info.filename
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # zipfile verifies each extracted member's CRC at end-of-stream.
            with zf.open(info) as source, target.open('wb') as dest:
                shutil.copyfileobj(source, dest, length=2**20)
    return build_inventory(output, split_output)


def build_inventory(output, split_output):
    output, split_output = Path(output), Path(split_output)
    if (split_output/'split.json').exists():
        raise FileExistsError('Split already frozen; refusing to overwrite')
    inventory, seen = [], set()
    for mesh_path in sorted(output.rglob('*.obj')):
        parts = mesh_path.relative_to(output).parts
        if 'models_orig' not in parts:
            continue
        index = parts.index('models_orig')
        asset_id = parts[index + 1]
        if asset_id in seen:
            raise ValueError(f'Multiple OBJ meshes for asset {asset_id}; inspect before defining asset identity')
        seen.add(asset_id)
        asset_dir = output.joinpath(*parts[:index + 2])
        value = dict(asset_id=asset_id, mesh=str(mesh_path.resolve()), valid=False,
                     view_seed=asset_seed('view', asset_id), source_units='unknown', source_up_axis='unknown')
        try:
            files = sorted(p for p in asset_dir.rglob('*') if p.is_file())
            value['files'] = {str(p.relative_to(asset_dir)): file_digest(p) for p in files}
            for p in files:
                if p.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    with Image.open(p) as image:
                        image.verify()
                elif p.suffix.lower() == '.mtl':
                    for line in p.read_text(errors='replace').splitlines():
                        if line.strip().startswith('map_Kd '):
                            texture = p.parent / line.strip().split(maxsplit=1)[1]
                            if not texture.is_file():
                                raise ValueError(f'Missing or unsupported texture reference: {line}')
            scene = trimesh.load(mesh_path, force='scene', process=False)
            geometries = list(scene.geometry.values())
            if not geometries:
                raise ValueError('Empty scene')
            for mesh in geometries:
                if not len(mesh.vertices) or not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
                    raise ValueError('Empty or non-finite geometry')
                if mesh.faces.min() < 0 or mesh.faces.max() >= len(mesh.vertices) or mesh.area <= 0:
                    raise ValueError('Invalid faces / zero surface area')
            value.update(valid=True, vertices=sum(len(m.vertices) for m in geometries),
                         faces=sum(len(m.faces) for m in geometries))
        except Exception as error:
            value['error'] = f'{type(error).__name__}: {error}'
        inventory.append(value)
        print(f'{len(inventory)} {asset_id}: {"valid" if value["valid"] else value["error"]}', flush=True)
    split_output.mkdir(parents=True, exist_ok=True)
    inventory_path = split_output / 'inventory.jsonl'
    inventory_path.write_text(''.join(json.dumps(x, sort_keys=True) + '\n' for x in inventory))
    valid = [x['asset_id'] for x in inventory if x['valid']]
    split = dict(seed=20261013, algorithm='numpy.PCG64', numpy=np.__version__,
                 inventory_sha256=file_digest(inventory_path), archive=read_archive(output),
                 total=len(inventory), valid=len(valid), excluded=len(inventory)-len(valid),
                 splits=split_ids(valid))
    atomic_json(split_output / 'split.json', split)
    atomic_json(split_output / 'split.sha256.json', dict(sha256=file_digest(split_output / 'split.json')))
    return split


def read_archive(output):
    return json.loads((output / 'archive.json').read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--split-out', required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.archive, args.out, args.split_out)
    print(json.dumps({k: result[k] for k in ('total', 'valid', 'excluded')}))
