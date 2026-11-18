"""Release the full camera queue only after all first-batch acceptance checks pass."""
import argparse
import fcntl
import subprocess
import sys
import time
import traceback
from pathlib import Path

from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import REPO_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--support", type=Path, required=True)
    parser.add_argument("--document", type=Path, required=True)
    args = parser.parse_args()
    control, support = args.control.resolve(), args.support.resolve()
    lock = (control / ".continuation.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest = read_json(support / "manifest.json")
    def verify_support():
        for name, checksum in manifest["files"].items():
            if file_digest(support / name) != checksum:
                raise ValueError("Frozen analysis/checkpoint support changed")
    def stage(name, command):
        verify_support()
        atomic_json(control / "continuation-state.json", {"status": "running", "phase": name, "command": command})
        with (control / (name + ".log")).open("a", buffering=1) as log:
            subprocess.run(command, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    try:
        atomic_json(control / "continuation-state.json", {"status": "running", "phase": "waiting_first_batch"})
        status_path = control / "formal-first-batch.status.json"
        while True:
            if status_path.exists():
                try:
                    status = read_json(status_path)
                except OSError as exc:
                    if exc.errno != 116:
                        raise
                    time.sleep(1)
                    continue
                if status["status"] == "failed":
                    raise RuntimeError("First batch failed; queue remains stopped")
                if status["status"] == "passed":
                    break
            time.sleep(15)
        checkpoint_path = control / "checkpoint-audit.json"
        resumed = (control / "formal-v2/execution.json").exists()
        checkpoint = read_json(checkpoint_path) if resumed and checkpoint_path.exists() else {}
        if resumed:
            if checkpoint.get("status") != "passed" or checkpoint.get("checked_stages") != 72:
                raise ValueError("Completed first-batch audit record is missing")
            atomic_json(control / "checkpoint-resume.json", {
                "status": "passed", "checkpoint_audit_sha256": file_digest(checkpoint_path),
                "reason": "The first-batch audit already passed before the indexed results expanded",
                "controller_sha256": file_digest(Path(__file__))})
        else:
            stage("checkpoint-audit", [sys.executable, "-uB", str(support / "validate_camera_checkpoint.py"),
                                      "--state", str(control / "formal/state.json"),
                                      "--output", str(control / "checkpoint-audit.json")])
            report = read_json(control / "checkpoint-audit.json")
            if report["status"] != "passed" or report["checked_stages"] != 72:
                raise ValueError("Checkpoint did not pass")
            stage("checkpoint-analysis", [sys.executable, "-uB", str(support / "analyze_camera_ablation.py"),
                                         "--state", str(control / "formal/state.json"),
                                         "--output", str(control / "checkpoint-analysis"), "--include-runtime-control"])
        stage("formal-all", [sys.executable, "-uB", str(support / "run_camera_ablation_parallel_pipeline.py"),
                            "--config", str(support / "camera_ablation_run.json"),
                            "--control", str(control / "formal-v2")])
        state = read_json(control / "formal-v2/state.json")
        if state["status"] != "complete":
            raise ValueError("Formal evaluation did not finish")
        stage("final-analysis", [sys.executable, "-uB", str(support / "analyze_camera_ablation.py"),
                                "--state", str(control / "formal-v2/state.json"),
                                "--output", str(control / "final-analysis"), "--include-runtime-control"])
        stage("final-document", [sys.executable, "-uB", str(support / "report_camera_ablation.py"),
                                 "--analysis", str(control / "final-analysis/camera_analysis.json"),
                                 "--state", str(control / "formal-v2/state.json"),
                                 "--document", str(args.document.resolve()),
                                 "--output", str(control / "final-report")])
        atomic_json(control / "continuation-state.json", {
            "status": "complete", "phase": "report_written",
            "analysis": str(control / "final-analysis/camera_analysis.json"),
            "document": str(args.document.resolve()),
            "document_sha256": file_digest(args.document.resolve())})
    except BaseException:
        atomic_json(control / "continuation-state.json", {
            "status": "failed", "error": traceback.format_exc()})
        raise


if __name__ == "__main__":
    main()
