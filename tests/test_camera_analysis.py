
import numpy as np

from examples.analyze_camera_ablation import common_visible_metrics, paired_values
from evaluation.visibility import INVALID, REGIONS


def test_common_visibility_uses_nearest_full_gt_before_restriction():
    gt = np.array([[0., 0, 0], [1., 0, 0], [2., 0, 0]])
    a = np.array([REGIONS["visible"], REGIONS["visible"], REGIONS["occluded"]])
    b = np.array([REGIONS["visible"], REGIONS["occluded"], REGIONS["visible"]])
    pred = np.array([[0., 0, 0], [1.01, 0, 0], [2.01, 0, 0]])
    result = common_visible_metrics(pred, gt, a, b)
    assert result["prediction_points"] == result["gt_points"] == 1
    assert result["metrics"]["cd_euclidean_mean"] == 0
    assert result["common_fraction_of_first_visible"] == .5
    a[1] = INVALID
    assert common_visible_metrics(pred, gt, a, b)["status"] == "invalid_visibility"


def test_paired_summary_uses_only_each_metrics_common_valid_assets():
    rows = [
        {"sample_id": "a", "category": "one", "control": {"x": 1, "y": 3}, "matched": {"x": 2}},
        {"sample_id": "b", "category": "one", "control": {"x": 3, "y": 5}, "matched": {"x": 1, "y": 1}},
    ]
    result = paired_values(rows, "OOD")
    assert result["x"]["delta"]["mean"] == -.5
    assert result["x"]["delta"]["n"] == 2
    assert result["y"]["delta"]["n"] == 1
    assert result["x"]["category_bootstrap"]["clusters"] == 1

def test_common_visible_empty_prediction_preserves_protocol_failure_semantics():
    gt = np.array([[0., 0, 0], [2., 0, 0]])
    labels = np.array([REGIONS["visible"], REGIONS["occluded"]])
    result = common_visible_metrics(np.array([[2., 0, 0]]), gt, labels, labels)
    assert result["status"] == "empty_prediction"
    assert result["metrics"]["cd_euclidean_mean"] is None
    assert result["metrics"]["f@0.01"] == 0


def test_method_gap_uses_four_way_valid_intersection_and_keeps_stages_separate():
    from examples.analyze_camera_ablation import method_gap_pairs
    def row(sample, method, stage, control, matched):
        return dict(dataset="GSO", group="B", sample_id=sample, method=method,
                    config_id="defaults-v1", stage=stage, category="box",
                    control_condition="B0", matched_condition="B1",
                    control=control, matched=matched)
    cd="shape.cd_euclidean_mean"
    visible="common_visible.cd_euclidean_mean"
    rows=[
        row("a", "wt", "points", {cd: 10., visible: 4.}, {cd: 6., visible: 3.}),
        row("a", "trellis2", "decoded", {cd: 8., visible: 2.}, {cd: 5.}),
        row("a", "trellis2", "glb", {cd: 9.}, {cd: 7.}),
        row("b", "wt", "points", {cd: 4., visible: 7.}, {cd: 3., visible: 5.}),
        row("b", "trellis2", "decoded", {cd: 3., visible: 3.}, {cd: 4., visible: 2.}),
        row("c", "wt", "points", {cd: 100.}, {cd: 1.}),
    ]
    result={row["stage"]:row["metrics"] for row in method_gap_pairs(rows)}
    assert result["decoded"][cd]["control"]["mean"] == 1.5
    assert result["decoded"][cd]["matched"]["mean"] == 0.
    assert result["decoded"][cd]["delta"]["mean"] == -1.5
    assert result["decoded"][cd]["sample_ids"] == ["a", "b"]
    assert result["decoded"][visible]["sample_ids"] == ["b"]
    assert result["decoded"][visible]["delta"]["mean"] == -1.
    assert result["glb"][cd]["sample_ids"] == ["a"]
    assert result["glb"][cd]["delta"]["mean"] == -2.


def test_method_gap_rejects_mismatched_conditions():
    import pytest
    from examples.analyze_camera_ablation import method_gap_pairs
    row=dict(dataset="OOD", group="A", sample_id="a", config_id="defaults-v1",
             category="one", control_condition="A0", matched_condition="A1",
             control={"shape.cd_euclidean_mean": 2.}, matched={"shape.cd_euclidean_mean": 1.})
    with pytest.raises(ValueError, match="conditions"):
        method_gap_pairs([dict(row, method="wt", stage="points"),
                          dict(row, method="trellis2", stage="decoded", control_condition="B0")])

def test_reduced_cohort_and_reused_control_are_not_reported_as_independent_repeat(tmp_path):
    from examples.analyze_camera_ablation import analyze
    state = dict(experiments={}, phase="paused", source_revision="fixture",
                 planned_assets_per_dataset=50, condition_aliases={"B0":"A0"})
    result = analyze(state, tmp_path)
    assert result["planned_assets_per_dataset"] == 50
    assert result["condition_aliases"] == {"B0":"A0"}
    assert not any(p["group"] == "implementation_control" for p in result["pairs"])
    document = (tmp_path/"camera_analysis.md").read_text()
    assert "完整 50 资产" in document
    assert "不构成独立重跑控制" in document
