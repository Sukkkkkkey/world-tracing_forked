import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from examples.export_experiments import export
from examples.prepare_gso_inventory import asset_seed, prepare, split_ids


def test_fixed_disjoint_split_and_order_independent_seeds():
    ids = [f'asset_{i:04d}' for i in range(1030)]
    first = split_ids(ids)
    assert first == split_ids(ids[::-1])
    assert [len(first[k]) for k in ('pilot', 'eval100', 'reserve')] == [10, 100, 920]
    assert len(set(sum(first.values(), []))) == 1030
    assert asset_seed('view', 'chair') == asset_seed('view', 'chair')
    assert asset_seed('view', 'chair') != asset_seed('gt_eval', 'chair')
    with pytest.raises(ValueError):
        split_ids(ids[:100])


def test_workbook_migrates_notes_and_retains_manual_edits_without_paper_sheets(tmp_path):
    root = tmp_path / 'experiments' / '20261013-R1-object-qual-v1'
    run = root / 'samples/asset/wt/defaults-v1/seed-0042'
    run.mkdir(parents=True)
    (root / 'experiment.json').write_text(json.dumps(dict(experiment_id=root.name)))
    (run.parent.parent.parent / 'input.json').write_text(json.dumps(dict(sample_id='asset', image='image.png', sha256='abc')))
    (run / 'run.json').write_text(json.dumps(dict(sample_id='asset',method='wt',config_id='defaults-v1',config_hash='c', seed=42,status='failed',error='=dangerous-formula')))
    (run / 'config.json').write_text(json.dumps(dict(parameters={},provenance={})))
    out = tmp_path / 'experiments.xlsx'
    book = Workbook()
    sheet = book.active
    sheet.title = 'Experiments'
    sheet.append(['experiment_id', 'status', 'runs', 'complete', 'failed', 'output', 'updated_at', '总体结论', '其他细节'])
    sheet.append([root.name, 'complete', 1, 1, 0, str(root), 'old', '保留人工结论', '保留人工细节'])
    book.create_sheet('PaperComparison')['A1'] = 'paper_value'
    book.save(out)
    book.close()
    export(root.parent, out)
    book = load_workbook(out)
    assert book.sheetnames == ['实验总览']
    sheet = book.active
    assert sheet['H6'].value == '保留人工结论\n\n保留人工细节'
    assert '无配套 GT' in sheet['J6'].value
    assert '1 执行失败' in sheet['G6'].value
    sheet['I6'] = '=literal reviewer note'
    sheet['I6'].data_type = 's'
    sheet['H6'] = '更新后的总体结论'
    book.save(out)
    book.close()
    export(root.parent, out)
    book = load_workbook(out)
    assert book.active['H6'].value == '更新后的总体结论'
    assert book.active['I6'].value == '=literal reviewer note'
    assert book.active['I6'].data_type == 's'
    book.close()


def test_workbook_distinguishes_zero_failure_na_and_recomputes_paired_cohort(tmp_path):
    root = tmp_path / 'experiments' / 'R2-quant'
    root.mkdir(parents=True)
    (root / 'experiment.json').write_text(json.dumps(dict(experiment_id=root.name)))
    for method in ['wt', 'trellis2', 'wt_trellis2']:
        for sample in ['a', 'b']:
            run = root / f'samples/{sample}/{method}/defaults-v1/seed-0042'
            run.mkdir(parents=True)
            (run / 'run.json').write_text(json.dumps(dict(sample_id=sample, method=method, config_id='defaults-v1',
                config_hash='c', seed=42, status='complete')))
            (run / 'config.json').write_text(json.dumps(dict(parameters={}, provenance={})))
            status = 'N/A' if method=='trellis2' else ('failed' if method=='wt_trellis2' and sample=='a' else 'complete')
            value = None if status!='complete' else (0.0 if sample=='a' else (1.0 if method=='wt' else 3.0))
            metrics = [dict(protocol_id='gso-depth-ssi-v1', metric=metric, status=status, value=value)
                       for metric in ['mae', 'rmse', 'absrel']]
            metrics += [dict(protocol_id='gso-shape-sim3-v1', metric='cd_euclidean_mean', status='complete', value=0.0)]
            (run / 'metrics.json').write_text(json.dumps(dict(metrics=metrics)))
    out = tmp_path / 'experiments.xlsx'
    audit = tmp_path/'audit.json'
    export(root.parent, out, audit_path=audit)
    book = load_workbook(out)
    assert book.sheetnames == ['实验总览', 'R2_逐样本']
    overview, detail = book.worksheets
    assert overview['K6'].value == 0.0
    assert overview['P6'].value == 0.5  # WT marginal mean uses both samples.
    assert overview['P7'].value == '不适用'
    assert overview['P8'].value == 3.0
    assert overview['O8'].value == '1 / 2'
    assert overview['AC6'].value == 1.0  # Paired cohort is only sample b.
    assert overview['AC8'].value == 3.0
    assert detail['P8'].value == '失败'
    assert list(overview.values)[2:5] == list(detail.values)[2:5]
    assert 'A6:A8' in overview.merged_cells
    assert 'A6:A11' in detail.merged_cells
    assert 'B6:B8' in detail.merged_cells
    assert json.loads(audit.read_text())['numeric_cells_verified'] > 0
    book.close()


def test_workbook_refuses_missing_source_experiments(tmp_path):
    root = tmp_path / 'experiments' / '20261013-R1-object-qual-v1'
    root.mkdir(parents=True)
    (root / 'experiment.json').write_text(json.dumps(dict(experiment_id=root.name)))
    out = tmp_path / 'experiments.xlsx'
    book = Workbook()
    sheet = book.active
    sheet.title = 'Experiments'
    sheet.append(['experiment_id', 'status', 'runs', 'complete', 'failed', 'output', 'updated_at'])
    sheet.append([root.name, 'complete', 120, 120, 0, str(root), 'old'])
    sheet.append(['missing-source', 'complete', 3, 3, 0, '/other', 'old'])
    book.save(out)
    book.close()

    before = out.read_bytes()
    with pytest.raises(ValueError, match='Missing source experiments'):
        export(root.parent, out)
    assert out.read_bytes() == before


def test_workbook_does_not_merge_different_parameters_under_one_config_id(tmp_path):
    root = tmp_path/'experiments'/'R2-config-variants'
    root.mkdir(parents=True)
    (root/'experiment.json').write_text(json.dumps(dict(experiment_id=root.name)))
    for sample, steps, value in [('a',20,0.0),('b',40,1.0)]:
        run = root/f'samples/{sample}/wt/defaults-v1/seed-0042'
        run.mkdir(parents=True)
        (run/'run.json').write_text(json.dumps(dict(sample_id=sample,method='wt',config_id='defaults-v1',seed=42,status='complete')))
        (run/'config.json').write_text(json.dumps(dict(parameters={'wt_steps':steps},provenance={})))
        (run/'metrics.json').write_text(json.dumps(dict(metrics=[dict(protocol_id='gso-shape-sim3-v1',metric='cd_euclidean_mean',status='complete',value=value)])))
    out = tmp_path/'experiments.xlsx'
    export(root.parent,out)
    book = load_workbook(out)
    assert {book.active['K6'].value,book.active['K7'].value} == {0.0,1.0}
    assert all('参数版本' in book.active[f'E{row}'].value for row in [6,7])
    book.close()


def test_archive_traversal_rejected_before_extracting(tmp_path):
    import zipfile
    archive = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('models_orig/../../escape.txt', 'unexpected')
    with pytest.raises(ValueError, match='Unsafe'):
        prepare(archive, tmp_path / 'assets', tmp_path / 'split')
    assert not (tmp_path / 'escape.txt').exists()


def test_asset_means_common_success_and_failed_denominator():
    from evaluation.records import summarize
    records=[]
    for method in ['wt','trellis2','wt_trellis2']:
        for asset in ['a','b']:
            failed=method=='trellis2' and asset=='b'
            records.append(dict(method=method,config_id='defaults-v1',seed=42,protocol_id='gso-shape-sim3-v1',metric='cd_euclidean_mean',
                sample_id=asset,status='failed' if failed else 'complete',value=None if failed else (1 if asset=='a' else 3)))
    summary=summarize(records,{(m,'defaults-v1',42):3 for m in ['wt','trellis2','wt_trellis2']})
    assert all(x['common_count']==1 and x['common_mean']==1 for x in summary)
    trellis=next(x for x in summary if x['method']=='trellis2')
    assert trellis['failed']==1 and trellis['pending']==1 and trellis['failure_rate']==pytest.approx(1/3)
    assert next(x for x in summary if x['method']=='wt')['mean']==2


def test_gso_experiment_gate_rejects_incomplete_raw_data(tmp_path):
    from examples.verify_gso_raw import require_complete
    with pytest.raises(RuntimeError,match='incomplete'):
        require_complete(tmp_path)
    (tmp_path/'COMPLETE.json').write_text(json.dumps(dict(status='complete',assets=100)))
    with pytest.raises(ValueError,match='completeness'):
        require_complete(tmp_path)
