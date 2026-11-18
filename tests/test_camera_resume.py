import json
import sys
from pathlib import Path

from scripts import continue_camera_ablation


def test_resume_reuses_initial_audit_after_results_have_expanded(tmp_path, monkeypatch):
    control = tmp_path / "control"
    support = tmp_path / "support"
    (control / "formal-v2").mkdir(parents=True)
    support.mkdir()
    document = tmp_path / "report.md"
    document.write_text("report")
    def save(path, value):
        path.write_text(json.dumps(value))
    save(support / "manifest.json", {"files": {}})
    save(control / "formal-first-batch.status.json", {"status": "passed"})
    save(control / "checkpoint-audit.json", {"status": "passed", "checked_stages": 72})
    save(control / "formal-v2/execution.json", {"source_revision": "fixed"})
    save(control / "formal-v2/state.json", {"status": "complete"})
    commands = []
    monkeypatch.setattr(continue_camera_ablation.subprocess, "run",
                        lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(sys, "argv", ["continue", "--control", str(control),
                                    "--support", str(support), "--document", str(document)])
    continue_camera_ablation.main()
    scripts = [Path(command[2]).name for command in commands]
    assert scripts == ["run_camera_ablation_parallel_pipeline.py",
                       "analyze_camera_ablation.py", "report_camera_ablation.py"]
    assert json.loads((control / "checkpoint-resume.json").read_text())["status"] == "passed"
    assert json.loads((control / "continuation-state.json").read_text())["phase"] == "report_written"
