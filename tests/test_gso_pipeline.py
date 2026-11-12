"""Synthetic end-to-end dataset → stored camera/crop → three-method evaluation contract."""
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from examples.prepare_gso_views import prepare
from examples.evaluate_gso import evaluate_run
from evaluation.render import Rasterizer
from wt.experiment import atomic_json
from wt.textured_mesh.canon import compute_canonical_transform


@pytest.mark.parametrize("dataset_name", ["gso-v1", "omniobject3d-ood-v1"])
def test_render_manifest_and_all_three_method_metrics(tmp_path, dataset_name):
    import torch
    if not torch.cuda.is_available(): pytest.skip('CUDA required for pipeline contract')
    mesh=trimesh.creation.box(extents=[.7,.5,.9])
    mesh_path=tmp_path/'asset.ply';mesh.export(mesh_path)
    dataset=tmp_path/'dataset';dataset.mkdir()
    (dataset/'inventory.jsonl').write_text(json.dumps(dict(asset_id='box',mesh=str(mesh_path),valid=True))+'\n')
    atomic_json(dataset/'split.json',dict(splits=dict(pilot=['box'])))
    manifest=prepare(dataset,'pilot','z',dataset_name=dataset_name)
    sample=json.loads(manifest.read_text())
    dest=Path(sample['evaluation_dir'])
    # Resume validates artifact hashes instead of generating a different view.
    assert prepare(dataset,'pilot','z',dataset_name=dataset_name) == manifest
    assert sample['dataset'] == dataset_name
    camera=json.loads((dest/'camera.json').read_text())
    reference=trimesh.load(dest/'gt_camera.ply',process=False)
    tf=compute_canonical_transform(np.asarray(reference.vertices))
    native=trimesh.load(dest/'gt_world.ply',process=False)
    hybrid=reference.copy();hybrid.vertices=tf.apply(hybrid.vertices)
    renderer=Rasterizer()
    exp=tmp_path/'experiment'; sample_dir=exp/'samples/box'
    atomic_json(sample_dir/'input.json',sample)
    with np.load(dest/'gt_depth.npz') as data:
        depth,mask,K=data['depth'],data['mask'],data['K']
    v,u=np.indices(depth.shape)
    xyz=np.stack([(u+.5-K[0,2])*depth/K[0,0],(v+.5-K[1,2])*depth/K[1,1],depth],axis=-1)
    for method in ('wt','trellis2','wt_trellis2'):
        run=sample_dir/method/'defaults-v1/seed-0042'
        atomic_json(run/'run.json',dict(status='complete',method=method))
        if method=='wt':
            np.savez_compressed(run/'prediction.npz',xyz=xyz[None],mask=mask[None])
        else:
            (native if method=='trellis2' else hybrid).export(run/'decoded_mesh.ply')
            if method=='wt_trellis2': atomic_json(run/'mesh.json',dict(canonical_transform=tf.to_dict()))
        result=evaluate_run(run,renderer)
        values={(x['protocol_id'],x['metric']):x for x in result['metrics']}
        if method=='trellis2':
            assert values['gso-depth-ssi-v1','mae']['status']=='N/A'
        else:
            assert values['gso-depth-ssi-v1','depth_coverage']['value'] > .995
            assert values['gso-depth-ssi-v1','mae']['value'] < 1e-5
        if method!='wt':
            assert values['gso-shape-sim3-v1','f@0.05']['value'] > .99
