"""Evaluation viewer identity, provenance, aggregation and GUI regressions."""
from copy import deepcopy
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
import viser

from viewer_utils.evaluation import load_evaluation
from viewer_utils.evaluation_panel import Comparison, EvaluationPanel, Metric, metric_table, number
from wt.experiment import file_digest


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def candidate(root, sample="a", method="wt", config="defaults", seed=42, stage="points"):
    return dict(sample_id=sample, method=method, config_id=config, seed=seed, stage=stage,
                source_directory=str(root / "samples" / sample / method / config / f"seed-{seed:04d}"))


def result(row, value=0.2):
    frame = dict(image_metric_region="full_frame",
                 metrics=dict(depth_mae=value, depth_absrel=value, normal_rmse=value,
                              depth_image_rmse=value, silhouette_iou=1.0))
    return dict(row, revision="revision", status="complete",
                inputs={str(Path(row["source_directory"]) / "prediction.npz"): "prediction",
                        "/dataset/gt_depth.npz": "gt"},
                shape={"cd_euclidean_mean": value, "cd_squared_mean": value * value},
                regions={"visible": {"status": "complete",
                                     "metrics": {"cd_euclidean_mean": value}}},
                comparisons={"surfel": {
                    "input": frame,
                    "multiview": {
                        "views": [deepcopy(frame) for _ in range(30)],
                        "metrics": [dict(metric="normal_rmse", value=value, status="complete",
                                         valid_views=30, total_views=30)]}}})


def fixture(tmp_path, records=None, pending=()):
    root, evaluation = tmp_path / "experiment", tmp_path / "evaluation"
    root.mkdir(exist_ok=True)
    if records is None:
        records = [result(candidate(root, "a"), 0), result(candidate(root, "b"), 0.4)]
    entries = []
    for i, record in enumerate(records):
        path = write(evaluation / f"result-{i}.json", record)
        entries.append({name: record[name] for name in
                        ("sample_id", "method", "config_id", "seed", "stage", "source_directory", "status")})
        entries[-1].update(result_path=str(path), result_sha256=file_digest(path))
    planned = [{key: row[key] for key in
                ("sample_id", "method", "config_id", "seed", "stage", "source_directory")}
               for row in entries] + list(pending)
    seeds = sorted({r["seed"] for r in planned})
    config = dict(dataset="test-data", seeds=seeds)
    write(evaluation / "plan.json", dict(candidates=planned, selected_seeds=seeds,
                                        config=config, mode="formal"))
    write(evaluation / "index.json", dict(revision="revision", config=config, results=entries))
    write(root / "baseline_evaluation.json",
          dict(directory=str(evaluation), revision="revision",
               index_sha256=file_digest(evaluation / "index.json")))
    return root, evaluation, entries


def test_full_plan_denominator_and_zero_values(tmp_path):
    root = tmp_path / "experiment"
    root, evaluation, entries = fixture(tmp_path, pending=[candidate(root, "c")])
    snapshot = load_evaluation(root)
    assert (snapshot.evaluated, snapshot.total) == (2, 3)
    key = ("a", "wt", "defaults", 42, "points")
    assert snapshot.cell(key, entries[0]["source_directory"], "shape.cd_euclidean_mean") == (0, 0.2, 2, 3, "")
    assert snapshot.cell(("c", *key[1:]), candidate(root, "c")["source_directory"],
                         "shape.cd_euclidean_mean") == (None, 0.2, 2, 3, "待评测")
    assert "当前有效样本均值" in EvaluationPanel.description(snapshot)


def test_configs_seeds_stages_and_sources_are_isolated(tmp_path):
    root = tmp_path / "experiment"
    rows = [candidate(root, config="a"), candidate(root, config="b"),
            candidate(root, config="a", seed=43),
            candidate(root, method="trellis2", config="a", stage="glb"),
            candidate(root, method="trellis2", config="a", stage="decoded")]
    root, evaluation, entries = fixture(tmp_path, [result(row, i) for i, row in enumerate(rows)])
    snapshot = load_evaluation(root)
    for i, row in enumerate(rows):
        key = tuple(row[k] for k in ("sample_id", "method", "config_id", "seed", "stage"))
        assert snapshot.cell(key, row["source_directory"], "shape.cd_euclidean_mean")[:4] == (i, i, 1, 1)
        assert snapshot.cell(key, "/other/source", "shape.cd_euclidean_mean")[-1] == "预测来源目录不匹配"


def test_empty_region_and_incomplete_multiview(tmp_path):
    root = tmp_path / "experiment"
    record = result(candidate(root))
    record["regions"]["visible"] = {
        "status": "empty_prediction", "metrics": {"recall@0.01": 0, "f@0.01": 0, "cd_euclidean_mean": None}}
    record["comparisons"]["surfel"]["multiview"]["metrics"][0]["valid_views"] = 29
    root, evaluation, entries = fixture(tmp_path, [record])
    snapshot = load_evaluation(root)
    values = next(iter(snapshot.records.values())).values
    assert values["regions.visible.f@0.01"] == 0
    assert "regions.visible.cd_euclidean_mean" not in values
    assert "surfel.multiview.normal_rmse" not in values


def review(evaluation, entry, name, comparison):
    report = dict(status="passed", evaluation_revision="revision",
                  index_sha256=file_digest(evaluation / "index.json"),
                  config={"image_metric_region": "full_frame"},
                  records=[dict(entry, source_files={entry["result_path"]: entry["result_sha256"]},
                                comparisons=comparison)])
    return write(evaluation / name, report)


def test_review_overlay_and_old_image_metrics(tmp_path):
    root = tmp_path / "experiment"
    record = result(candidate(root))
    del record["comparisons"]["surfel"]["input"]["image_metric_region"]
    root, evaluation, entries = fixture(tmp_path, [record])
    snapshot = load_evaluation(root)
    assert "surfel.input.normal_rmse" not in next(iter(snapshot.records.values())).values
    comparison = {"surfel": {"input": {"image_metric_region": "full_frame",
                                      "metrics": {"normal_rmse": 0.3, "depth_mae": 0.5}}}}
    review(evaluation, entries[0], "render_image_fullframe_review.json", comparison)
    review(evaluation, entries[0], "visible_depth_direct_review.json",
           {"surfel": {"input": {"metrics": {"depth_mae": 0.7, "depth_absrel": 0.8}}}})
    snapshot = load_evaluation(root)
    values = next(iter(snapshot.records.values())).values
    assert values["surfel.input.normal_rmse"] == 0.3
    assert values["surfel.input.depth_mae"] == 0.7
    assert values["surfel.input.depth_absrel"] == 0.8
    assert not snapshot.warnings


@pytest.mark.parametrize("field,value", [("index_sha256", "wrong"), ("evaluation_revision", "wrong"),
                                        ("status", "failed")])
def test_mismatched_review_is_reported_without_using_its_values(tmp_path, field, value):
    root, evaluation, entries = fixture(tmp_path)
    path = review(evaluation, entries[0], "visible_depth_direct_review.json",
                  {"surfel": {"input": {"metrics": {"depth_mae": 99}}}})
    data = json.loads(path.read_text())
    data[field] = value
    write(path, data)
    snapshot = load_evaluation(root)
    assert snapshot.warnings
    assert next(iter(snapshot.records.values())).values["surfel.input.depth_mae"] == 0


@pytest.mark.parametrize("kind", ["gso", "ood"])
def test_l0_review_formats_and_failed_fit(tmp_path, kind):
    root, evaluation, entries = fixture(tmp_path)
    rows = []
    for index, entry in enumerate(entries):
        row = dict(sample_id=entry["sample_id"], l0_ssi={
            "status": "complete" if index == 0 else "failed", "mae": 0,
            "reason": "Nonpositive scale" if index else ""})
        if kind == "gso":
            row.update(result_path=entry["result_path"], result_sha256=entry["result_sha256"],
                       l0_source_sha256=file_digest(write(
                           Path(entry["source_directory"]) / "depth_fit.json", row["l0_ssi"])))
        else:
            row["source_files"] = {
                str(Path(entry["source_directory"]) / "prediction.npz"): "prediction",
                "/dataset/gt_depth.npz": "gt"}
        rows.append(row)
    name = "visible_depth_review.json" if kind == "gso" else "visible_depth_l0_review.json"
    write(evaluation / name, dict(status="passed", records=rows))
    snapshot = load_evaluation(root)
    assert not snapshot.warnings
    assert snapshot.means[("wt", "defaults", 42, "points")]["l0_ssi.mae"] == (0, 1)
    key = ("b", "wt", "defaults", 42, "points")
    assert snapshot.cell(key, entries[1]["source_directory"], "l0_ssi.mae")[-1] == "Nonpositive scale"


def test_bad_result_digest_and_wrong_experiment_fail(tmp_path):
    root, evaluation, entries = fixture(tmp_path)
    with pytest.raises(ValueError, match="来源"):
        load_evaluation(tmp_path / "other", evaluation)
    Path(entries[0]["result_path"]).write_text("{}")
    with pytest.raises(ValueError, match="摘要"):
        load_evaluation(root)


def test_formatting_and_native_wt_state(tmp_path):
    assert number(0) == "0"
    assert number(None) == "—"
    assert number(-0.021, "%", difference=True) == "-2.10pp"
    assert number(0.5, "%") == "50.00%"
    root, evaluation, entries = fixture(tmp_path)
    snapshot = load_evaluation(root)
    key = ("a", "wt", "defaults", 42, "points")
    table = metric_table(snapshot, [Comparison(key, Path(entries[0]["source_directory"]), "WT · points")],
                         "native.input.", Metric("depth_mae", "MAE", "D"))
    assert "不适用 Native mesh" in table
    assert "| — | — | — | 0/2 |" in table


def wait_for(predicate, timeout=10):
    until = time.monotonic() + timeout
    while not predicate() and time.monotonic() < until:
        time.sleep(0.01)
    assert predicate()


def test_panel_switch_and_refresh_keep_handles(tmp_path):
    root, evaluation, entries = fixture(tmp_path)
    server = viser.ViserServer(host="127.0.0.1", port=0, verbose=False)
    tab = server.gui.add_tab_group().add_tab("评测")
    panel = EvaluationPanel(server.gui, tab, root, threading.RLock())
    try:
        wait_for(lambda: panel.snapshot is not None)
        def select(index):
            entry = entries[index]
            panel.select(entry["sample_id"], [SimpleNamespace(
                method=entry["method"], config_id=entry["config_id"], seed=entry["seed"],
                directory=Path(entry["source_directory"]))], "glb")
        select(0)
        group = panel.tables[("Geometry（whole & visible）", "Whole", "cd_euclidean_mean")]
        assert "| 0 | 0.2 | -0.2 | 2/2 |" in group[1].content
        select(1)
        assert panel.tables[("Geometry（whole & visible）", "Whole", "cd_euclidean_mean")][0] is group[0]
        assert "| 0.4 | 0.2 | +0.2 | 2/2 |" in group[1].content
        panel.representation.value = "Native mesh（补充）"
        wait_for(lambda: "WT 点云不适用" in panel.tables[("Visible depth", "Sim(3) 重渲染", "depth_mae")][1].content)
        panel.refresh()
        wait_for(lambda: panel.snapshot is not None)
        assert panel.tables[("Geometry（whole & visible）", "Whole", "cd_euclidean_mean")][0] is group[0]
    finally:
        panel.close()
        server.stop()


def test_superseded_load_cannot_publish_old_snapshot(tmp_path, monkeypatch):
    from viewer_utils import evaluation_panel
    entered, release = threading.Event(), threading.Event()
    root, evaluation, entries = fixture(tmp_path)
    expected = load_evaluation(root)
    calls = []
    def load(*args):
        calls.append(None)
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=10)
            return None
        return expected
    monkeypatch.setattr(evaluation_panel, "load_evaluation", load)
    server = viser.ViserServer(host="127.0.0.1", port=0, verbose=False)
    panel = EvaluationPanel(server.gui, server.gui.add_tab_group().add_tab("评测"),
                            root, threading.RLock())
    try:
        assert entered.wait(timeout=10)
        panel.refresh()
        release.set()
        wait_for(lambda: panel.snapshot is expected)
        assert "test-data" in panel.header.content
    finally:
        release.set()
        panel.close()
        server.stop()


def test_failed_and_nonfinite_results_do_not_bias_means(tmp_path):
    root = tmp_path / "experiment"
    a, b = result(candidate(root, "a"), 0), result(candidate(root, "b"), 9)
    b["status"] = "failed"
    a["shape"]["cd_squared_mean"] = float("nan")
    root, evaluation, entries = fixture(tmp_path, [a, b])
    snapshot = load_evaluation(root)
    assert snapshot.means[("wt", "defaults", 42, "points")]["shape.cd_euclidean_mean"] == (0, 1)
    assert "shape.cd_squared_mean" not in snapshot.means[("wt", "defaults", 42, "points")]
    assert snapshot.cell(("b", "wt", "defaults", 42, "points"),
                         entries[1]["source_directory"], "shape.cd_euclidean_mean")[-1] == "评测失败"


def test_bad_review_result_hash_rejects_whole_overlay(tmp_path):
    root, evaluation, entries = fixture(tmp_path)
    path = review(evaluation, entries[0], "visible_depth_direct_review.json",
                  {"surfel": {"input": {"metrics": {"depth_mae": 99}}}})
    data = json.loads(path.read_text())
    invalid = deepcopy(data["records"][0])
    invalid.update(entries[1])
    invalid["source_files"] = {entries[1]["result_path"]: "wrong"}
    data["records"].append(invalid)
    write(path, data)
    snapshot = load_evaluation(root)
    assert snapshot.warnings
    assert snapshot.means[("wt", "defaults", 42, "points")]["surfel.input.depth_mae"] == (0.2, 2)


def test_metric_controls_do_not_reload_geometry(tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image
    import viewer

    root, evaluation, entries = fixture(tmp_path)
    write(root / "experiment.json", {"schema_version": 1})
    image = tmp_path / "image.png"
    Image.new("RGB", (16, 16)).save(image)
    for entry in entries:
        source = Path(entry["source_directory"])
        source.mkdir(parents=True)
        np.save(source / "points.npy", np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32))
        write(source / "run.json", {"status": "complete", "artifacts": {"points": {
            "path": "points.npy", "kind": "points", "frame": "camera_rdf"}}})
        write(root / "samples" / entry["sample_id"] / "input.json", {"image": str(image)})
    loaded = []
    original = viewer.read_run_geometry
    def load(run, **kwargs):
        loaded.append(run.sample_id)
        return original(run, **kwargs)
    monkeypatch.setattr(viewer, "read_run_geometry", load)
    server = viser.ViserServer(host="127.0.0.1", port=0, verbose=False)
    browser = viewer.ExperimentViewer(server, root)
    try:
        browser.sample.value = "a"
        wait_for(lambda: "Prepared 100%" in browser.status.content and browser.metrics.snapshot is not None)
        assert loaded == ["a"]
        browser.metrics.representation.value = "Native mesh（补充）"
        wait_for(lambda: "WT 点云不适用" in browser.metrics.tables[("Visible depth", "Sim(3) 重渲染", "depth_mae")][1].content)
        assert loaded == ["a"]
        browser.sample.value = "b"
        wait_for(lambda: "Prepared 100%" in browser.status.content and loaded == ["a", "b"])
        assert "样本 b" in browser.metrics.sample_label.content
        browser.config.value = ()
        wait_for(lambda: "无方法结果" in browser.metrics.sample_label.content)
    finally:
        browser.close()
        server.stop()


def test_evaluation_flags_require_experiment():
    import viewer
    with pytest.raises(SystemExit):
        viewer.parse_args(["--evaluation", "/evaluation"])


def test_same_metric_compares_methods_in_one_table(tmp_path):
    from viewer_utils.evaluation_panel import comparisons_for
    root = tmp_path / "experiment"
    rows = [
        result(candidate(root, "a"), 0),
        result(candidate(root, "b"), 0.4),
        result(candidate(root, "a", method="trellis2", stage="glb"), 1),
        result(candidate(root, "b", method="trellis2", stage="glb"), 3),
    ]
    root, evaluation, entries = fixture(tmp_path, rows)
    runs = [SimpleNamespace(method=row["method"], config_id=row["config_id"],
                            seed=row["seed"], directory=Path(row["source_directory"]))
            for row in (entries[2], entries[0])]
    comparisons = comparisons_for("a", runs, "glb")
    table = metric_table(load_evaluation(root), comparisons, "shape.",
                         Metric("cd_euclidean_mean", "CD-L1", "D"))
    assert "| 方法 | 本样本 | 均值 | Δ | n/N |" in table
    assert "| WT · points | 0 | 0.2 | -0.2 | 2/2 |" in table
    assert "| TRELLIS.2 · glb | 1 | 2 | -1 | 2/2 |" in table
    assert table.index("WT · points") < table.index("TRELLIS.2 · glb")


def test_multiple_configs_and_seeds_have_distinct_comparison_rows(tmp_path):
    from viewer_utils.evaluation_panel import comparisons_for
    root = tmp_path / "experiment"
    candidates = [candidate(root, config="first"), candidate(root, config="second"),
                  candidate(root, config="first", seed=43)]
    root, evaluation, entries = fixture(tmp_path, [result(row, i) for i, row in enumerate(candidates)])
    runs = [SimpleNamespace(method=row["method"], config_id=row["config_id"],
                            seed=row["seed"], directory=Path(row["source_directory"])) for row in entries]
    comparisons = comparisons_for("a", runs, "glb")
    assert len({row.label for row in comparisons}) == 3
    assert any("first / seed 43" in row.label for row in comparisons)
    table = metric_table(load_evaluation(root), comparisons, "shape.",
                         Metric("cd_euclidean_mean", "CD-L1", "D"))
    assert table.count("| 1/1 |") == 3


def test_metric_sections_filter_supplements_and_follow_mesh_stage(tmp_path):
    root = tmp_path / "experiment"
    rows = [result(candidate(root)),
            result(candidate(root, method="trellis2", stage="glb"), 0.6),
            result(candidate(root, method="trellis2", stage="decoded"), 0.8)]
    root, evaluation, entries = fixture(tmp_path, rows)
    runs = [SimpleNamespace(method=row["method"], config_id=row["config_id"],
                            seed=row["seed"], directory=Path(row["source_directory"]))
            for row in entries[:2]]
    server = viser.ViserServer(host="127.0.0.1", port=0, verbose=False)
    panel = EvaluationPanel(server.gui, server.gui.add_tab_group().add_tab("评测"), root, threading.RLock())
    try:
        wait_for(lambda: panel.snapshot is not None)
        panel.select("a", runs, "glb")
        assert len(panel.categories) == 3
        key = ("Geometry（whole & visible）", "Whole", "cd_euclidean_mean")
        folder, content = panel.tables[key]
        assert "WT · points" in content.content and "TRELLIS.2 · glb" in content.content
        ssi = panel.tables[("Visible depth", "WT L0＋SSI 补充", "mae")]
        rgb = panel.tables[("Input view & multi-view", "GLB 输入 RGB", "psnr")]
        assert ssi[0].visible and rgb[0].visible
        assert "TRELLIS" not in ssi[1].content
        assert "WT · points" not in rgb[1].content
        panel.select("a", runs, "decoded")
        assert panel.tables[key][0] is folder
        assert "TRELLIS.2 · decoded | 0.8 |" in content.content
        assert not rgb[0].visible
        panel.select("a", runs[1:], "decoded")
        assert "WT · points" not in content.content
        assert not ssi[0].visible
    finally:
        panel.close()
        server.stop()
