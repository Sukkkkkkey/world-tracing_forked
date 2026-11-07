"""Scheduling regressions: disjoint writers and lossless retries."""
import multiprocessing
from pathlib import Path
import pytest
from scripts.run_parallel_recovery import partitions,run_worker,incomplete,archive_incomplete
from wt.experiment import atomic_json,file_digest,read_json,run_directory


class FakeBackend:
    provenance={'model':'fixed'}
    def __init__(self,fail=False):self.fail=fail
    def load(self):pass
    def infer(self,image,directory,seed):
        if self.fail:raise RuntimeError('synthetic worker failure')
        (directory/'mesh.glb').write_bytes(image.read_bytes()+str(seed).encode())
        atomic_json(directory/'mesh.json',{'seed':seed})
        atomic_json(directory/'runtime.json',{'seconds':0})
        return {'mesh':dict(path='mesh.glb',kind='mesh',frame='gltf_yup')}


def fixture_root(tmp_path,n=4):
    root=tmp_path/'experiment'
    atomic_json(root/'experiment.json',dict(schema_version=1,experiment_id='experiment'))
    for i in range(n):
        name=f'sample{i}';image=tmp_path/(name+'.png');image.write_bytes(name.encode())
        atomic_json(root/'samples'/name/'input.json',dict(sample_id=name,image=str(image),sha256=file_digest(image)))
    old=root/'samples/sample0/trellis2/defaults-v1/seed-0042/keep.txt'
    old.parent.mkdir(parents=True);old.write_text('untouched baseline')
    return root


def spec(root,ids,index=0):
    return dict(root=str(root),kind='pixal',samples=ids,configs=[],provenance=FakeBackend.provenance,
                summary=f'parallel-pixal-worker{index}.json')


def child_run(value):
    raise SystemExit(run_worker(value,FakeBackend()))


def test_partition_keeps_every_sample_once():
    values=[dict(sample_id=f'x{i}') for i in range(9)]
    chunks=partitions(values,2)
    assert sorted(v['sample_id'] for chunk in chunks for v in chunk)==[f'x{i}' for i in range(9)]
    assert set(v['sample_id'] for v in chunks[0]).isdisjoint(v['sample_id'] for v in chunks[1])
    with pytest.raises(ValueError):partitions(['duplicate','duplicate'],2)


def test_two_processes_write_distinct_complete_results(tmp_path):
    root=fixture_root(tmp_path)
    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    ctx=multiprocessing.get_context('fork')
    jobs=[ctx.Process(target=child_run,args=(spec(root,ids,index),))
          for index,ids in enumerate(partitions([f'sample{i}' for i in range(4)],2))]
    for job in jobs:job.start()
    for job in jobs:job.join(timeout=20);assert job.exitcode==0
    assert all(p.read_bytes()==original for p,original in before.items())
    for i in range(4):
        folder=run_directory(root,f'sample{i}','pixal3d','resolution1024-v1',42)
        state=read_json(folder/'run.json')
        assert state['status']=='complete'
        assert all(file_digest(folder/name)==sha for name,sha in state['artifact_sha256'].items())
    assert (root/'parallel-pixal-worker0.json').is_file()
    assert (root/'parallel-pixal-worker1.json').is_file()
    assert not (root/'last_pixal3d_batch.json').exists()


def test_retry_preserves_failure_and_completed_neighbors(tmp_path):
    root=fixture_root(tmp_path,2)
    assert run_worker(spec(root,['sample0']),FakeBackend(fail=True))==1
    assert run_worker(spec(root,['sample1'],1),FakeBackend())==0
    successful=run_directory(root,'sample1','pixal3d','resolution1024-v1',42)
    before={p:p.read_bytes() for p in successful.iterdir() if p.is_file()}
    pending=incomplete(root,['sample0','sample1'],'pixal',[])
    assert len(pending)==1
    archive=tmp_path/'retry-audit'
    archived=archive_incomplete(root,pending,archive)
    assert len(archived)==1
    assert read_json(Path(archived[0]['archive'])/'run.json')['status']=='failed'
    assert run_worker(spec(root,['sample0']),FakeBackend())==0
    assert not incomplete(root,['sample0','sample1'],'pixal',[])
    assert all(p.read_bytes()==value for p,value in before.items())
    assert 'synthetic worker failure' in (Path(archived[0]['archive'])/'error.txt').read_text()


def test_retry_rejects_evaluated_artifacts(tmp_path):
    root=fixture_root(tmp_path,1)
    assert run_worker(spec(root,['sample0']),FakeBackend(fail=True))==1
    folder=incomplete(root,['sample0'],'pixal',[])[0]
    atomic_json(folder/'metrics.json',{'evaluation_status':'complete'})
    with pytest.raises(ValueError,match='evaluated'):
        archive_incomplete(root,[folder],tmp_path/'never-overwrite')


def test_transient_gpu_query_timeout_keeps_cpu_visibility_and_recovers(tmp_path,monkeypatch):
    import subprocess
    import scripts.run_parallel_recovery as runner
    (tmp_path/'memory.stat').write_text('total_inactive_file 2048\n')
    (tmp_path/'memory.usage_in_bytes').write_text('8192\n')
    replies=iter([subprocess.TimeoutExpired('nvidia-smi',10),'128\n'])
    def query(*args,**kwargs):
        value=next(replies)
        if isinstance(value,Exception):raise value
        return value
    monkeypatch.setattr(runner.subprocess,'check_output',query)
    first=runner.memory_sample(tmp_path)
    assert first['gpu_mib'] is None and first['working_set_bytes']==6144
    assert 'TimeoutExpired' in first['monitor_error']
    missed,reason=runner.monitor_guard(first,0)
    assert missed==1 and reason is None
    second=runner.memory_sample(tmp_path)
    assert second['gpu_mib']==128 and second['monitor_error'] is None
    assert runner.monitor_guard(second,missed)==(0,None)


def test_persistent_gpu_query_failure_closes_parallel_execution():
    from scripts.run_parallel_recovery import monitor_guard
    value=dict(gpu_mib=None,working_set_bytes=0)
    missed=0
    for index in range(3):
        missed,reason=monitor_guard(value,missed)
        assert (reason is None)==(index<2)
    assert 'three consecutive' in reason


def test_cpu_margin_is_enforced_when_gpu_query_is_unavailable():
    from scripts.run_parallel_recovery import monitor_guard
    missed,reason=monitor_guard(dict(gpu_mib=None,working_set_bytes=123*1024**3),0)
    assert missed==1 and reason=='Instance working-set margin reached'
