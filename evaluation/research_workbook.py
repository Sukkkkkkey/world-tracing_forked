"""A research ledger: one overview and one detail sheet per quantitative experiment."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
from zoneinfo import ZoneInfo

from evaluation.xlsx_compat import normalize_comment_parts

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


VERSION = 'research-ledger-v2'
OVERVIEW = '实验总览'
FIRST_ROW = 6
SHAPE, CAMERA, DEPTH = 'gso-shape-sim3-v1', 'gso-camera-native-v1', 'gso-depth-ssi-v1'
METHODS = {'wt': 'WT', 'trellis2': 'TRELLIS.2', 'wt_trellis2': 'WT + TRELLIS.2', 'pixal3d': 'Pixal3D'}
METHOD_ORDER = {name: i for i, name in enumerate(METHODS)}
LEGACY_SHEETS = {'PaperComparison', 'PairedDepth', 'ExecutionRetries', 'Experiments', 'Configs',
                 'Samples', 'Runs', 'Metrics', 'Summary', 'Protocol', 'MetricSummary', 'FourMethodShape'}
HEADERS = ['实验', '数据 / 样本', '研究问题 / 改动', '方法 / 结构', '配置 / 关键参数', '随机种子', '执行进度',
           '总体结论', '配置观察 / 其他细节',
           '有效 / 总数', 'CD-L1 ↓', 'CD-L2 ↓', 'F@0.01 ↑', 'F@0.05 ↑',
           'SSI 有效 / 总数', 'MAE ↓', 'RMSE ↓', 'AbsRel ↓', 'δ1 ↑', 'δ2 ↑', '覆盖率 ↑', '轮廓 IoU ↑',
           '有效 / 总数', 'CD-L1 ↓', 'CD-L2 ↓', 'F@0.01 ↑', 'F@0.05 ↑',
           '共同有效 / 总数', 'MAE ↓', 'RMSE ↓', 'AbsRel ↓', '结果 / 依据']
METRIC_COLUMNS = {
    11: (SHAPE, 'cd_euclidean_mean'), 12: (SHAPE, 'cd_squared_mean'),
    13: (SHAPE, 'f@0.01'), 14: (SHAPE, 'f@0.05'),
    16: (DEPTH, 'mae'), 17: (DEPTH, 'rmse'), 18: (DEPTH, 'absrel'),
    19: (DEPTH, 'delta1'), 20: (DEPTH, 'delta2'),
    21: (DEPTH, 'depth_coverage'), 22: (DEPTH, 'silhouette_iou'),
    24: (CAMERA, 'cd_euclidean_mean'), 25: (CAMERA, 'cd_squared_mean'),
    26: (CAMERA, 'f@0.01'), 27: (CAMERA, 'f@0.05'),
}
KEY_PREFIX, AUTO_PREFIX = '记录键：', '自动摘要：'


def _json(path, sources):
    data = Path(path).read_bytes()
    sources[str(path)] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _comment_field(cell, prefix):
    for line in (cell.comment.text if cell.comment else '').splitlines():
        if line.startswith(prefix):
            return json.loads(line[len(prefix):])
    return None


def _text(cell, value):
    cell.value = value
    if isinstance(value, str):
        cell.data_type = 's'


def collect_experiments(base):
    """Read index/config/metric JSON only; reject ambiguous or corrupt metric records."""
    sources, experiments = {}, []
    for path in sorted(Path(base).glob('*/experiment.json')):
        root, manifest = path.parent, _json(path, sources)
        experiment_id = manifest['experiment_id']
        if experiment_id != root.name:
            raise ValueError(f'Experiment ID/path mismatch: {path}')
        samples = {p.parent.name: _json(p, sources) for p in sorted((root/'samples').glob('*/input.json'))}
        records, seen = [], set()
        for run_path in sorted((root/'samples').glob('*/*/*/seed-*/run.json')):
            sample, method, config, seed_dir = run_path.parent.relative_to(root/'samples').parts
            seed = int(seed_dir[5:])
            run, cfg = _json(run_path, sources), _json(run_path.parent/'config.json', sources)
            for key, value in [('sample_id', sample), ('method', method), ('config_id', config), ('seed', seed)]:
                if key in run and run[key] != value:
                    raise ValueError(f'Run ID/path mismatch ({key}): {run_path}')
            parameters = cfg['parameters']
            parameter_hash = hashlib.sha256(_encoded(parameters).encode()).hexdigest()[:12]
            group = (method, config, seed, parameter_hash)
            identity = (sample, *group)
            if identity in seen:
                raise ValueError(f'Duplicate run: {run_path}')
            seen.add(identity)
            metrics, metric_path = {}, run_path.parent/'metrics.json'
            if metric_path.exists():
                for metric in _json(metric_path, sources)['metrics']:
                    key = (metric['protocol_id'], metric['metric'])
                    if key in metrics:
                        raise ValueError(f'Duplicate metric {key}: {metric_path}')
                    if key not in METRIC_COLUMNS.values():
                        raise ValueError(f'Unmapped metric {key}; extend the ledger columns before exporting: {metric_path}')
                    value = metric.get('value')
                    if metric['status'] == 'complete' and (
                        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    ):
                        raise ValueError(f'Invalid completed metric {key}: {metric_path}')
                    metrics[key] = metric
            records.append(dict(sample=sample, method=method, config=config, seed=seed, group=group,
                                parameters=parameters, run=run, directory=run_path.parent, metrics=metrics,
                                config_path=run_path.parent/'config.json', metric_path=metric_path))
        quantitative = (any(r['metrics'] for r in records)
                        or any(x.get('evaluation_dir') or x.get('ground_truth') for x in samples.values())
                        or manifest.get('kind') == 'quantitative' or '-gso-' in experiment_id)
        groups = defaultdict(list)
        for record in records:
            groups[record['group']].append(record)
        observations_path = root/'observations.json'
        observations = _json(observations_path, sources) if observations_path.exists() else {}
        warnings = []
        if records and manifest.get('status') == 'planned' and all(r['run']['status'] == 'complete' for r in records):
            warnings.append('历史 manifest 状态为 planned；本表按实际 run 记录显示完成情况。')
        if manifest.get('planned_runs') is not None and manifest['planned_runs'] != len(records):
            warnings.append(f'历史计划数 {manifest["planned_runs"]}，实际记录 {len(records)}；不把差额当执行失败。')
        experiments.append(dict(id=experiment_id, root=root, manifest=manifest, samples=samples,
                                records=records, groups=groups, quantitative=quantitative,
                                observations=observations, warnings=warnings))
    return experiments, sources


def _group_order(group):
    method, config, seed, parameter_hash = group
    return (METHOD_ORDER.get(method, 99), config != 'defaults-v1', config, seed, parameter_hash)


def _load_annotations(path):
    annotations = {'conclusions': {}, 'purposes': {}, 'notes': {}, 'links': {}, 'experiments': set()}
    if not path.exists() or not path.stat().st_size:
        return annotations
    book = load_workbook(path)
    try:
        if OVERVIEW in book:
            if book.properties.identifier != VERSION:
                raise ValueError('Unrecognized overview schema; refusing to overwrite')
            if any(not (sheet.sheet_properties.codeName or '').startswith('researchLedger') for sheet in book):
                raise ValueError('Unrecognized custom sheet; refusing to discard it')
            overview = book[OVERVIEW]
            for row in overview.iter_rows(min_row=FIRST_ROW):
                if row[0].value:
                    exp = row[0].value
                    annotations['experiments'].add(exp)
                    annotations['conclusions'][exp] = row[7].value
                    annotations['purposes'][exp] = row[2].value
                    if row[7].hyperlink:
                        annotations['links'][exp] = row[7].hyperlink.target
            for sheet in book:
                for row in sheet.iter_rows(min_row=FIRST_ROW):
                    key = _comment_field(row[4], KEY_PREFIX)
                    if key and row[8].value != _comment_field(row[8], AUTO_PREFIX):
                        annotations['notes'][tuple(key)] = row[8].value
        elif 'Experiments' in book:
            unknown = set(book.sheetnames) - LEGACY_SHEETS
            if unknown:
                raise ValueError(f'Unrecognized custom sheets; refusing to discard: {sorted(unknown)}')
            rows = iter(book['Experiments'].values)
            headers = next(rows)
            for values in rows:
                row = dict(zip(headers, values))
                exp = row['experiment_id']
                annotations['experiments'].add(exp)
                notes = [row.get('总体结论'), row.get('其他细节')]
                annotations['conclusions'][exp] = '\n\n'.join(x for x in notes if x) or None
        elif not (book.sheetnames == ['Sheet'] and book.active['A1'].value is None):
            raise ValueError('Unrecognized workbook; refusing to overwrite')
    finally:
        book.close()
    return annotations


def _merge(sheet, r1, c1, r2, c2, value=None):
    if (r1, c1) != (r2, c2):
        sheet.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
    if value is not None:
        _text(sheet.cell(r1, c1), value)


def _create_sheet(book, title, subtitle):
    sheet = book.create_sheet(title)
    sheet.sheet_properties.codeName = f'researchLedger{len(book.worksheets)}'
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 75
    sheet.freeze_panes = 'E6'
    for r in range(1, FIRST_ROW):
        for c in range(1, 33):
            cell = sheet.cell(r, c)
            cell.font = Font(name='等线', size=10, bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='17365D' if r < 3 else '305496')
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    _merge(sheet, 1, 1, 1, 32, title + '  |  World Tracing 研究记录')
    _merge(sheet, 2, 1, 2, 32, subtitle)
    sheet['A1'].font = Font(name='等线', size=17, bold=True, color='FFFFFF')
    sheet['A1'].alignment = Alignment(horizontal='left', vertical='center')
    sheet['A2'].alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
    _merge(sheet, 3, 1, 3, 7, '实验信息与配置')
    _merge(sheet, 3, 8, 3, 9, '定性结果')
    _merge(sheet, 3, 10, 3, 31, '定量结果（仅本项目实测）')
    _merge(sheet, 3, 32, 5, 32, HEADERS[-1])
    for c in range(1, 10):
        _merge(sheet, 4, c, 5, c, HEADERS[c-1])
    for start, end, name in [(10, 14, '完整形状 · GT 辅助 Sim(3)'), (15, 22, '可见深度 · SSI / 覆盖'),
                             (23, 27, '相机框架 · 不配准'), (28, 31, 'WT / 默认 hybrid · 共同有效深度')]:
        _merge(sheet, 4, start, 4, end, name)
        for c in range(start, end+1):
            _text(sheet.cell(5, c), HEADERS[c-1])
    widths = {1: 30, 2: 24, 3: 31, 4: 21, 5: 40, 6: 15, 7: 16, 8: 54, 9: 52,
              10: 13, 15: 15, 23: 13, 28: 16, 32: 22}
    for c in range(1, 33):
        sheet.column_dimensions[get_column_letter(c)].width = widths.get(c, 12)
    # Keep the principal shape/depth results visible; secondary groups remain expandable.
    sheet.column_dimensions.group('S', 'T', hidden=True)
    sheet.column_dimensions.group('W', 'AA', hidden=True)
    sheet.column_dimensions.group('AB', 'AE', hidden=True)
    for r, height in [(1, 32), (2, 34), (3, 26), (4, 30), (5, 42)]:
        sheet.row_dimensions[r].height = height
    sheet.print_title_rows = '1:5'
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.oddFooter.center.text = '第 &P / &N 页'
    return sheet


def _style_row(sheet, row, alternate=False):
    fill = PatternFill('solid', fgColor='F0F5FA' if alternate else 'FFFFFF')
    border = Border(bottom=Side(style='hair', color='CBD5E1'))
    for cell in sheet[row][:32]:
        cell.font = Font(name='等线', size=10, color='1F2937')
        cell.alignment = Alignment(vertical='top', wrap_text=True)
        cell.fill, cell.border = fill, border
        if 10 <= cell.column <= 31:
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.number_format = '0.000000'
    sheet.row_dimensions[row].height = 108


def _config_text(record):
    p, method = record['parameters'], record['method']
    parts = [record['config']]
    if method in ('wt', 'wt_trellis2'):
        background = p.get('bg_color', '?')
        if isinstance(background, (list, tuple)):
            background = background[0] if len(set(background)) == 1 else background
        parts.append(f'WT {p.get("wt_steps", "?")} 步；背景 {background}；腐蚀 {p.get("alpha_erode", "?")} px')
    if method != 'wt':
        parts.append(str(p.get('pipeline_type', '?')))
        if method == 'pixal3d':
            steps = [p.get(k, {}).get('steps', '?') for k in ('sparse_structure_sampler_params', 'shape_slat_sampler_params', 'tex_slat_sampler_params')]
            parts.append('结构/形状/纹理步数 ' + '/'.join(map(str, steps)))
        else:
            parts.append(f'形状/纹理步数 {p.get("shape_steps", "?")}/{p.get("tex_steps", "?")}')
        if method == 'wt_trellis2':
            parts.append(f'ray_steps={p.get("ray_steps", "?")}' + ('；复用基线 WT' if p.get('reuse_wt_config') or record['config']=='shared-wt-v1' else '；独立 WT 上游'))
        parts.append(f'贴图 {p.get("texture_size", "?")}；目标面数 {p.get("decimation_target", "?")}')
    return '\n'.join(parts)


def _stats(records, protocol, metric):
    values, statuses, reasons, paths, units = [], Counter(), set(), [], set()
    for record in records:
        item = record['metrics'].get((protocol, metric))
        if item is None:
            statuses['failed' if record['run']['status'] == 'failed' else 'pending'] += 1
            if record['run'].get('error'):
                reasons.add(record['run']['error'])
            continue
        statuses[item['status']] += 1
        if item.get('unit'):
            units.add(item['unit'])
        if item.get('reason'):
            reasons.add(item['reason'])
        if item['status'] == 'complete':
            values.append(item['value'])
            paths.append(str(record['metric_path']))
    if len(units) > 1:
        raise ValueError(f'Inconsistent units for {protocol}/{metric}: {sorted(units)}')
    return dict(n=len(values), total=len(records), mean=statistics.mean(values) if values else None,
                std=statistics.pstdev(values) if values else None, statuses=dict(statuses),
                reasons=sorted(reasons), sources=paths, units=sorted(units))


def _count_label(stats):
    if stats['statuses'].get('N/A', 0) == stats['total']:
        return '不适用'
    return f'{stats["n"]} / {stats["total"]}'


def _write_metric(sheet, row, column, records, protocol, metric, audit):
    stats = _stats(records, protocol, metric)
    cell = sheet.cell(row, column)
    if stats['mean'] is not None:
        cell.value = stats['mean']
        audit['cells'].append(dict(sheet=sheet.title, cell=cell.coordinate, value=cell.value,
                                   protocol=protocol, metric=metric, n=stats['n'], sources=stats['sources']))
    else:
        _text(cell, '不适用' if stats['statuses'].get('N/A') == stats['total'] else
              ('失败' if stats['statuses'].get('failed') else '待评价'))
        cell.font = Font(name='等线', size=10, color='9C6500' if cell.value != '不适用' else '94A3B8')
    explanation = (f'协议：{protocol}\n指标：{metric}\n有效 n={stats["n"]}/{stats["total"]}；'
                   f'状态={_encoded(stats["statuses"])}\n单位={", ".join(stats["units"]) or "源记录未声明"}\n总体标准差={stats["std"]}\n')
    if stats['reasons']:
        explanation += '\n'.join(stats['reasons']) + '\n'
    explanation += '汇总为逐样本算术均值；不适用/失败/待评价不以 0 填充。'
    cell.comment = Comment(explanation, '实验记录')
    return stats


def _paired(exp, seed):
    sets = []
    for method in ('wt', 'wt_trellis2'):
        groups = [records for group, records in exp['groups'].items() if group[:3] == (method, 'defaults-v1', seed)]
        if len(groups) != 1:
            return None
        sets.append({r['sample'] for r in groups[0] if all(
            r['metrics'].get((DEPTH, metric), {}).get('status') == 'complete' for metric in ('mae', 'rmse', 'absrel'))})
    return set.intersection(*sets)


def _automatic_note(exp, records, detail):
    record = records[0]
    observed = exp['observations'].get('observations', {}).get(record['config'], {}).get(str(record['seed']))
    if observed:
        return observed
    if not exp['quantitative']:
        return '定性分析待补充。'
    messages = []
    for protocol, metric, label in [(SHAPE, 'cd_euclidean_mean', '形状'), (DEPTH, 'mae', 'SSI 深度')]:
        stats = _stats(records, protocol, metric)
        if stats['statuses'].get('failed'):
            messages.append(f'{label}评价失败 {stats["statuses"]["failed"]}/{stats["total"]}；失败值不计均值。')
            if detail:
                messages.extend(stats['reasons'])
        elif stats['statuses'].get('pending'):
            messages.append(f'{label}待评价 {stats["statuses"]["pending"]}/{stats["total"]}。')
    if record['method'] in ('trellis2', 'pixal3d'):
        messages.append('输入相机框架/深度不适用；未使用 GT 姿态补齐。')
    if not messages:
        messages.append('已记录指标；定性观察待补充。')
    return '\n'.join(messages)


def _write_run_row(sheet, row, exp, records, annotations, audit, detail=False):
    record = records[0]
    scope = record['sample'] if detail else '*'
    key = (exp['id'], scope, *record['group'])
    _text(sheet.cell(row, 4), METHODS.get(record['method'], record['method']))
    config_text = _config_text(record)
    if sum(group[:3] == record['group'][:3] for group in exp['groups']) > 1:
        config_text += '\n参数版本 ' + record['group'][3]
    _text(sheet.cell(row, 5), config_text)
    configs = sorted({str(r['config_path']) for r in records})
    sheet.cell(row, 5).comment = Comment(KEY_PREFIX + _encoded(key) + '\n'
        + f'配置来源：{configs[0]}\n参数：{_encoded(record["parameters"])}\n'
        + f'本组 {len(records)} 条记录；{len({r["run"].get("config_hash") for r in records})} 个完整配置/环境摘要。', '实验记录')
    sheet.cell(row, 5).hyperlink = configs[0]
    p = record['parameters']
    seed = f'纹理 {record["seed"]}\nWT {p["wt_seed"]} / 形状 {p["shape_seed"]}' if 'texture_seed_policy' in p else str(record['seed'])
    _text(sheet.cell(row, 6), seed)
    counts = Counter(r['run']['status'] for r in records)
    status = f'{counts["complete"]}/{len(records)} 完成'
    if counts['failed']:
        status += f'\n{counts["failed"]} 执行失败'
    if sum(counts.values()) != counts['complete'] + counts['failed']:
        status += '\n存在待运行项'
    _text(sheet.cell(row, 7), status)
    automatic = _automatic_note(exp, records, detail)
    _text(sheet.cell(row, 9), annotations['notes'].get(key, automatic))
    sheet.cell(row, 9).comment = Comment(AUTO_PREFIX + _encoded(automatic) + '\n可直接编辑此格；后续刷新保留人工文字。', '实验记录')
    _text(sheet.cell(row, 32), '配置 / 原始结果' if detail else '结果目录 / 配置')
    sheet.cell(row, 32).hyperlink = str(record['directory'] if detail else exp['root'])
    paths = [record['directory'], record['config_path']]
    if record['metric_path'].exists():
        paths.append(record['metric_path'])
    sheet.cell(row, 32).comment = Comment('\n'.join(map(str, paths)), '实验记录')
    if not exp['quantitative']:
        _merge(sheet, row, 10, row, 31, '不适用：定性输入无配套 GT；不计算形状、相机与深度准确率。')
        return
    for column, (protocol, metric) in METRIC_COLUMNS.items():
        _write_metric(sheet, row, column, records, protocol, metric, audit)
    for column, protocol, metric in [(10, SHAPE, 'cd_euclidean_mean'), (15, DEPTH, 'mae'), (23, CAMERA, 'cd_euclidean_mean')]:
        _text(sheet.cell(row, column), _count_label(_stats(records, protocol, metric)))
    common = _paired(exp, record['seed'])
    eligible = record['method'] in ('wt', 'wt_trellis2') and record['config'] == 'defaults-v1' and common is not None
    if eligible:
        selected = [r for r in records if r['sample'] in common]
        _text(sheet.cell(row, 28), f'{len(selected)} / {len(records)}')
        for column, metric in [(29, 'mae'), (30, 'rmse'), (31, 'absrel')]:
            if selected:
                _write_metric(sheet, row, column, selected, DEPTH, metric, audit)
            else:
                _text(sheet.cell(row, column), '未纳入')
    else:
        _merge(sheet, row, 28, row, 31, '不适用：仅比较默认 WT / hybrid 的共同有效样本。')


def _sheet_name(exp, used):
    tokens = exp['id'].split('-')
    short = next((x for x in tokens if x in ('P0', 'R1', 'R2')), exp['id'][:18])
    base = short + '_逐样本'
    name, i = base[:31], 2
    while name in used:
        name = base[:27] + f'_{i}'
        i += 1
    return name


def _experiment_cells(sheet, start, end, exp, annotations, sample=None, detail_name=None):
    if sample is None:
        _merge(sheet, start, 1, end, 1, exp['id'])
        sheet.cell(start, 1).hyperlink = str(exp['root'])
        _merge(sheet, start, 2, end, 2, f'{len(exp["samples"])} 样本\n{len(exp["records"])} 次运行\n'
               + ('有 GT · 定量实验' if exp['quantitative'] else '无 GT · 定性实验'))
        if detail_name:
            sheet.cell(start, 2).hyperlink = f"#'{detail_name}'!A1"
        purpose = annotations['purposes'].get(exp['id']) or exp['manifest'].get('purpose') or exp['manifest'].get('name') or '研究问题待补充。'
        _merge(sheet, start, 3, end, 3, purpose)
        _merge(sheet, start, 8, end, 8, annotations['conclusions'].get(exp['id']) or '结论待补充。')
        if annotations['links'].get(exp['id']):
            sheet.cell(start, 8).hyperlink = annotations['links'][exp['id']]
        sheet.cell(start, 3).comment = Comment('\n'.join(exp['warnings']) or '进度依据实际 run.json，不使用历史计划数推断完成情况。', '实验记录')
    else:
        _merge(sheet, start, 2, end, 2, sample)
        input_data = exp['samples'].get(sample, {})
        image = input_data.get('image')
        if image:
            image_path = Path(image)
            if not image_path.is_absolute():
                image_path = exp['root']/'samples'/sample/image_path
            sheet.cell(start, 2).hyperlink = str(image_path)


def build_workbook(experiments, annotations, sources):
    book = Workbook()
    book.remove(book.active)
    book.properties.identifier = VERSION
    book.properties.title = 'World Tracing 实验研究记录'
    book.properties.creator = 'World Tracing'
    now = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
    subtitle = (f'核对：{now} | 每行=方法×配置×seed；均值只使用有效样本，失败/不适用保留说明。'
                '形状经 GT 辅助 Sim(3)，深度经 SSI；覆盖率/IoU 的样本数见单元格批注。'
                '列上方 + 可展开 δ1/δ2、相机框架和共同样本指标。')
    overview = _create_sheet(book, OVERVIEW, subtitle)
    audit = dict(schema=VERSION, updated_at=now, source_sha256=sources, experiments=[], cells=[])
    row = FIRST_ROW
    for i, exp in enumerate(experiments):
        detail_name = _sheet_name(exp, book.sheetnames) if exp['quantitative'] else None
        groups = sorted(exp['groups'], key=_group_order)
        start = row
        for group in groups:
            _style_row(overview, row, i % 2)
            _write_run_row(overview, row, exp, exp['groups'][group], annotations, audit)
            row += 1
        if not groups:
            _style_row(overview, row, i % 2)
            _text(overview.cell(row, 7), '尚无运行记录')
            row += 1
        _experiment_cells(overview, start, row-1, exp, annotations, detail_name=detail_name)
        if row-start > 1:
            overview.row_dimensions.group(start+1, row-1, hidden=False)
        if detail_name:
            detail = _create_sheet(book, detail_name, '逐样本：每个样本下按方法×配置×seed 排列。' + subtitle)
            detail_row = FIRST_ROW
            by_sample = defaultdict(list)
            for record in exp['records']:
                by_sample[record['sample']].append(record)
            for j, sample in enumerate(sorted(by_sample)):
                sample_start = detail_row
                for record in sorted(by_sample[sample], key=lambda r: _group_order(r['group'])):
                    _style_row(detail, detail_row, j % 2)
                    _write_run_row(detail, detail_row, exp, [record], annotations, audit, detail=True)
                    detail_row += 1
                _experiment_cells(detail, sample_start, detail_row-1, exp, annotations, sample=sample)
            if detail_row > FIRST_ROW:
                for c, text in [(1, exp['id']), (3, '单样本诊断；样本行内横向比较方法。\n完整配置见 E 列链接，指标缺失原因见批注。'),
                                (8, '总体结论见「实验总览」。逐样本定性观察记入 I 列；空白观察不推断为通过。')]:
                    _merge(detail, FIRST_ROW, c, detail_row-1, c, text)
                detail.cell(FIRST_ROW, 8).hyperlink = f"#'{OVERVIEW}'!H{start}"
            detail.print_area = f'A1:AF{max(FIRST_ROW, detail_row-1)}'
        audit['experiments'].append(dict(id=exp['id'], samples=len(exp['samples']), runs=len(exp['records']),
            statuses=dict(Counter(r['run']['status'] for r in exp['records'])), configurations=len(groups),
            overview_rows=[start,row-1], detail_sheet=detail_name, warnings=exp['warnings']))
    overview.print_area = f'A1:AF{row-1}'
    book.active = 0
    return book, audit


def export(experiment_dir, destination, *, audit_path=None, annotations=None, notice=None):
    """Rebuild the ledger atomically; carry human conclusions/observations across refreshes."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.with_suffix('.xlsx.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = _load_annotations(destination)
        experiments, sources = collect_experiments(experiment_dir)
        missing = previous['experiments'] - {exp['id'] for exp in experiments}
        if missing:
            raise ValueError(f'Missing source experiments; refusing to discard records: {sorted(missing)}')
        for key, values in (annotations or {}).items():
            previous[key].update(values)
        book, audit = build_workbook(experiments, previous, sources)
        if notice:
            for sheet in book.worksheets:
                sheet['A2'] = str(notice) + chr(10) + str(sheet['A2'].value or '')
            audit['notice'] = str(notice)
        with tempfile.NamedTemporaryFile(prefix='.experiments-', suffix='.xlsx', dir=destination.parent, delete=False) as tmp:
            temporary = Path(tmp.name)
        try:
            book.save(temporary)
            normalize_comment_parts(temporary)
            book.close()
            check = load_workbook(temporary)
            for item in audit['cells']:
                value = check[item['sheet']][item['cell']].value
                if not isinstance(value, (float, int)) or not math.isclose(value, item['value'], rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError(f'Workbook numeric roundtrip failed: {item["sheet"]}/{item["cell"]}')
            audit['numeric_cells_verified'] = len(audit['cells'])
            audit['sheets'] = check.sheetnames[:]
            check.close()
            if destination.exists():
                os.chmod(temporary, destination.stat().st_mode & 0o777)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        audit['workbook_sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
        if audit_path:
            audit_path = Path(audit_path)
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
        return {OVERVIEW: sum(max(1, len(e['groups'])) for e in experiments),
                **{e['detail_sheet']: e['runs'] for e in audit['experiments'] if e['detail_sheet']}}
