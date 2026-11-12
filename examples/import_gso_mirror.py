"""Make derived material-compatible copies only after complete raw GSO verification."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
from pathlib import Path
import shutil
import zlib

import numpy as np
from PIL import Image

from examples.prepare_gso_inventory import build_inventory
from examples.verify_gso_raw import require_complete
from wt.experiment import atomic_json, file_digest


def import_assets(source, partial_entries, original_zip, output, dataset, workers=8):
    source, output, dataset = Path(source), Path(output), Path(dataset)
    raw_marker=require_complete(source.parent)
    manifest=json.loads((source/'manifest.json').read_text())
    if (partial_entries is None) != (original_zip is None):
        raise ValueError('Original archive and partial entries must be supplied together')
    original={x['name']:x for x in json.loads(Path(partial_entries).read_text())} if partial_entries else {}
    output.mkdir(parents=True,exist_ok=True)
    if (dataset/'split.json').exists(): raise FileExistsError('Dataset is already frozen')
    if 'raw' in output.resolve().parts: raise ValueError('Derived output must not be under raw')
    if shutil.disk_usage(output).free < 40*2**30: raise OSError('Insufficient space for derived copies and headroom')
    def import_one(file):
        asset=Path(file['path']).stem
        dest=output/'models_orig'/asset
        origin=source.parent/'objects'/asset
        record_path=output/'import_records'/f'{asset}.json'
        if record_path.exists():
            record=json.loads(record_path.read_text())
            if record['archive_sha256']==file['sha256'] and all(file_digest(dest/name)==sha for name,sha in record['derived_sha256'].items()):
                return record['comparison']
        shutil.copytree(origin,dest,dirs_exist_ok=True)
        # Add a lossless RGB texture beside model.mtl in the derived copy only.
        with Image.open(origin/'materials/textures/texture.png') as image:
            texture=image.convert('RGB')
        texture.save(dest/'meshes/texture.png',compress_level=1)
        prefix=f'google_scanned_objects/models_orig/{asset}/'
        mesh_entry=original.get(prefix+'meshes/model.obj')
        texture_entry=original.get(prefix+'meshes/texture.png')
        match=dict(asset_id=asset,mesh_compared=mesh_entry is not None,texture_compared=texture_entry is not None)
        from contextlib import nullcontext
        with (Path(original_zip).open('rb') if original_zip else nullcontext()) as orig:
            def read_original(entry):
                orig.seek(entry['data_offset']);data=orig.read(entry['compressed'])
                if entry['method']==8:data=zlib.decompress(data,-15)
                if zlib.crc32(data)&0xffffffff!=entry['crc']:raise ValueError('Original member CRC mismatch')
                return data
            if mesh_entry:
                if read_original(mesh_entry)!=(dest/'meshes/model.obj').read_bytes():raise ValueError(f'Original/mirror mesh differs: {asset}')
                match['mesh_identical']=True
            if texture_entry:
                image=Image.open(io.BytesIO(read_original(texture_entry))).convert('RGB')
                if not np.array_equal(np.asarray(image),np.asarray(texture)):raise ValueError(f'Original/mirror texture pixels differ: {asset}')
                match['texture_rgb_identical']=True
        atomic_json(record_path,dict(archive_sha256=file['sha256'],comparison=match,
                    derived_sha256={name:file_digest(dest/name) for name in ['meshes/model.obj','meshes/model.mtl','meshes/texture.png']}))
        return match
    comparisons=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(import_one,item) for item in manifest['files']]
        for future in as_completed(futures):
            result=future.result();comparisons.append(result)
            print(f'{len(comparisons)}/1030 {result["asset_id"]}: copied, compared where original available',flush=True)
    comparisons.sort(key=lambda x:x['asset_id'])
    atomic_json(output/'mirror-comparison.json',dict(assets=comparisons,original_zip=str(original_zip) if original_zip else None,
                original_catalog_sha256=manifest['original_ids_sha256'],matched_meshes=sum(x['mesh_compared'] for x in comparisons),
                matched_textures=sum(x['texture_compared'] for x in comparisons)))
    atomic_json(output/'archive.json',dict(source='MegaPose 1030 asset IDs + pinned Google raw ZIP mirror',
                raw_complete_path=str(raw_marker),raw_complete_sha256=file_digest(raw_marker),
                mirror_manifest=manifest,manifest_sha256=file_digest(source/'manifest.json'),
                comparison_sha256=file_digest(output/'mirror-comparison.json'),
                note='Raw archives are verified against the pinned mirror SHA-256. Original archive member comparisons are performed only when reference bytes are available; absent comparisons are not claimed.',
                preparer_sha256=file_digest(Path(__file__))))
    return build_inventory(output,dataset)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['source','out','dataset']:p.add_argument('--'+key,type=Path,required=True)
    for key in ['partial-entries','original-zip']:p.add_argument('--'+key,type=Path)
    p.add_argument('--workers',type=int,default=8)
    args=p.parse_args()
    import_assets(args.source,args.partial_entries,args.original_zip,args.out,args.dataset,args.workers)
