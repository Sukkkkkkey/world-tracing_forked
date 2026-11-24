from contextlib import contextmanager
from pathlib import Path
import pytest
from scripts import run_hybrid_adaptive as a
from wt.experiment import atomic_json, read_json


def test_only_cuda_memory_errors_trigger_fallback():
    for msg in ("CUDA out of memory.", "CUDA_ERROR_OUT_OF_MEMORY"):
        assert a.cuda_oom(RuntimeError(msg))
    for err in (MemoryError("out of memory"), RuntimeError("DefaultCPUAllocator: out of memory"), ValueError("bad mesh")):
        assert not a.cuda_oom(err)


def test_dispatch_defers_only_unfinished_and_uses_actual_tail():
    jobs = [dict(destination=str(i), experiment_root=str(i//20), strategy="surface", preprocessing="defaults-v1", parameters={}, config_id="surface") for i in range(100)]
    calls = []
    def attempt(group, req, single):
        ids = [j["destination"] for j in group]
        calls.append((req, ids, single))
        if "2" in ids:
            return (set(ids[:2]) if len(calls)==1 else set()), True
        return set(ids), False
    failed = a.dispatch(jobs, dict(ceiling=a.SIZES[0], deferred=[]), attempt, lambda:None)
    assert [r for r,ids,s in calls[:8]] == [64,32,16,12,10,8,6,4]
    assert [len(ids) for _,ids,_ in calls[:8]] == list(a.SIZES)
    assert all("0" not in ids and "1" not in ids for _,ids,_ in calls[1:])
    assert failed == ["2"] and calls[-1][2]
    assert {ids[0] for _,ids,s in calls if s} == {"2","3","4","5"}


def test_synthetic_mixed_batch_pause_resume(tmp_path,monkeypatch):
    jobs=[dict(destination=str(tmp_path/f"job{i}"), source_key=str(i), strategy="surface", pins={},canonical_transform={},
               input={"sha256":"image"}, parameters={"steps":12}, preprocessing="defaults-v1", experiment_root=str(i//80),config_id=str((i//20)%4))
          for i in range(480)]
    indices=list(range(58))
    plan={"plan_hash":"test"}
    old="frozen-executor"
    class Fake:
        provenance={"torch":"synthetic"}
        loads=0
        history=[]
        def load_trellis(self,**kw): self.loads+=1
        def unload_trellis(self): pass
        def recover(self): pass
        @contextmanager
        def prepare_batch(self,group):
            self.history.append([j["source_key"] for j in group])
            yield
    backend=Fake()
    groups=[jobs[i:i+4] for i in range(0,480,4)]
    monkeypatch.setattr(a.original,"mesh_batches",lambda *args:groups)
    monkeypatch.setattr(a,"validate_sources",lambda *args:None)
    monkeypatch.setattr(a,"assert_camera_idle",lambda:None)
    legacy={}
    for i in indices:
        j=jobs[i];k=a.identity(j,a.schedule_for(groups[i//4],4),backend.provenance,old,plan)
        legacy[j["destination"]]=k
        atomic_json(Path(j["destination"])/"run.json",dict(config_hash=k,status="complete",input_sha256="image"))
    policy=dict(remaining=422,completed_at_pause=legacy,legacy_executor_sha256=old)
    def check(d,k,img):
        assert read_json(d/"run.json")==dict(status="complete",config_hash=k,input_sha256=img)
        return True
    monkeypatch.setattr(a.original,"completed_job",check)
    def finish(plan,b,j,d,key,sched,seconds):
        assert len({jobs[int(i)]["config_id"] for i in sched["members"]})==1
        if len(b.history)==1 and j["source_key"]==b.history[0][2]:
            atomic_json(d/"run.json",dict(status="failed",config_hash=key,input_sha256="image"))
            raise RuntimeError("CUDA out of memory")
        atomic_json(d/"run.json",dict(status="complete",config_hash=key,input_sha256="image"))
    monkeypatch.setattr(a.original,"finish_mesh",finish)
    assert a.run_locked(plan,policy,tmp_path,backend)==0
    assert [len(x) for x in backend.history[:2]]==[64,32]
    assert len({jobs[int(i)]["experiment_root"] for i in backend.history[0]})>1
    assert len({i for group in backend.history for i in group})==422
    assert not set(map(str,indices)).intersection(i for g in backend.history for i in g)
    assert len(list(tmp_path.glob(".*-adaptive-attempt-*")))==1
    assert a.run_locked(plan,policy,tmp_path,backend)==0 and backend.loads==1


def test_non_oom_is_not_retried():
    jobs=[dict(destination="x",experiment_root="G",config_id="c",strategy="band", preprocessing="defaults-v1",parameters={})]
    def attempt(*args): raise ValueError("invalid source")
    with pytest.raises(ValueError, match="invalid source"):
        a.dispatch(jobs,dict(ceiling=a.SIZES[0],deferred=[]),attempt,lambda:pytest.fail("unexpected recovery"))


def test_bucket_respects_all_sampling_settings():
    base = dict(dataset="GSO", condition="A0", experiment_root="g-a0", strategy="band",
                preprocessing="shared-wt-v1", config_id="band-shared-wt-v1", parameters={"steps": 12})
    assert a.bucket(base) == a.bucket(dict(base, dataset="OOD", condition="B1", experiment_root="o-b1"))
    for change in (dict(strategy="surface"), dict(preprocessing="defaults-v1"), dict(parameters={"steps": 8})):
        assert a.bucket(base) != a.bucket(dict(base, **change))
