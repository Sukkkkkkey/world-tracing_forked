"""Single-writer resumable oracle workflow, including GLB evaluation and reporting."""
import fcntl
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.prepare_stage1_oracle import CONTROL, FORMAL, REPO
from wt.experiment import atomic_json,read_json

FROZEN=FORMAL.parent/"hybrid-ablation-20261119-pilot20-bs4-r2/pause-for-camera/evaluation-source"


def state(phase,**fields):
    atomic_json(CONTROL/"state.json",dict(phase=phase,pid=os.getpid(),time=time.time(),**fields))


def run(name,program,args,eval_env=False):
    env=dict(os.environ,OMP_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1",MKL_NUM_THREADS="1")
    cwd=FROZEN if eval_env else REPO
    env["PYTHONPATH"]=os.pathsep.join([str(cwd),str(REPO),env["WT_TRELLIS2_ROOT"]])
    with (CONTROL/(name+".log")).open("a") as log:
        child=subprocess.Popen([sys.executable,"-Bu",str(REPO/"scripts"/program),*map(str,args)],env=env,cwd=cwd,stdout=log,stderr=subprocess.STDOUT)
        atomic_json(CONTROL/(name+"-launch.json"),dict(pid=child.pid,time=time.time()))
        if child.wait():raise RuntimeError(f"{name} failed; see {log.name}")


def main():
    with (CONTROL/"controller.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            if not (CONTROL/"smoke.json").is_file():
                state("smoke")
                run("replay","run_stage1_oracle.py",["smoke"])
            scope=read_json(CONTROL/"B-primary.json")
            for mode in (scope["primary"],):
                state("inference-"+mode)
                marker=CONTROL/mode/"inference-complete.json"
                if not marker.is_file():run("infer-"+mode,"run_stage1_oracle.py",[mode])
                assert read_json(marker)["complete"]==200
            state("evaluation",lanes=12)
            def lane(i):
                time.sleep(i*8)
                run(f"eval-{i:02}","evaluate_stage1_oracle.py",[i,12],True)
            with ThreadPoolExecutor(12) as p:list(p.map(lane,range(12)))
            state("report")
            run("report","report_stage1_oracle.py",[])
            state("complete",primary="B",inference_B=200,reference_A=len(scope["reference_A"]),evaluation=200+len(scope["reference_A"]),paired_assets=200)
        except Exception:
            state("needs_attention",error=traceback.format_exc())
            raise


if __name__=="__main__":main()
