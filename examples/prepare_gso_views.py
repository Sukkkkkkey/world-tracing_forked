"""Render frozen GSO IDs with stored cameras, exact WT crop K, and independent GT samples."""
import argparse
import json
from pathlib import Path

import numpy as np
from wt.artifacts import save_npz
from PIL import Image
import trimesh

from examples.prepare_gso_inventory import asset_seed
from examples.verify_gso_raw import require_complete
from evaluation.geometry import surface_points
from evaluation.render import Rasterizer, load_mesh_parts, make_camera, normalize_parts
from wt.data import compute_object_crop
from wt.experiment import atomic_json, digest, file_digest, identifier
from wt.paths import DATA_ROOT


def prepare(dataset, split_name, asset_up, *, dataset_name="gso-v1", render_protocol="gso-render-v1"):
    dataset = Path(dataset)
    inventory = {x['asset_id']: x for x in map(json.loads, (dataset/'inventory.jsonl').read_text().splitlines())}
    split = json.loads((dataset/'split.json').read_text())
    source = Path(__file__).resolve().parents[1]
    config = dict(protocol=render_protocol, asset_up=asset_up, normalization='asset-AABB-diagonal=1',
                  resolution=1024, eval_resolution=504, horizontal_fov=40., elevation=20.,
                  sphere_radius=.5, distance_margin=1.2, lighting='unit ambient, texture sRGB unchanged',
                  alpha='opaque center sample, no AA', depth='linear camera Z', faces='double-sided',
                  numpy=np.__version__, split_sha256=file_digest(dataset/'split.json'),
                  source_sha256={str(p.relative_to(source)):file_digest(p) for p in [Path(__file__), source/'evaluation/render.py', source/'evaluation/geometry.py', source/'wt/data.py', source/'wt/artifacts.py']})
    config_hash = digest(config)
    renderer = Rasterizer()
    manifest = []
    for asset_id in split['splits'][split_name]:
        identifier(asset_id)
        dest = dataset/'samples'/asset_id
        entry = dest/'input.json'
        if entry.exists():
            value = json.loads(entry.read_text())
            if value['render_config_hash'] != config_hash:
                raise ValueError('Rendering configuration changed; create a new dataset version')
            for name, sha in value['artifact_sha256'].items():
                if file_digest(dest/name) != sha:
                    raise ValueError(f'Frozen artifact changed: {dest/name}')
            manifest.append(value)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        asset = inventory[asset_id]
        parts, transform, diagonal = normalize_parts(load_mesh_parts(asset['mesh']), asset_up)
        view_seed = asset_seed('view', asset_id)
        azimuth = float(np.random.Generator(np.random.PCG64(view_seed)).uniform(0, 360))
        camera = make_camera(azimuth)
        K, T = np.asarray(camera['K']), np.asarray(camera['T_world_to_camera'])
        rgba, depth, mask, normals = renderer.render(parts, K, T, 1024)
        if not mask.any() or mask[0].any() or mask[-1].any() or mask[:,0].any() or mask[:,-1].any():
            raise ValueError(f'Empty or clipped input view: {asset_id}')
        Image.fromarray(rgba).save(dest/'input.png')
        save_npz(dest/'gt_depth_original.npz', depth=depth, mask=mask)
        y1, x1, side = compute_object_crop(rgba)
        K_crop = K.copy()
        K_crop[0,2] -= x1; K_crop[1,2] -= y1
        K_crop[:2] *= 504/side
        _, depth_crop, mask_crop, normals_crop = renderer.render(parts, K_crop, T, 504, texture=False)
        save_npz(dest/'gt_depth.npz', depth=depth_crop, mask=mask_crop, K=K_crop, normals=normals_crop)
        mesh = trimesh.util.concatenate([trimesh.Trimesh(m.vertices, m.faces, process=False) for m in parts])
        mesh.export(dest/'gt_world.ply')
        camera_mesh = mesh.copy(); camera_mesh.apply_transform(T); camera_mesh.export(dest/'gt_camera.ply')
        reg_seed, eval_seed = asset_seed('gt_reg',asset_id), asset_seed('gt_eval',asset_id)
        save_npz(dest/'gt_points.npz', registration=surface_points(mesh,10000,reg_seed),
                            evaluation=surface_points(mesh,100000,eval_seed))
        atomic_json(dest/'camera.json', dict(camera, K_crop=K_crop.tolist(), crop_y_x_side=[y1,x1,side],
                    T_asset_to_world=transform.tolist(), source_diagonal=diagonal,
                    source_units=asset.get('source_units','unknown'), experimental_diagonal=1.,
                    view_seed=view_seed, gt_registration_seed=reg_seed, gt_evaluation_seed=eval_seed))
        atomic_json(dest/'render_config.json', config)
        files = ['input.png','gt_depth_original.npz','gt_depth.npz','gt_world.ply','gt_camera.ply','gt_points.npz','camera.json','render_config.json']
        value = dict(sample_id=asset_id, asset_id=asset_id, image=str((dest/'input.png').resolve()), split=split_name,
                     dataset=dataset_name, ground_truth=dict(path=str((dest/'gt_camera.ply').resolve()), kind='mesh',frame='camera_rdf'),
                     evaluation_dir=str(dest.resolve()), render_config_hash=config_hash,
                     artifact_sha256={name:file_digest(dest/name) for name in files})
        for key in ("category", "source_mesh_sha256"):
            if key in asset:
                value[key] = asset[key]
        if "archive_sha256" in asset:
            value["source_archive_sha256"] = asset["archive_sha256"]
        atomic_json(entry,value)
        manifest.append(value)
        print(f'{split_name} {len(manifest)} {asset_id}: rendered',flush=True)
    output = dataset/f'{split_name}.jsonl'
    output.write_text(''.join(json.dumps(x)+'\n' for x in manifest))
    atomic_json(dataset/f'{split_name}.manifest.json',dict(sha256=file_digest(output),config_hash=config_hash, samples=len(manifest)))
    return output


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--split',choices=['pilot','eval100'],required=True)
    parser.add_argument('--asset-up',choices=['y','z'],required=True)
    parser.add_argument('--raw-root',type=Path,default=DATA_ROOT/'raw/gso')
    args=parser.parse_args()
    require_complete(args.raw_root)
    print(prepare(args.dataset,args.split,args.asset_up))
