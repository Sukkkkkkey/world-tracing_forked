import pytest

from examples.report_camera_ablation import delta_cell, direction, verify_complete


def test_report_rejects_incomplete_evaluation_before_any_document_write():
    with pytest.raises(ValueError, match="complete audited"):
        verify_complete({"status": "partial"}, {"status": "running"})
    with pytest.raises(ValueError, match="Same-runtime"):
        verify_complete({"status": "complete"}, {"status": "complete"})


def test_report_intervals_keep_uncertain_and_directional_changes_distinct():
    stat={"delta": {"n": 99, "mean": -.005, "ci95": [-.01, .001]}}
    assert "包含零" in direction(stat)
    assert "n=99" in delta_cell(stat)
    stat["delta"]["ci95"]=[-.01, -.001]
    assert "下降" in direction(stat)
    stat["delta"]["ci95"]=[.001, .01]
    assert "上升" in direction(stat)
    assert direction(None) == "没有足够有效配对"
