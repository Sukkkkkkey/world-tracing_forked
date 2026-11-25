"""Evaluate exported GLBs with the exact formal native evaluator and revisions."""
import os
import sys
from pathlib import Path

from scripts.prepare_stage1_oracle import CONTROL, FORMAL
from wt.experiment import atomic_json, file_digest, read_json

sys.path.insert(0,str(FORMAL))
from formal_native_glb import NativeGlbEvaluator
from scripts.run_ood_evaluation import index_row


def main(lane,lanes,overlap=False):
    import gc
    import torch
    torch.cuda.set_per_process_memory_fraction(.0375 if overlap else .065)
    cpus=sorted(os.sched_getaffinity(0))
    os.sched_setaffinity(0,{cpus[lane%len(cpus)]})
    plan=read_json(CONTROL/"plan.json")
    evaluator=None
    prev=None
    scope=read_json(CONTROL/"B-primary.json")
    assert scope["plan_hash"]==plan["hash"]
    reference=set(scope["reference_A"])
    jobs=[j for j in plan["jobs"] if j["mode"]=="B"]+[j for j in plan["jobs"] if j["dest"] in reference]
    assert len(jobs)==200+len(reference)
    for j in jobs[lane::lanes]:
        if overlap and not read_json(CONTROL/"state.json")["phase"].startswith("inference-"):break
        ds,sid,mode=j["dataset"],j["input"]["sample_id"],j["mode"]
        dest=Path(j["dest"])
        path=CONTROL/"metrics"/ds/sid/(mode+".json")
        glb=dest/"mesh.glb"
        if path.exists():
            row=read_json(path)
            if row["plan_hash"]!=plan["hash"] or file_digest(Path(row["result_path"]))!=row["result_sha256"]:
                raise ValueError(f"Cached metric changed: {path}")
            continue
        if overlap:
            run=dest/"run.json"
            if not run.is_file() or read_json(run)["status"]!="complete":continue
            import subprocess
            free=int(subprocess.check_output(["nvidia-smi","--query-gpu=memory.free","--format=csv,noheader,nounits"],text=True).strip())
            if free<14*1024:break
        assert read_json(dest/"oracle.json")["support_sha256"]==j["support_sha256"]
        if prev!=ds:
            del evaluator
            gc.collect()
            torch.cuda.empty_cache()
            evaluator=NativeGlbEvaluator(Path(j["eval_config"]))
            assert evaluator.revision==j["revision"],(evaluator.revision,j["revision"])
            prev=ds
        result=evaluator.evaluate(dest,"glb","20261124-stage1-oracle-"+ds)
        if result["status"]!="complete":raise RuntimeError(result.get("error"))
        assert result["numerical_status"]=="complete"
        visible=result["regions"]["visible"]
        assert visible["status"]=="complete" or (visible["status"]=="empty_prediction" and visible["prediction_points"]==0 and visible["metrics"]["cd_euclidean_mean"] is None)
        assert (result["sample_id"],result["seed"],result["stage"],result["source_directory"],result["revision"])==(sid,42,"glb",str(dest),j["revision"])
        assert result["inputs"][str(glb)]==file_digest(glb)
        assert result["inputs"][j["input"]["image"]]==j["input"]["sha256"]
        assert result["inputs"][str(Path(j["input"]["evaluation_dir"])/"gt_points.npz")]==j["input"]["artifact_sha256"]["gt_points.npz"]
        atomic_json(path,dict(index_row(result),dataset=ds,sid=sid,mode=mode,plan_hash=plan["hash"]))
        print(ds,sid,mode,flush=True)


if __name__=="__main__":
    import fcntl
    import time
    overlap=sys.argv[1:]==["overlap"]
    with (CONTROL/"eval-handoff.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB if overlap else fcntl.LOCK_SH)
        if overlap:
            while read_json(CONTROL/"state.json")["phase"].startswith("inference-"):
                main(0,1,True)
                time.sleep(15)
        else:main(int(sys.argv[1]),int(sys.argv[2]))
