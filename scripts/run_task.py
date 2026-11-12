"""Run a recoverable project job and persist PID, command, timestamps and exit code."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import traceback

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", required=True)
    p.add_argument("--log-dir", type=Path, required=True)
    p.add_argument("--artifact-dir", type=Path)
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command:
        p.error("a command is required")
    root = Path(__file__).resolve().parents[1]
    a.log_dir.mkdir(parents=True, exist_ok=True)
    status_path = a.log_dir / (a.name + ".status.json")
    log_path = a.log_dir / (a.name + ".log")
    status = dict(name=a.name, status="running", pid=os.getpid(), command=command,
                  cwd=str(root), started=now(), log=str(log_path),
                  environment={key: os.environ.get(key) for key in ('CUDA_VISIBLE_DEVICES', 'PYTHONHASHSEED', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'HF_HUB_OFFLINE')})
    def save():
        temporary = status_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(status, indent=2) + "\n")
        temporary.replace(status_path)
        if a.artifact_dir:
            a.artifact_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(status_path, a.artifact_dir / status_path.name)
    save()
    code = 1
    try:
        with log_path.open("a", buffering=1) as log:
            child = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
            status["child_pid"] = child.pid
            save()
            code = child.wait()
    except Exception:
        status["exception"] = traceback.format_exc()
    status.update(status="passed" if code == 0 else "failed", exit_code=code, finished=now())
    save()
    (a.log_dir / (a.name + ".exit")).write_text(str(code) + "\n")
    if a.artifact_dir:
        shutil.copyfile(log_path, a.artifact_dir / log_path.name)
        shutil.copyfile(a.log_dir / (a.name + ".exit"), a.artifact_dir / (a.name + ".exit"))
    return code

if __name__ == "__main__":
    sys.exit(main())
