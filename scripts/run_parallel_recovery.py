"""Run reviewed independent sample workers on one GPU, with serial recovery."""
import argparse
import datetime
import fcntl
import gc
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from wt.experiment import SCHEMA_VERSION,atomic_json,digest,file_digest,identifier,read_json,run_directory
from wt.paths import OUTPUT_ROOT,PROCESSED_ROOT,WEIGHTS_ROOT

REPO=Path(__file__).resolve().parents[1]


def partitions(values,count):
    ids=[v['sample_id'] if isinstance(v,dict) else v for v in values]
    if count not in (1,2) or len(ids)!=len(set(ids)) or not ids:
        raise ValueError('Expected distinct frozen samples and one or two workers')
    for sample in ids:identifier(sample)
    return [values[i::count] for i in range(min(count,len(values)))]


def baseline_inputs(spec):
    path=PROCESSED_ROOT/'gso/v1'/(spec['split']+'.jsonl')
    values=[]
    for line in path.read_text().splitlines():
        if not line.strip():continue
        value=json.loads(line)
        for owner,key in [(value,'image')]+([(value['ground_truth'],'path')] if 'ground_truth' in value else []):
            target=Path(owner[key]);owner[key]=str(target if target.is_absolute() else path.parent/target)
        values.append(value)
    expected=read_json(REPO/'configs/historical_gso_samples.json')[spec['split']]
    assert len(values)==len(expected) and {v['sample_id'] for v in values}==set(expected)
    return values


def new_backend(kind):
    if kind=='pixal':
        from wt.baselines.pixal3d import Pixal3DBackend
        return Pixal3DBackend(WEIGHTS_ROOT/'pixal3d/manifest.json')
    from wt.batch import InferenceBackend
    checkpoint=WEIGHTS_ROOT/'huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt'
    return InferenceBackend(checkpoint,WEIGHTS_ROOT/'local-pipelines/TRELLIS.2')


def baseline_preflight(root,inputs,configs,backend):
    from wt.batch import completed
    partitions(inputs,1)
    for item in inputs:
        sample=item['sample_id'];sha=file_digest(Path(item['image']))
        previous=root/'samples'/sample/'input.json'
        if previous.exists() and read_json(previous)['sha256']!=sha:
            raise ValueError('Frozen input changed: '+sample)
        for cfg in configs:
            folder=run_directory(root,sample,cfg['method'],cfg['config_id'],42)
            config_hash=digest(dict(config=cfg,provenance=backend.provenance))
            state=folder/'run.json'
            if state.exists() and read_json(state).get('config_hash')!=config_hash:
                raise ValueError('Config/source changed: '+str(folder))
            if (folder/'metrics.json').exists() and not completed(folder,config_hash,sha):
                raise ValueError('Evaluated artifacts require a separate repair audit: '+str(folder))


def precompute_wt(root,inputs,configs,backend):
    from wt.batch import cache_key
    pending={}
    for value in inputs:
        sample=dict(value,sha256=file_digest(Path(value['image'])))
        for cfg in configs:
            if cfg['method']=='trellis2':continue
            key=cache_key(sample,cfg,42,backend.provenance)
            directory=root/'_cache/wt'/key
            try:
                info=read_json(directory/'complete.json')
                assert info['cache_key']==key
                assert file_digest(directory/'prediction.npz')==info['sha256']
                assert file_digest(directory/'rgba.png')==info['rgba_sha256']
            except (OSError,ValueError,KeyError,AssertionError):
                pending.setdefault(key,(sample,cfg,directory))
    if not pending:return
    from contextlib import redirect_stdout,redirect_stderr
    backend.load_wt()
    try:
        for index,(key,(sample,cfg,directory)) in enumerate(pending.items()):
            directory.mkdir(parents=True,exist_ok=True)
            started=time.monotonic()
            with (directory/'run.log').open('w') as log,redirect_stdout(log),redirect_stderr(log):
                backend.predict_wt(Path(sample['image']),cfg,42,directory)
            atomic_json(directory/'complete.json',dict(cache_key=key,
                sha256=file_digest(directory/'prediction.npz'),rgba_sha256=file_digest(directory/'rgba.png'),
                seconds=time.monotonic()-started))
            print('WT SERIAL CACHE',index+1,'/',len(pending),sample['sample_id'],flush=True)
    finally:backend.unload_wt()


def run_worker(spec,backend=None):
    root=Path(spec['root'])
    backend=backend or new_backend(spec['kind'])
    assert backend.provenance==spec['provenance'],'Source changed during execution'
    if spec['kind']=='pixal':
        from wt.baselines.pixal3d_batch import run_batch
        return run_batch(root,backend,spec['samples'],42,summary_file=spec['summary'])
    import wt.batch as batch
    original=batch.atomic_json
    def write(path,value):
        if Path(path)==root/'last_batch.json':path=root/spec['summary']
        original(path,value)
    batch.atomic_json=write
    try:return int(batch.run_batch(root,spec['samples'],spec['configs'],[42],backend)>0)
    finally:batch.atomic_json=original


def incomplete(root,ids,kind,configs):
    pairs=[('pixal3d','resolution1024-v1')] if kind=='pixal' else [(c['method'],c['config_id']) for c in configs]
    pending=[]
    for sample in ids:
        for method,config in pairs:
            path=run_directory(root,sample,method,config,42)
            state=path/'run.json'
            if not state.exists() or read_json(state).get('status')!='complete':pending.append(path)
    return pending


def archive_incomplete(root,folders,destination):
    records=[]
    for folder in folders:
        assert folder.resolve().is_relative_to((root/'samples').resolve())
        if not folder.exists():continue
        if (folder/'metrics.json').exists():
            raise ValueError('Never overwrite evaluated artifacts during automatic retry')
        state=folder/'run.json'
        if state.exists() and read_json(state).get('status')=='complete':
            raise ValueError('Never archive a completed result for automatic retry')
        target=destination/folder.relative_to(root)
        shutil.copytree(folder,target)
        records.append(dict(source=str(folder),archive=str(target)))
    atomic_json(destination/'manifest.json',records)
    return records


def memory_sample(memory_root=Path('/sys/fs/cgroup/memory')):
    gpu_mib=None;error=None
    try:
        raw=subprocess.check_output(
            ['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],
            text=True,stderr=subprocess.STDOUT,timeout=10)
        gpu_mib=int(raw.splitlines()[0])
    except (subprocess.SubprocessError,OSError,ValueError,IndexError) as exc:
        error=type(exc).__name__+': '+str(exc).splitlines()[0][:240]
    # CPU pressure remains observable even when the GPU query times out.
    stat=dict(line.split() for line in (memory_root/'memory.stat').read_text().splitlines())
    usage=int((memory_root/'memory.usage_in_bytes').read_text())
    return dict(time=time.monotonic(),gpu_mib=gpu_mib,monitor_error=error,
                working_set_bytes=max(0,usage-int(stat.get('total_inactive_file',0))))


def monitor_guard(value,missed):
    missed=missed+1 if value['gpu_mib'] is None else 0
    reason=None
    if value['working_set_bytes']>122*1024**3:
        reason='Instance working-set margin reached'
    elif value['gpu_mib'] is not None and value['gpu_mib']>78*1024:
        reason='GPU memory margin reached'
    elif missed>=3:
        reason='GPU telemetry unavailable for three consecutive samples'
    return missed,reason


def run_parent(args):
    recipe=read_json(REPO/'configs/recovery_experiments.json')
    root=args.experiment.resolve()
    spec=next(v for v in recipe['experiments'] if root.name==v['id'])
    assert root==(OUTPUT_ROOT/'experiments'/spec['id']).resolve()
    decision=read_json(args.decision)
    assert decision['status']=='reviewed' and decision['workers'][args.kind]==args.workers
    assert decision['wt_batch_size']==1 and args.workers==2
    for name,sha in decision['evidence_sha256'].items():assert file_digest(Path(name))==sha
    assert decision['runner_sha256']==file_digest(Path(__file__))
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    control=REPO/'.runtime/logs/recovery-20261105'/f'parallel-{args.kind}-{root.name}-{stamp}'
    control.mkdir(parents=True)
    audit=OUTPUT_ROOT/'validation/recovery-20261105'/root.name
    audit.mkdir(parents=True,exist_ok=True)
    configs=[]
    if args.kind=='baseline':
        from wt.batch import resolve_configs
        inputs=baseline_inputs(spec)
        configs=resolve_configs(read_json(REPO/spec['configs']))
    else:
        inputs=[p.parent.name for p in sorted((root/'samples').glob('*/input.json'))]
        assert len(inputs)==spec['samples']
    shards=partitions(inputs,args.workers)
    ids=[v['sample_id'] if isinstance(v,dict) else v for v in inputs]
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        backend=new_backend(args.kind);provenance=backend.provenance
        if args.kind=='pixal':
            from wt.baselines.pixal3d_batch import run_batch
            run_batch(root,backend,ids,42,dry_run=True)
        else:
            baseline_preflight(root,inputs,configs,backend)
            if not (root/'experiment.json').exists():
                atomic_json(root/'experiment.json',dict(schema_version=SCHEMA_VERSION,experiment_id=root.name))
            else:assert read_json(root/'experiment.json')['schema_version']==SCHEMA_VERSION
            precompute_wt(root,inputs,configs,backend)
        del backend;gc.collect()
        started=time.monotonic();processes=[];handles=[];observed=[];guard=None
        try:
            for index,values in enumerate(shards):
                worker=dict(kind=args.kind,root=str(root),samples=values,configs=configs,provenance=provenance,
                            summary=f'parallel-{args.kind}-worker{index}.json')
                path=control/f'worker-{index}.json';atomic_json(path,worker)
                log=(control/f'worker-{index}.log').open('w',buffering=1);handles.append(log)
                process=subprocess.Popen([sys.executable,'-uB',str(Path(__file__)),'--worker-spec',str(path)],
                    cwd=REPO,stdout=log,stderr=subprocess.STDOUT,
                    env=os.environ|{'CUDA_VISIBLE_DEVICES':'0','PYTHONHASHSEED':'42',
                    'OMP_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'4','MKL_NUM_THREADS':'4'})
                processes.append(process)
                atomic_json(control/f'worker-{index}.process.json',dict(pid=process.pid,log=str(control/f'worker-{index}.log')))
            last=started;missed=0
            while any(p.poll() is None for p in processes):
                value=memory_sample();observed.append(value)
                missed,guard=monitor_guard(value,missed)
                if value['monitor_error']:
                    print('RESOURCE MONITOR RETRY',missed,'/ 3',value['monitor_error'],flush=True)
                if guard:
                    print('RESOURCE GUARD',guard,flush=True)
                    break
                if time.monotonic()-last>=60:
                    print('PARALLEL',args.kind,'elapsed',round(time.monotonic()-started),'memory',value,flush=True);last=time.monotonic()
                time.sleep(2)
        finally:
            for p in processes:
                if p.poll() is None:p.terminate()
            for p in processes:
                try:p.wait(timeout=20)
                except subprocess.TimeoutExpired:p.kill();p.wait()
            for h in handles:h.close()
            atomic_json(control/'resources.json',observed)
        pending=incomplete(root,ids,args.kind,configs)
        failures=[p.returncode for p in processes]
        fallback=[]
        if pending:
            retry=audit/'retries'/f'{args.kind}-{stamp}'
            fallback=archive_incomplete(root,pending,retry)
            health=memory_sample()
            atomic_json(control/'before-serial-retry-resources.json',health)
            _,unsafe=monitor_guard(health,0)
            if health['gpu_mib'] is None or unsafe:
                raise RuntimeError('GPU/instance telemetry has not recovered after stopping owned workers: '+str(health))
            samples={p.relative_to(root/'samples').parts[0] for p in pending}
            values=[v for v in inputs if (v['sample_id'] if isinstance(v,dict) else v) in samples]
            print('SERIAL RETRY',len(values),'samples;',guard or failures,flush=True)
            worker=dict(kind=args.kind,root=str(root),samples=values,configs=configs,provenance=provenance,
                        summary=f'parallel-{args.kind}-serial-retry.json')
            path=control/'serial-retry.json';atomic_json(path,worker)
            with (control/'serial-retry.log').open('w',buffering=1) as log:
                subprocess.run([sys.executable,'-uB',str(Path(__file__)),'--worker-spec',str(path)],
                               cwd=REPO,stdout=log,stderr=subprocess.STDOUT,check=True)
        assert not incomplete(root,ids,args.kind,configs),'Incomplete formal results remain'
        if any(failures) and not fallback:
            raise RuntimeError('Worker failed after writing outputs; inspect logs before acceptance')
        report=dict(status='passed',kind=args.kind,workers=args.workers,device=0,samples=len(ids),
            elapsed_seconds=time.monotonic()-started,worker_exits=failures,resource_guard=guard,retries=fallback,
            elapsed_scope='Worker startup, loading, parallel inference/export and any serial retry; parent WT precompute excluded.',
            monitor_query_error_count=sum(v['monitor_error'] is not None for v in observed),
            monitored_parallel_peak_gpu_mib=max((v['gpu_mib'] for v in observed if v['gpu_mib'] is not None),default=0),
            monitored_parallel_peak_working_set_bytes=max((v['working_set_bytes'] for v in observed),default=0),
            decision_sha256=file_digest(args.decision),runner_sha256=file_digest(Path(__file__)),control=str(control),
            finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
        atomic_json(control/'resources.json',observed);atomic_json(control/'complete.json',report)
        shutil.copytree(control,audit/'execution-logs'/control.name)
        atomic_json(audit/f'execution-{args.kind}.json',report)
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-spec',type=Path)
    parser.add_argument('--experiment',type=Path)
    parser.add_argument('--kind',choices=['baseline','pixal'])
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--decision',type=Path)
    args=parser.parse_args()
    if args.worker_spec:raise SystemExit(run_worker(read_json(args.worker_spec)))
    assert os.environ.get('TMUX') or os.environ.get('STY'),'Use dedicated tmux'
    run_parent(args)
