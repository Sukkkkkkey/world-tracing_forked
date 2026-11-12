"""Regression checks for stage-owned resource monitoring in the OOD pipeline."""
import json
import sys

import pytest

from scripts import run_ood_pipeline


@pytest.mark.parametrize("exit_code", [0, 3])
def test_stage_delegates_resource_monitoring(tmp_path, monkeypatch, exit_code):
    def unexpected_monitor(*args, **kwargs):
        raise AssertionError("The outer runner must delegate this stage's monitoring")

    monkeypatch.setattr(run_ood_pipeline, "monitor", unexpected_monitor)
    command = [sys.executable, "-c", f"print('stage executed'); raise SystemExit({exit_code})"]
    if exit_code:
        with pytest.raises(RuntimeError, match=f"exit {exit_code}"):
            run_ood_pipeline.run_stage(command, tmp_path, monitor_resources=False)
    else:
        run_ood_pipeline.run_stage(command, tmp_path, monitor_resources=False)
    result = json.loads((tmp_path / "exit.json").read_text())
    assert result == {"worker_exits": [exit_code], "monitor": "delegated-to-stage"}
    assert "stage executed" in (tmp_path / "run.log").read_text()

