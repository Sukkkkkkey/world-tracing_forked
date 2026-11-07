"""Measure single-GPU tensor batches and independent mesh workers before R2."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

REPO=Path(__file__).resolve().parents[1]
OUTPUT=Path('/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing')
ROOT=OUTPUT/'validation/single-gpu-batch-20261105'


def read(path):return json.loads(path.read_text())
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.partial')
    temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)


def mesh_worker(args):
    import numpy as np
    import torch
    import trimesh
    from wt.batch import InferenceBackend
    from wt.experiment import file_digest,read_json,resolve_reference,run_directory
    from wt.paths import WEIGHTS_ROOT
    plan=read(REPO/'configs/benchmark_single_gpu.json')
    p0=OUTPUT/'experiments/20261013-P0-gso-pilot-v1'
    cfg_id='resolution1024-v1' if args.kind=='pixal' else 'defaults-v1'
    methods=['pixal3d'] if args.kind=='pixal' else ['trellis2','wt_trellis2']
    jobs=[(sample,method) for sample in plan['mesh_samples'] for method in methods]
    if os.environ.get('WT_BENCHMARK_ASSIGNMENT')=='sample':
        selected=set(plan['mesh_samples'][args.worker_index::args.workers])
        jobs=[job for job in jobs if job[0] in selected]
    else:
        jobs=jobs[args.worker_index::args.workers]
    tick=time.perf_counter()
    if args.kind=='pixal':
        from wt.baselines.pixal3d import Pixal3DBackend
        backend=Pixal3DBackend(WEIGHTS_ROOT/'pixal3d/manifest.json');backend.load()
    else:
        checkpoint=WEIGHTS_ROOT/'huggingface/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt'
        backend=InferenceBackend(checkpoint,WEIGHTS_ROOT/'local-pipelines/TRELLIS.2')
        backend.load_trellis(include_stage1=True,modes={'1024_cascade'})
    load_seconds=time.perf_counter()-tick
    write(args.control/'ready.json',dict(pid=os.getpid(),load_seconds=load_seconds,jobs=jobs))
    while not (args.control/'go').exists():time.sleep(.2)
    # Hash geometry and pre-export texture tensors. GLB byte equality is not a
    # valid texture test because UV/export metadata can vary even in serial runs.
    import hashlib
    def signature(value):
        cpu=value.detach().cpu().contiguous()
        return dict(shape=list(cpu.shape),dtype=str(cpu.dtype),
                    sha256=hashlib.sha256(memoryview(cpu.view(torch.uint8).numpy())).hexdigest())
    captured={}
    if args.kind=='pixal':
        import o_voxel
        original_export=o_voxel.postprocess.to_glb
        def export_capture(*values,**kwargs):
            captured.clear()
            for key in ('vertices','faces','coords','attr_volume'):
                captured[key]=signature(kwargs[key])
            captured['grid_size']=kwargs['grid_size']
            return original_export(*values,**kwargs)
        o_voxel.postprocess.to_glb=export_capture
    else:
        import wt.textured_mesh
        original_export=wt.textured_mesh.save_mesh_glb
        def export_capture(path,mesh,**kwargs):
            captured.clear()
            for key in ('vertices','faces','coords','attrs'):
                captured[key]=signature(getattr(mesh,key))
            captured['voxel_size']=float(mesh.voxel_size)
            return original_export(path,mesh,**kwargs)
        wt.textured_mesh.save_mesh_glb=export_capture
    records=[];begin=time.perf_counter()
    for sample,method in jobs:
        ref=run_directory(p0,sample,method,cfg_id,plan['seed'])
        cfg=read_json(ref/'config.json')['parameters']
        image=Path(read_json(p0/'samples'/sample/'input.json')['image'])
        dest=args.output/sample/method;dest.mkdir(parents=True,exist_ok=True)
        parent=None
        if method=='wt_trellis2':
            info=read_json(ref/'wt_parent.json')
            parent=resolve_reference(ref,info['path']).parent
        torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
        tick=time.perf_counter()
        if args.kind=='pixal':
            backend.infer(image,dest,plan['seed'])
        else:
            backend.generate_mesh(image,cfg,plan['seed'],dest,parent)
        torch.cuda.synchronize()
        seconds=time.perf_counter()-tick
        result=dict(sample=sample,method=method,seconds=seconds,
            peak_allocated=torch.cuda.max_memory_allocated(),peak_reserved=torch.cuda.max_memory_reserved(),
            decoded_sha256=file_digest(dest/'decoded_mesh.ply'),
            reference_sha256=file_digest(ref/'decoded_mesh.ply'),
            reference=str(ref/'decoded_mesh.ply'),input_sha256=file_digest(image),preexport_signature=dict(captured))
        assert captured, 'Pre-export tensor capture did not execute'
        result['decoded_exact']=result['decoded_sha256']==result['reference_sha256']
        if args.kind=='pixal':
            result['preprocessed_exact']=file_digest(dest/'preprocessed.png')==file_digest(ref/'preprocessed.png')
        # Reload validation is timed separately and never changes the saved mesh.
        validate=time.perf_counter()
        scene=trimesh.load(dest/'mesh.glb',force='scene',process=False)
        assert scene.geometry and np.isfinite(scene.bounds).all()
        assert any(getattr(g.visual,'material',None) is not None for g in scene.geometry.values())
        del scene
        result['reload_seconds']=time.perf_counter()-validate
        records.append(result);print('MESH-BENCH',args.kind,args.workers,sample,method,seconds,flush=True)
    finish=time.perf_counter()
    write(args.output/'result.json',dict(status='completed',kind=args.kind,worker=args.worker_index,
        started_monotonic=begin,finished_monotonic=finish,wall_seconds=finish-begin,
        load_seconds=load_seconds,records=records,
        all_exact=all(r['decoded_exact'] and r.get('preprocessed_exact',True) for r in records)))


def resources():
    gpu=subprocess.run(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],
                        text=True,capture_output=True,timeout=10)
    memory,util=[int(x.strip()) for x in gpu.stdout.splitlines()[0].split(',')]
    usage=int(Path('/sys/fs/cgroup/memory/memory.usage_in_bytes').read_text())
    stat=dict(line.split() for line in Path('/sys/fs/cgroup/memory/memory.stat').read_text().splitlines())
    return dict(time=time.monotonic(),gpu_used_mib=memory,gpu_util=util,
                instance_working_set_bytes=max(0,usage-int(stat.get('total_inactive_file',0))))


def trial(kind,count,attempt,control_root):
    key=f'{kind}-{count}';output=attempt/key;controls=control_root/key
    output.mkdir(parents=True,exist_ok=True);controls.mkdir(parents=True,exist_ok=True)
    processes=[];handles=[];samples=[];ready_time=None;error=None
    workers=count if kind!='wt' else 1
    started=time.monotonic()
    try:
        for index in range(workers):
            control=controls/f'worker-{index}';control.mkdir()
            destination=output/f'worker-{index}' if kind!='wt' else output
            environment='compare_methods/pixal3d/env.sh' if kind=='pixal' else 'scripts/env.sh'
            if kind=='wt':
                arguments=['scripts/benchmark_wt_batch.py','--batch-size',str(count)]
            else:
                arguments=['scripts/benchmark_single_gpu.py','--worker','--kind',kind,
                           '--workers',str(count),'--worker-index',str(index)]
            command=['bash','-c','source "$1" && shift && exec "$@"','benchmark',environment,
                     'python','-uB',*arguments,'--control',str(control),'--output',str(destination)]
            log=(control/'worker.log').open('w',buffering=1);handles.append(log)
            env=os.environ|{'CUDA_VISIBLE_DEVICES':'0','PYTHONHASHSEED':'42','OMP_NUM_THREADS':'4',
                'MKL_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'4','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
            proc=subprocess.Popen(command,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT)
            processes.append(proc)
            write(control/'process.json',dict(pid=proc.pid,command=command,output=str(destination)))
        last_report=started
        while True:
            sample=resources();samples.append(sample)
            if sample['gpu_used_mib']>78*1024 or sample['instance_working_set_bytes']>122*1024**3:
                error='Resource guard stopped benchmark workers before exhausting the instance';break
            bad=[p.returncode for p in processes if p.poll() is not None and p.returncode!=0]
            if bad:error='Worker failed: '+str(bad);break
            if ready_time is None and all((controls/f'worker-{i}/ready.json').exists() for i in range(workers)):
                ready_time=time.monotonic()
                for index in range(workers):(controls/f'worker-{index}/go').touch()
                print('BENCH START',key,'model preparation seconds',ready_time-started,flush=True)
            if all(p.poll() is not None for p in processes):break
            if time.monotonic()-last_report>=60:
                print('BENCH PROGRESS',key,'elapsed',round(time.monotonic()-started),
                      'gpu MiB',sample['gpu_used_mib'],'util',sample['gpu_util'],flush=True)
                last_report=time.monotonic()
            time.sleep(1)
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=20)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        for h in handles:h.close()
        for index in range(workers):
            src=controls/f'worker-{index}/worker.log'
            if src.exists():shutil.copyfile(src,output/f'worker-{index}.log')
    result=dict(kind=kind,count=count,status='failed' if error else 'completed',error=error,
        elapsed_with_load=time.monotonic()-started,preparation_seconds=ready_time-started if ready_time else None,
        peak_gpu_mib=max((x['gpu_used_mib'] for x in samples),default=0),
        peak_instance_working_set_bytes=max((x['instance_working_set_bytes'] for x in samples),default=0))
    if not error:
        reports=[read(output/'result.json')] if kind=='wt' else [read(output/f'worker-{i}/result.json') for i in range(workers)]
        result['all_exact']=all(r['status']=='completed' and r['all_exact'] for r in reports)
        if kind!='wt' and count>1:
            reference=read(attempt/f'{kind}-1/worker-0/result.json')
            expected={(r['sample'],r['method']):r['preexport_signature'] for r in reference['records']}
            result['preexport_texture_and_geometry_exact']=all(
                r['preexport_signature']==expected[(r['sample'],r['method'])]
                for report in reports for r in report['records'])
            result['all_exact'] &= result['preexport_texture_and_geometry_exact']
        result['images']=sum(r.get('images',len(r.get('records',[]))) for r in reports)
        result['wall_seconds']=max(r['finished_monotonic'] for r in reports)-min(r['started_monotonic'] for r in reports)
        result['items_per_minute']=60*result['images']/result['wall_seconds']
        result['reports']=[str(output/'result.json')] if kind=='wt' else [str(output/f'worker-{i}/result.json') for i in range(workers)]
    write(output/'resources.json',samples);write(output/'trial.json',result)
    print('BENCH RESULT',json.dumps(result),flush=True)
    return result


def main():
    print('Waiting for current R1 baseline and exclusive GPU access',flush=True)
    subprocess.run([sys.executable,'-uB',str(REPO/'scripts/wait_task.py'),'r1-baseline'],check=True)
    with (REPO/'.runtime/recovery-gpu.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        assert read(REPO/'.runtime/logs/recovery-20261105/r1-baseline.status.json')['status']=='passed'
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        attempt=ROOT/stamp;controls=REPO/'.runtime/single-gpu-benchmark'/stamp
        attempt.mkdir(parents=True);controls.mkdir(parents=True)
        plan=read(REPO/'configs/benchmark_single_gpu.json');write(attempt/'plan.json',plan)
        shutil.copyfile(REPO/'scripts/benchmark_wt_batch.py',attempt/'benchmark_wt_batch.py')
        shutil.copyfile(Path(__file__),attempt/'benchmark_single_gpu.py')
        results=[]
        for kind,counts in [('wt',plan['wt_batch_sizes']),('mesh',plan['mesh_workers']),('pixal',plan['mesh_workers'])]:
            for count in counts:
                value=trial(kind,count,attempt,controls);results.append(value)
                write(attempt/'progress.json',dict(status='running',trials=results))
                if count==1:
                    assert value['status']=='completed' and value['all_exact'], 'Serial control did not reproduce P0; inspect before using any optimization'
        recommendations={}
        for kind in ('wt','mesh','pixal'):
            group=[r for r in results if r['kind']==kind]
            base=next(r for r in group if r['count']==1)
            eligible=[r for r in group if r['status']=='completed' and r['all_exact']
                and r['peak_gpu_mib']<=plan['acceptance']['gpu_memory_limit_gib']*1024
                and r['peak_instance_working_set_bytes']<=plan['acceptance']['instance_memory_limit_gib']*1024**3]
            best=max(eligible,key=lambda r:r['items_per_minute'],default=base)
            speedup=best['items_per_minute']/base['items_per_minute']
            selected=best['count'] if speedup>=plan['acceptance']['min_speedup'] else 1
            recommendations[kind]=dict(count=selected,measured_speedup=speedup,
                selection='Exact geometry/RNG agreement, throughput >= 1.10x and measured memory margins required')
        report=dict(status='completed-awaiting-review',attempt=str(attempt),trials=results,recommendations=recommendations,
            finished=datetime.datetime.now(datetime.timezone.utc).isoformat(),controls=str(controls))
        write(attempt/'report.json',report);write(ROOT/'latest.json',dict(report=str(attempt/'report.json')))
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker',action='store_true');p.add_argument('--kind',choices=['mesh','pixal'])
    p.add_argument('--workers',type=int);p.add_argument('--worker-index',type=int)
    p.add_argument('--control',type=Path);p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.worker:
        args.output.mkdir(parents=True,exist_ok=True)
        try:mesh_worker(args)
        except Exception as exc:
            write(args.output/'result.json',dict(status='failed',error=str(exc),traceback=traceback.format_exc()))
            raise
    else:main()
