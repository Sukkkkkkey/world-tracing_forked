"""Recover only the two archived R2 OOMs with a reviewed historical memory policy."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import time
import numpy as np
from wt.experiment import atomic_json, digest, file_digest, read_json, resolve_reference, run_directory
from wt.paths import OUTPUT_ROOT, WEIGHTS_ROOT
from wt.batch import cache_key, resolve_configs
from scripts.recovery_memory import AUDIT, MemoryBoundBackend, policy_record, source_digests
from scripts.run_parallel_recovery import baseline_inputs, precompute_wt

REPO=Path(__file__).resolve().parents[1]
ROOT=OUTPUT_ROOT/'experiments/20261013-R2-gso-quant-v1'
SAMPLES=('Pokémon_Omega_Ruby_Alpha_Sapphire_Dual_Pack_Nintendo_3DS',
         '3M_Antislip_Surfacing_Light_Duty_White')
DECISION=AUDIT/'memory-policy-decision.json'
REPORT=AUDIT/'memory-repair.json'

def check_decision():
    value=read_json(DECISION)
    assert value['status']=='reviewed' and value['seed']==42
    assert value['samples']==list(SAMPLES)
    assert value['allocator']=='expandable_segments:True'
    for path,checksum in value['source_sha256'].items():
        assert file_digest(Path(path))==checksum,path
    for path,checksum in value['evidence_sha256'].items():
        assert file_digest(Path(path))==checksum,path
    equivalent=read_json(AUDIT/'memory-pretrained-equivalence.json')
    assert equivalent['status']=='passed' and len(equivalent['records'])==2
    assert all(row['decoded_exact'] and row['texture_exact'] and row['material_reload']
               for row in equivalent['records'])
    assert equivalent['source_sha256']==source_digests()
    assert equivalent['allocator']==value['allocator']
    return value

def run_path(sample):
    return run_directory(ROOT,sample,'wt_trellis2','defaults-v1',42)

def remove_archived_failed(root,folder,archive):
    """Delete only a failed, unevaluated directory with an exact verified archive."""
    sample_root=(root/'samples').resolve()
    assert folder.is_dir() and archive.is_dir() and not folder.is_symlink() and not archive.is_symlink()
    assert folder.resolve().is_relative_to(sample_root)
    relative=folder.resolve().relative_to(sample_root)
    assert len(relative.parts)==4 and relative.parts[-1]=='seed-0042'
    assert folder.resolve()!=archive.resolve()
    assert not any(p.is_symlink() for p in folder.rglob('*'))
    assert not any(p.is_symlink() for p in archive.rglob('*'))
    assert read_json(folder/'run.json')['status']=='failed'
    assert not (folder/'metrics.json').exists()
    source_files={str(p.relative_to(folder)):p for p in folder.rglob('*') if p.is_file()}
    archived_files={str(p.relative_to(archive)):p for p in archive.rglob('*') if p.is_file()}
    assert source_files.keys()==archived_files.keys()
    assert source_files and all(file_digest(p)==file_digest(archived_files[n]) for n,p in source_files.items())
    shutil.rmtree(folder)

def preserved_files(root, excluded):
    result={}
    count=0
    for path in sorted((root/'samples').glob('*/*/*/seed-0042/run.json')):
        if path.parent in excluded:
            continue
        state=read_json(path)
        assert state['status']=='complete'
        count+=1
        files=[path,path.parent/'config.json',path.parent/'runtime.json']
        if (path.parent/'mesh.json').exists():files.append(path.parent/'mesh.json')
        for artifact in state['artifacts'].values():
            files.append(resolve_reference(path.parent,artifact['path']))
        for file in set(files):
            result[str(file.relative_to(root))]=file_digest(file)
        if count%25==0:print('PRESERVE',count,'/ 298',flush=True)
    assert count==298
    for file in [root/'experiment.json',*sorted((root/'samples').glob('*/input.json'))]:
        result[str(file.relative_to(root))]=file_digest(file)
    return result

def verify_hashes(root,records):
    for path,checksum in records.items():
        assert file_digest(root/path)==checksum,'Preserved artifact changed: '+path

def verify_completion(root=ROOT):
    assert root.resolve()==ROOT.resolve()
    check_decision()
    report=read_json(REPORT)
    assert report['status']=='passed' and report['samples']==list(SAMPLES)
    assert report['decision_sha256']==file_digest(DECISION)
    assert report['repair_runner_sha256']==file_digest(Path(__file__))
    verify_hashes(root,report['preserved_sha256'])
    verify_hashes(root,report['repaired_sha256'])
    for sample in SAMPLES:
        directory=run_path(sample);state=read_json(directory/'run.json')
        cfg=read_json(directory/'config.json')
        assert state['status']=='complete' and state['seed']==42
        assert cfg['provenance']['runtime_memory_policy']==policy_record()
        assert state['config_hash']==digest(dict(config=cfg['parameters'],provenance=cfg['provenance']))
        assert read_json(directory/'memory-policy.json')['policy']==policy_record()
    for row in report['wt_replay']:
        assert row['arrays_exact'] and row['rgba_exact']
        for key in ('old_prediction','new_prediction','old_rgba','new_rgba'):
            assert file_digest(Path(row[key]))==row[key+'_sha256']
    return report

def repair():
    started=time.monotonic()
    decision=check_decision()
    assert os.environ.get('PYTORCH_CUDA_ALLOC_CONF')==decision['allocator']
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='0'
    if REPORT.exists():
        report=verify_completion()
        write_execution(report)
        print('Memory repair already verified',flush=True)
        return
    start=read_json(AUDIT/'memory-repair-start.json')
    assert start['status']=='original_serial_attempt_failed' and start['failed_samples']==list(SAMPLES)
    old_archive=Path(start['serial_archive'])
    old_records=read_json(old_archive/'manifest.json')
    assert len(old_records)==2
    targets=[run_path(sample) for sample in SAMPLES]
    for target,record in zip(targets,old_records):
        assert str(target)==record['source']
        assert read_json(target/'run.json')['status']=='failed'
        assert 'out of memory' in read_json(target/'run.json')['error'].lower()
        assert not (target/'metrics.json').exists()
        for name,checksum in record['sha256'].items():
            assert file_digest(target/name)==checksum
            assert file_digest(Path(record['archive'])/name)==checksum
    protected=preserved_files(ROOT,set(targets))
    atomic_json(AUDIT/'memory-preservation-before.json',protected)
    recipe=read_json(REPO/'configs/recovery_experiments.json')
    spec=next(v for v in recipe['experiments'] if v['id']==ROOT.name)
    inputs=[v for v in baseline_inputs(spec) if v['sample_id'] in SAMPLES]
    assert {v['sample_id'] for v in inputs}==set(SAMPLES)
    configs=resolve_configs(read_json(REPO/spec['configs']))
    cfg=next(v for v in configs if v['method']=='wt_trellis2')
    for target in targets:
        assert read_json(target/'config.json')['parameters']==cfg
    checkpoint=WEIGHTS_ROOT/'huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt'
    backend=MemoryBoundBackend(checkpoint,WEIGHTS_ROOT/'local-pipelines/TRELLIS.2')
    base_provenance=read_json(targets[0]/'config.json')['provenance']
    assert backend.provenance['sources']==base_provenance['sources']
    precompute_wt(ROOT,inputs,[cfg],backend)
    replay=[]
    for value in inputs:
        sample=dict(value,sha256=file_digest(Path(value['image'])))
        new_dir=ROOT/'_cache/wt'/cache_key(sample,cfg,42,backend.provenance)
        target=run_path(sample['sample_id'])
        parent=read_json(target/'wt_parent.json')
        old_prediction=resolve_reference(target,parent['path'])
        assert file_digest(old_prediction)==parent['sha256']
        paths=dict(old_prediction=old_prediction,new_prediction=new_dir/'prediction.npz',
                   old_rgba=old_prediction.parent/'rgba.png',new_rgba=new_dir/'rgba.png')
        with np.load(paths['old_prediction'],allow_pickle=False) as before, np.load(paths['new_prediction'],allow_pickle=False) as after:
            assert set(before.files)==set(after.files)
            assert all(np.array_equal(before[name],after[name]) for name in before.files)
        assert file_digest(paths['old_rgba'])==file_digest(paths['new_rgba'])
        row=dict(sample=sample['sample_id'],arrays_exact=True,rgba_exact=True,
                 **{key:str(path) for key,path in paths.items()},
                 **{key+'_sha256':file_digest(path) for key,path in paths.items()})
        replay.append(row)
    atomic_json(AUDIT/'memory-wt-replay.json',replay)
    verify_hashes(ROOT,protected)
    for target,record in zip(targets,old_records):
        remove_archived_failed(ROOT,target,Path(record['archive']))
    import wt.batch as batch
    original=batch.atomic_json
    input_paths={ROOT/'samples'/sample/'input.json' for sample in SAMPLES}
    def guarded_write(path,value):
        path=Path(path)
        if path in input_paths:
            assert read_json(path)==value,'Frozen input metadata changed'
            return
        if path==ROOT/'last_batch.json':
            path=AUDIT/'memory-repair-last-batch.json'
        else:
            assert any(path.is_relative_to(target) for target in targets) or path.is_relative_to(ROOT/'_cache/wt'),path
        original(path,value)
    batch.atomic_json=guarded_write
    try:
        failures=batch.run_batch(ROOT,inputs,[cfg],[42],backend)
    finally:
        batch.atomic_json=original
    assert failures==0,'Selective memory repair has incomplete outputs'
    verify_hashes(ROOT,protected)
    repaired={}
    for target in targets:
        assert read_json(target/'run.json')['status']=='complete'
        for file in target.iterdir():
            if file.is_file():repaired[str(file.relative_to(ROOT))]=file_digest(file)
    report=dict(status='passed',samples=list(SAMPLES),seed=42,
        finished=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        elapsed_seconds=time.monotonic()-started,decision_sha256=file_digest(DECISION),
        repair_runner_sha256=file_digest(Path(__file__)),provenance=backend.provenance,
        original_failed_archive=start['serial_archive'],wt_replay=replay,
        preserved_runs=298,preserved_sha256=protected,repaired_sha256=repaired)
    atomic_json(REPORT,report)
    verify_completion()
    write_execution(report)
    print('REVIEWED MEMORY REPAIR COMPLETE: 300 baseline outputs available for evaluation',flush=True)


def write_execution(report):
    start=read_json(AUDIT/'memory-repair-start.json')
    old_records=read_json(Path(start['serial_archive'])/'manifest.json')
    status=read_json(Path(start['failed_task_status']))
    failed_elapsed=(datetime.datetime.fromisoformat(status['finished'])-datetime.datetime.fromisoformat(status['started'])).total_seconds()
    control=Path(start['control'])
    resources=read_json(control/'resources.json')
    scheduler=read_json(Path(start['decision_snapshot']))
    execution=dict(status='passed',kind='baseline',workers=2,device=0,samples=100,
        execution_mode='parallel-plus-reviewed-selective-memory-repair',
        elapsed_seconds=failed_elapsed+report['elapsed_seconds'],
        elapsed_scope='Sum of the original v2 attempt wall time (including cached-WT preflight and unsuccessful serial retry) and selective memory repair (including WT replay and preservation checks); excludes diagnosis/validation downtime and the earlier WT generation attempt.',
        worker_exits=[1,1],original_serial_retry_exit=1,final_memory_repair_exit=0,
        resource_guard=None,retries=old_records,
        runner_sha256=start['source_runner_sha256'],
        decision_sha256=file_digest(Path(start['decision_snapshot'])),
        completion_runner_sha256=file_digest(Path(__file__)),
        memory_decision_sha256=file_digest(DECISION),memory_repair_sha256=file_digest(REPORT),
        original_failed_task_sha256=file_digest(Path(start['failed_task_status'])),
        original_attempt_log_archive=start['archived_control'],
        monitor_query_error_count=sum(v.get('monitor_error') is not None for v in resources),
        monitored_parallel_peak_gpu_mib=max(v['gpu_mib'] for v in resources if v['gpu_mib'] is not None),
        monitored_parallel_peak_working_set_bytes=max(v['working_set_bytes'] for v in resources),
        control=str(control),finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
    assert execution['runner_sha256']==scheduler['runner_sha256']
    atomic_json(AUDIT/'execution-baseline.json',execution)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    if args.verify:
        verify_completion()
        print('Memory completion and preserved artifacts verified')
        return
    assert os.environ.get('TMUX'),'Use dedicated recovery tmux'
    with (REPO/'.runtime/recovery-gpu.lock').open('a') as gpu_lock:
        fcntl.flock(gpu_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with (ROOT/'.writer.lock').open('a') as writer_lock:
            fcntl.flock(writer_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            repair()

if __name__=='__main__':
    main()
