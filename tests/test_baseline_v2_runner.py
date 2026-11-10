from pathlib import Path
import pytest

from scripts.run_baseline_v2 import pending_inputs, record_failures, terminal
from wt.experiment import atomic_json, read_json, run_directory


def test_terminal_failures_count_attempts_and_preserve_evidence(tmp_path):
    sample = {"sample_id": "asset"}
    root = tmp_path / "experiment"
    directory = run_directory(root, "asset", "pixal3d", "resolution1024-v1", 43)
    atomic_json(directory / "run.json", {"status": "failed", "error": "test"})
    (directory / "inference.log").write_text("failed inference evidence")
    control = tmp_path / "control"
    record_failures(root, [sample], "pixal", 43, control, 1)
    assert not terminal(directory)
    assert pending_inputs(root, [sample], "pixal", 43) == [sample]
    record_failures(root, [sample], "pixal", 43, control, 2)
    assert terminal(directory)
    assert pending_inputs(root, [sample], "pixal", 43) == []
    history = read_json(directory / "attempt_history.json")
    assert len(history) == 2
    assert (Path(history[0]["evidence"]) / "inference.log").read_text() == "failed inference evidence"


def test_unattempted_candidates_remain_pending(tmp_path):
    sample = {"sample_id": "asset"}
    directory = run_directory(tmp_path, "asset", "pixal3d", "resolution1024-v1", 43)
    atomic_json(directory / "run.json", {"status": "planned"})
    record_failures(tmp_path, [sample], "pixal", 43, tmp_path / "control", 1)
    assert not terminal(directory)
    assert not (directory / "attempt_history.json").exists()
    assert pending_inputs(tmp_path, [sample], "pixal", 43) == [sample]


def test_terminal_marker_rejects_changed_inference_state(tmp_path):
    sample = {"sample_id": "asset"}
    directory = run_directory(tmp_path, "asset", "pixal3d", "resolution1024-v1", 43)
    atomic_json(directory / "run.json", {"status": "failed"})
    record_failures(tmp_path, [sample], "pixal", 43, tmp_path / "control", 1)
    record_failures(tmp_path, [sample], "pixal", 43, tmp_path / "control", 2)
    atomic_json(directory / "run.json", {"status": "running"})
    with pytest.raises(ValueError, match="Terminal inference state changed"):
        terminal(directory)


def test_model_initialization_failure_requires_recovery(tmp_path):
    sample = {"sample_id": "asset"}
    directory = run_directory(tmp_path, "asset", "pixal3d", "resolution1024-v1", 43)
    atomic_json(directory / "run.json", {"status": "failed", "error": "TRELLIS initialization failed"})
    with pytest.raises(RuntimeError, match="Model initialization failed"):
        record_failures(tmp_path, [sample], "pixal", 43, tmp_path / "control", 1)
    assert not terminal(directory)


def test_memory_policy_candidates_use_a_separate_serial_phase(tmp_path):
    from scripts.run_baseline_v2 import jobs
    inputs = [{"sample_id": "ordinary"}, {"sample_id": "large"}]
    atomic_json(tmp_path / "baseline_manifest.json", {
        "memory_candidates": [["large", "wt_trellis2"]]})
    ordinary = jobs(tmp_path, inputs, "baseline", 43)
    bounded = jobs(tmp_path, inputs, "memory", 43)
    assert len(ordinary) == 5
    assert len(bounded) == 1
    assert bounded[0][0]["sample_id"] == "large"
    assert bounded[0][1] == "wt_trellis2"
    assert not ({str(row[3]) for row in ordinary} & {str(row[3]) for row in bounded})


@pytest.mark.parametrize("save_multiview", [False, True])
def test_queue_includes_source_seed_and_forwards_render_option(tmp_path, monkeypatch, save_multiview):
    from types import SimpleNamespace
    from scripts import run_baseline_v2 as runner

    config = tmp_path / "config.json"
    atomic_json(config, {"seeds": list(range(42, 50)), "report_single_seed": 42})
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    args = SimpleNamespace(config=config, seeds=[43], workers=2,
                           experiment=tmp_path / "new", source_experiment=tmp_path / "source",
                           save_multiview_renders=save_multiview)
    assert runner.run_queue(args) == 0
    evaluation_calls = [command for command in calls if "examples.evaluate_baseline_v2" in command]
    assert [command[command.index("--seeds") + 1] for command in evaluation_calls] == ["42", "43"]
    assert calls[0] == evaluation_calls[0]
    assert len(calls) == 5
    assert all(("--save-multiview-renders" in command) == save_multiview for command in evaluation_calls)
    assert (args.experiment / "evaluation-seed-42.json").is_file()
    assert (args.experiment / "evaluation-seed-43.json").is_file()
