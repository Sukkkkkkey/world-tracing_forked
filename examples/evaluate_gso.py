"""Evaluate completed GSO runs under project-defined shape/camera/depth protocols."""
import argparse
import json
from pathlib import Path
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

import numpy as np
from wt.artifacts import save_npz
import trimesh

from examples.prepare_gso_inventory import asset_seed
from examples.verify_gso_raw import require_complete
from wt.paths import DATA_ROOT
from evaluation.geometry import chamfer, depth_metrics, register_sim3, surface_points, transform_points
from evaluation.render import Rasterizer
from wt.experiment import CAMERA_NA, METHODS, atomic_json, digest, file_digest
from wt.textured_mesh.canon import CanonicalTransform, canon_inverse


def evaluate_run(directory, renderer=None):
    directory = Path(directory)
    state = json.loads((directory/'run.json').read_text())
    if state['method'] in CAMERA_NA and (directory/'wt_parent.json').exists():
        raise ValueError('Invalid independent baseline: unexpected WT parent')
    sample = json.loads((directory.parents[2]/'input.json').read_text())
    dataset = Path(sample['evaluation_dir'])
    camera = json.loads((dataset/'camera.json').read_text())
    asset_id = sample['asset_id']
    seeds = {purpose:asset_seed(purpose,asset_id) for purpose in ('pred_reg','pred_eval')}
    with np.load(dataset/'gt_points.npz') as data:
        gt_reg, gt_eval = data['registration'], data['evaluation']
    method = state['method']
    mesh = None
    if method == 'wt':
        with np.load(directory/'prediction.npz') as data:
            xyz, valid = data['xyz'], data['mask']
        points = xyz[valid]
        points = np.unique(points[np.isfinite(points).all(-1)],axis=0)
        if not len(points): raise ValueError('WT returned no finite valid points')
        def draw(n, seed):
            rng=np.random.Generator(np.random.PCG64(seed))
            return points[rng.choice(len(points),min(n,len(points)),replace=False)]
        pred_reg, pred_eval = draw(10000,seeds['pred_reg']),draw(100000,seeds['pred_eval'])
        camera_pred = pred_eval
        pred_depth, pred_mask = xyz[0,...,2], valid[0]
    else:
        mesh=trimesh.load(directory/'decoded_mesh.ply',process=False)
        pred_reg=surface_points(mesh,10000,seeds['pred_reg'])
        pred_eval=surface_points(mesh,100000,seeds['pred_eval'])
        camera_pred=None
        if method == 'wt_trellis2':
            tf=CanonicalTransform(**json.loads((directory/'mesh.json').read_text())['canonical_transform'])
            camera_pred=canon_inverse(pred_eval,tf)
            camera_mesh=mesh.copy()
            camera_mesh.vertices=canon_inverse(np.asarray(mesh.vertices),tf)
            if renderer is None: renderer=Rasterizer()
            _, pred_depth, pred_mask, _=renderer.render([camera_mesh],camera['K_crop'],np.eye(4),504,texture=False)
    # Preserve actual sampled points so numerical results are recoverable without RNG replay.
    save_npz(directory/'evaluation_points.npz',registration=pred_reg,evaluation=pred_eval)
    aligned_matrix, registration=register_sim3(pred_reg,gt_reg[:len(pred_reg)])
    aligned=transform_points(pred_eval,aligned_matrix)
    metrics=[]
    def add(protocol, values, status='complete', reason=None):
        for key, value in values.items():
            unit='GT_diagonal_squared' if key=='cd_squared_mean' else (
                'ratio' if key.startswith(('f@','delta','depth_coverage','silhouette','absrel')) else 'GT_diagonal')
            metrics.append(dict(protocol_id=protocol,metric=key,value=value,unit=unit,status=status,reason=reason))
    add('gso-shape-sim3-v1',chamfer(aligned,gt_eval))
    atomic_json(directory/'registration.json',dict(matrix=aligned_matrix.tolist(),**registration))
    if camera_pred is not None:
        gt_camera=transform_points(gt_eval,np.asarray(camera['T_world_to_camera']))
        add('gso-camera-native-v1',chamfer(camera_pred,gt_camera))
        with np.load(dataset/'gt_depth.npz') as data:
            depth=depth_metrics(pred_depth,data['depth'],pred_mask,data['mask'])
        atomic_json(directory/'depth_fit.json',depth)
        add('gso-depth-ssi-v1',{k:depth[k] for k in ('depth_coverage','silhouette_iou')})
        add('gso-depth-ssi-v1',{k:depth.get(k) for k in ('mae','rmse','absrel','delta1','delta2')},
            status=depth['status'],reason=depth.get('reason'))
    else:
        for protocol,keys in [('gso-camera-native-v1',['cd_euclidean_mean','cd_squared_mean','f@0.01','f@0.05']),
                              ('gso-depth-ssi-v1',['mae','rmse','absrel','delta1','delta2','depth_coverage','silhouette_iou'])]:
            add(protocol,{k:None for k in keys},status='N/A',reason=CAMERA_NA[method])
    return dict(metrics=metrics,seeds=seeds,predicted_points=len(pred_eval),gt_points=len(gt_eval),
                source_run_hash=file_digest(directory/'run.json'), render_config_hash=sample['render_config_hash'])


def evaluate_one(path, version):
    """One process per run keeps a CUDA failure from corrupting later samples."""
    path=Path(path)
    state=json.loads(path.read_text())
    dest=path.parent/'metrics.json'
    try:
        value=evaluate_run(path.parent)
        atomic_json(dest,dict(value,evaluator_sha256=version,evaluation_status='complete'))
        (path.parent/'evaluation_error.json').unlink(missing_ok=True)
        return 'complete'
    except Exception:
        error=traceback.format_exc()
        atomic_json(path.parent/'evaluation_error.json',dict(evaluator_sha256=version,error=error))
        rows=[]
        for protocol, keys in [('gso-shape-sim3-v1',['cd_euclidean_mean','cd_squared_mean','f@0.01','f@0.05']),
                               ('gso-camera-native-v1',['cd_euclidean_mean','cd_squared_mean','f@0.01','f@0.05']),
                               ('gso-depth-ssi-v1',['mae','rmse','absrel','delta1','delta2','depth_coverage','silhouette_iou'])]:
            for key in keys:
                na=state['method'] in CAMERA_NA and protocol!='gso-shape-sim3-v1'
                rows.append(dict(protocol_id=protocol,metric=key,value=None,unit=None,status='N/A' if na else 'failed',reason='No native camera pose' if na else 'See evaluation_error.json'))
        atomic_json(dest,dict(evaluator_sha256=version,evaluation_status='failed',metrics=rows))
        print(path.parent,error,flush=True)
        return 'failed'


def evaluate(root, force=False, workers=1, methods=None):
    if workers < 1: raise ValueError('workers must be positive')
    root=Path(root)
    source=Path(__file__).resolve().parents[1]
    version=digest({str(p.relative_to(source)):file_digest(p) for p in [Path(__file__),source/'evaluation/geometry.py',source/'evaluation/render.py',source/'wt/textured_mesh/canon.py',source/'wt/artifacts.py']})
    jobs=[]
    for path in sorted(root.glob('samples/*/*/*/seed-*/run.json')):
        state=json.loads(path.read_text())
        if state['status'] != 'complete' or (methods is not None and state['method'] not in methods): continue
        dest=path.parent/'metrics.json'
        if dest.exists() and not force:
            previous=json.loads(dest.read_text())
            if previous.get('evaluator_sha256') != version:
                raise ValueError('Evaluator changed: review protocol and explicitly re-evaluate pilot with --force')
            if previous.get('evaluation_status')=='complete': continue
        jobs.append(path)
    counts=dict(complete=0,failed=0)
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),max_tasks_per_child=1) as pool:
        futures={pool.submit(evaluate_one,path,version):path for path in jobs}
        for future in as_completed(futures):
            status=future.result()
            counts[status]+=1
            print(futures[future].parent,status,flush=True)
    return counts


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',required=True,type=Path)
    parser.add_argument('--force',action='store_true',help='Explicitly re-evaluate changed pilot protocol; preserve audit separately')
    parser.add_argument('--raw-root',type=Path,default=DATA_ROOT/'raw/gso')
    parser.add_argument('--workers',type=int,default=1,help='Isolated evaluation processes; size for available RAM/GPU memory')
    parser.add_argument('--methods',nargs='+',choices=METHODS)
    args=parser.parse_args()
    require_complete(args.raw_root)
    result = evaluate(args.experiment,args.force,args.workers,args.methods)
    print(result)
    raise SystemExit(1 if result['failed'] else 0)
