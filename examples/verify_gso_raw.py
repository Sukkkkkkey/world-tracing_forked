"""Verify and unpack every original GSO archive; publish COMPLETE only after all 1030 pass."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

from wt.experiment import atomic_json, file_digest


def require_complete(root):
    root=Path(root).resolve()
    marker=root/'COMPLETE.json'
    if not marker.is_file():
        raise RuntimeError(f'GSO raw data is incomplete: {marker} is required before experiments')
    value=json.loads(marker.read_text())
    if value.get('status')!='complete' or value.get('assets')!=1030:
        raise ValueError('Invalid GSO completeness marker')
    for name,key in [('canonical_ids.json','canonical_ids_sha256'),('archives/manifest.json','mirror_manifest_sha256')]:
        if file_digest(root/name)!=value[key]:raise ValueError(f'GSO manifest changed: {name}')
    ids=json.loads((root/'canonical_ids.json').read_text())
    if len(ids)!=1030 or len(set(ids))!=1030:raise ValueError('Invalid original asset ID list')
    for asset in ids:
        if not (root/'archives'/f'{asset}.zip').is_file() or not (root/'objects'/asset/'meshes/model.obj').is_file():
            raise FileNotFoundError(f'Previously verified raw asset is missing: {asset}')
    return marker


def verify(root):
    root=Path(root).resolve()
    ids=json.loads((root/'canonical_ids.json').read_text())
    manifest=json.loads((root/'archives/manifest.json').read_text())
    files=manifest['files']
    if len(ids)!=1030 or {Path(x['path']).stem for x in files}!=set(ids) or len(files)!=1030:
        raise ValueError('Raw archive manifest must exactly match all 1030 original asset IDs')
    required={'meshes/model.obj','meshes/model.mtl','materials/textures/texture.png','metadata.pbtxt','model.sdf','model.config'}
    records=[]
    for index,item in enumerate(files,1):
        asset=Path(item['path']).stem
        archive=root/'archives'/item['path']
        if archive.stat().st_size!=item['size'] or file_digest(archive)!=item['sha256']:
            raise ValueError(f'Archive size/hash mismatch: {asset}')
        dest=root/'objects'/asset
        record_path=root/'integrity'/f'{asset}.json'
        with zipfile.ZipFile(archive) as zf:
            members=zf.infolist()
            names={x.filename for x in members if not x.is_dir()}
            if not required<=names:raise ValueError(f'Missing required raw members for {asset}: {required-names}')
            if dest.exists():
                if not record_path.exists():raise ValueError(f'Unrecorded existing raw directory: {dest}')
                record=json.loads(record_path.read_text())
                if record['archive_sha256']!=item['sha256'] or set(record['files'])!=names:
                    raise ValueError(f'Existing raw record differs: {asset}')
                for name,sha in record['files'].items():
                    if file_digest(dest/name)!=sha:raise ValueError(f'Existing raw file changed: {asset}/{name}')
            else:
                temporary=root/'objects'/f'.{asset}.partial'
                temporary.mkdir(parents=True,exist_ok=True)
                needed=sum(x.file_size for x in members)
                if shutil.disk_usage(root).free<needed+20*2**30:raise OSError('Insufficient data disk headroom')
                hashes={}
                for member in members:
                    path=PurePosixPath(member.filename)
                    if path.is_absolute() or '..' in path.parts or stat.S_ISLNK(member.external_attr>>16):
                        raise ValueError(f'Unsafe archive entry: {member.filename}')
                    target=temporary/member.filename
                    if member.is_dir():target.mkdir(parents=True,exist_ok=True);continue
                    target.parent.mkdir(parents=True,exist_ok=True)
                    # Reading a complete member verifies its CRC. Bytes are copied unchanged.
                    with zf.open(member) as source,target.open('wb') as output:shutil.copyfileobj(source,output,2**20)
                    hashes[member.filename]=file_digest(target)
                record=dict(asset_id=asset,archive_sha256=item['sha256'],files=hashes)
                atomic_json(record_path,record)
                temporary.rename(dest)
        records.append(dict(asset_id=asset,archive_sha256=item['sha256'],integrity_sha256=file_digest(record_path)))
        print(f'{index}/1030 {asset}: archive SHA-256, member CRC and raw files OK',flush=True)
    atomic_json(root/'COMPLETE.json',dict(status='complete',assets=1030,source=json.loads((root/'SOURCE.json').read_text()),
                canonical_ids_sha256=file_digest(root/'canonical_ids.json'),mirror_manifest_sha256=file_digest(root/'archives/manifest.json'),
                verifier_sha256=file_digest(Path(__file__)),archives_bytes=sum(x['size'] for x in files),records=records,
                rule='All original IDs present; all archive hashes and extracted member CRCs verified. No geometry, texture or metadata modifications.'))
    print('GSO RAW COMPLETE:',root,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True,type=Path)
    verify(p.parse_args().root)
