"""Compare memory-bounded pretrained outputs with the sealed original P0 controls."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np
import torch
import trimesh
from wt.experiment import atomic_json, file_digest, read_json, resolve_reference, run_directory
from wt.paths import OUTPUT_ROOT, WEIGHTS_ROOT
from scripts.recovery_memory import AUDIT, MemoryBoundBackend, source_digests
from scripts.check_recovery_performance import check

def signature(value):
    cpu = value.detach().cpu().contiguous()
    return dict(shape=list(cpu.shape), dtype=str(cpu.dtype),
                sha256=hashlib.sha256(memoryview(cpu.view(torch.uint8).numpy())).hexdigest())

def main():
    decision = check()
    benchmark = OUTPUT_ROOT / 'validation/single-gpu-batch-20261105/20261105T164410Z'
    sealed = read_json(benchmark / 'report.json')
    gold_path = benchmark / 'mesh-1/worker-0/result.json'
    gold = read_json(gold_path)
    controls = {r['sample']:r for r in gold['records'] if r['method']=='wt_trellis2'}
    selected = ['SCHOOL_BUS', 'Frozen_Olafs_In_Trouble_PopOMatic_Game']
    assert set(controls) == set(selected) and gold['all_exact']
    assert file_digest(gold_path) == decision['evidence_sha256'][str(gold_path)]
    assert any(str(gold_path) in trial.get('reports', []) and trial['kind']=='mesh'
               and trial['count']==1 for trial in sealed['trials'])
    destination = AUDIT / 'memory-pretrained-equivalence'
    destination.mkdir(exist_ok=False)
    checkpoint=WEIGHTS_ROOT/'huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt'
    backend = MemoryBoundBackend(checkpoint, WEIGHTS_ROOT/'local-pipelines/TRELLIS.2')
    backend.load_trellis(include_stage1=False, modes={'1024_cascade'})
    import wt.textured_mesh
    original = wt.textured_mesh.save_mesh_glb
    captured = {}
    def capture(path, mesh, **kwargs):
        captured.clear()
        captured.update({key:signature(getattr(mesh,key)) for key in ('vertices','faces','coords','attrs')})
        captured['voxel_size'] = float(mesh.voxel_size)
        return original(path, mesh, **kwargs)
    wt.textured_mesh.save_mesh_glb = capture
    p0 = OUTPUT_ROOT/'experiments/20261013-P0-gso-pilot-v1'
    rows=[]
    try:
        for sample in selected:
            ref=run_directory(p0,sample,'wt_trellis2','defaults-v1',42)
            cfg=read_json(ref/'config.json')['parameters']
            input_record=p0/'samples'/sample/'input.json'
            info=read_json(input_record)
            image=resolve_reference(input_record.parent,info['image'])
            assert file_digest(image)==controls[sample]['input_sha256']==info['sha256']
            parent=resolve_reference(ref,read_json(ref/'wt_parent.json')['path']).parent
            dest=destination/sample;dest.mkdir()
            started=time.monotonic()
            torch.cuda.reset_peak_memory_stats()
            backend.generate_mesh(image,cfg,42,dest,parent)
            torch.cuda.synchronize()
            policy=read_json(dest/'memory-policy.json')
            assert policy['actual']['tiled_calls'] > 0
            assert any(v['stage']=='bounded_fdg' for v in policy['actual']['topology'])
            decoded=file_digest(dest/'decoded_mesh.ply')
            assert decoded==controls[sample]['decoded_sha256']==file_digest(ref/'decoded_mesh.ply')
            assert captured==controls[sample]['preexport_signature'], 'Pre-export geometry/texture changed'
            scene=trimesh.load(dest/'mesh.glb',force='scene',process=False)
            assert scene.geometry and np.isfinite(scene.bounds).all()
            assert any(getattr(g.visual,'material',None) is not None for g in scene.geometry.values())
            del scene
            row=dict(sample=sample,seed=42,input_sha256=file_digest(image),parameters=cfg,
                seconds=time.monotonic()-started,decoded_sha256=decoded,
                preexport_signature=dict(captured),decoded_exact=True,texture_exact=True,
                material_reload=True,policy_sha256=file_digest(dest/'memory-policy.json'),
                peak_allocated=torch.cuda.max_memory_allocated(),
                peak_reserved=torch.cuda.max_memory_reserved(),tiled_calls=policy['actual']['tiled_calls'])
            rows.append(row)
            atomic_json(destination/'progress.json',dict(status='running',records=rows))
            print('PRETRAINED MEMORY EQUIVALENCE',sample,'passed',flush=True)
    finally:
        wt.textured_mesh.save_mesh_glb=original
        backend.unload_trellis()
    report=dict(status='passed',finished=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        records=rows,source_sha256=source_digests(),validator_sha256=file_digest(Path(__file__)),
        component_report_sha256=file_digest(AUDIT/'memory-component-checks.json'),
        original_control_sha256=file_digest(gold_path),original_reviewed_report_sha256=file_digest(benchmark/'report.json'),
        allocator=os.environ.get('PYTORCH_CUDA_ALLOC_CONF'),
        scope='Two fixed pretrained P0 hybrids: decoded PLY and pre-export geometry/coords/texture tensors exact; GLB reload valid. No full GLB byte equality claim.')
    atomic_json(AUDIT/'memory-pretrained-equivalence.json',report)

if __name__=='__main__':
    main()
