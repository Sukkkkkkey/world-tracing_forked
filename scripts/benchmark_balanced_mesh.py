"""Retest mesh concurrency with sample-balanced workers after the strided trial."""
import datetime
import fcntl
import os
from pathlib import Path
import shutil
from scripts.benchmark_single_gpu import ROOT,REPO,read,write,trial

def main():
    with (REPO/'.runtime/recovery-gpu.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        previous=Path(read(ROOT/'latest.json')['report'])
        report=read(previous)
        assert report['status']=='completed-awaiting-review'
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        attempt=ROOT/('balanced-'+stamp)
        controls=REPO/'.runtime/single-gpu-benchmark'/('balanced-'+stamp)
        attempt.mkdir(parents=True);controls.mkdir(parents=True)
        source=previous.parent/'mesh-1/worker-0/result.json'
        destination=attempt/'mesh-1/worker-0/result.json'
        destination.parent.mkdir(parents=True);shutil.copyfile(source,destination)
        os.environ['WT_BENCHMARK_ASSIGNMENT']='sample'
        for script in ('benchmark_single_gpu.py','benchmark_balanced_mesh.py'):
            shutil.copyfile(REPO/'scripts'/script,attempt/script)
        write(attempt/'plan.json',dict(parent_report=str(previous),assignment='disjoint complete sample groups',
            rationale='The strided workers held all native jobs in one process; worker wall times were 1190 versus 350 seconds.'))
        value=trial('mesh',2,attempt,controls)
        baseline=next(t for t in report['trials'] if t['kind']=='mesh' and t['count']==1)
        result=dict(status='completed-awaiting-review',trial=value,baseline=baseline,
            speedup=baseline['wall_seconds']/value['wall_seconds'] if value['status']=='completed' else None,
            source_report=str(previous),attempt=str(attempt))
        write(attempt/'report.json',result);write(ROOT/'balanced-latest.json',dict(report=str(attempt/'report.json')))
        print(result,flush=True)
        assert value['status']=='completed' and value['all_exact']

if __name__=='__main__':main()
