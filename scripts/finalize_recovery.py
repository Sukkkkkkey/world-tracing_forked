"""Publish recovered summaries and workbook only after all 621 outputs pass review."""
import argparse
from collections import Counter, defaultdict
import datetime
import fcntl
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess

from evaluation.research_workbook import export, _load_annotations
from wt.experiment import atomic_json, file_digest, read_json
from wt.paths import OUTPUT_ROOT, PROCESSED_ROOT
from scripts.compare_recovery_metrics import compare

REPO = Path(__file__).resolve().parents[1]
AUDITS = OUTPUT_ROOT / 'validation/recovery-20261105'


def summarize(root, audit):
    groups, fingerprints = defaultdict(list), {}
    states = []
    for path in sorted(root.glob('samples/*/*/*/seed-*/run.json')):
        state = read_json(path)
        assert state['status'] == 'complete'
        states.append(state)
        for name in ('run.json', 'config.json', 'metrics.json'):
            file = path.parent / name
            if not file.exists():
                assert name == 'metrics.json'
                continue
            checksum = file_digest(file)
            assert checksum == audit['artifact_sha256'][str(file.relative_to(root))]
            fingerprints[str(file.relative_to(root))] = checksum
        metrics = path.parent / 'metrics.json'
        if metrics.exists():
            assert read_json(metrics)['evaluation_status'] == 'complete'
            for row in read_json(metrics)['metrics']:
                key = (state['method'], state['config_id'], state['seed'], row['protocol_id'], row['metric'])
                groups[key].append(dict(row, sample_id=state['sample_id']))
    assert len(states) == audit['expected']
    records = []
    for key, rows in sorted(groups.items()):
        values = [r['value'] for r in rows if r['status'] == 'complete']
        records.append(dict(zip(('method', 'config_id', 'seed', 'protocol_id', 'metric'), key),
            total=len(rows), valid=len(values), mean=statistics.fmean(values) if values else None,
            std=statistics.pstdev(values) if values else None,
            statuses=dict(Counter(r['status'] for r in rows)), units=sorted({r['unit'] for r in rows}),
            missing=[dict(sample=r['sample_id'], status=r['status'], reason=r.get('reason'))
                     for r in rows if r['status'] != 'complete']))
    result = dict(status='complete', experiment=root.name, runs=len(states),
        by_method=dict(Counter(x['method'] for x in states)), records=records,
        source_sha256=fingerprints, quality_failures=audit['quality_failures'],
        source_audit_sha256=file_digest(AUDITS / root.name / 'all-methods.json'))
    atomic_json(root / 'summary.json', result)
    return result


def publish_workbook():
    destination = REPO / '.runtime/experiments-protocolv0-regenerated.xlsx'
    if not destination.exists():
        shutil.copy2(REPO / 'docs/archived/20261110_experiment_baseline_protocol_v0.xlsx', destination)
    original_hash = file_digest(destination)
    before = _load_annotations(destination)
    temporary = REPO / '.runtime/experiments.recovered.xlsx'
    shutil.copy2(destination, temporary)
    link_changes = {}
    for key, target in before['links'].items():
        updated = target.replace('/data1/LiuShuqi/code/world_tracing', str(REPO))
        updated = updated.replace('/data1/LiuShuqi/output/world_tracing', str(OUTPUT_ROOT))
        if updated != target:
            # The existing historical code reports were migrated with the repository.
            assert Path(updated.split('#', 1)[0]).exists(), 'Mapped conclusion link is missing: ' + updated
            link_changes[key] = updated
    export(OUTPUT_ROOT / 'experiments', temporary, audit_path=AUDITS / 'workbook.json',
           annotations={'links': link_changes},
           notice='数值来自新服务器复跑；人工结论与备注继承旧工作簿。最新复核见恢复结果报告。')
    after = _load_annotations(temporary)
    for category in ('conclusions', 'purposes', 'notes'):
        for identity, text in before[category].items():
            if text is not None:
                assert after[category].get(identity) == text, 'Human annotation changed: ' + str((category, identity))
    assert before['experiments'] == after['experiments']
    with destination.with_suffix('.xlsx.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert file_digest(destination) == original_hash, 'Workbook was edited during regeneration'
        temporary.replace(destination)
    return dict(before_sha256=original_hash, after_sha256=file_digest(destination),
        preserved={k: len(before[k]) for k in ('conclusions', 'purposes', 'notes')},
        updated_links=link_changes)


def verify_reviewed_sources(source_ref=None):
    """Verify the recorded recovery source against a fixed Git commit."""
    review_path = AUDITS / 'source-review.json'
    lock = read_json(REPO / 'configs/recovery_source.json')
    assert file_digest(review_path) == lock['review_sha256'], 'Recovery source review changed'
    review = read_json(review_path)
    assert review['status'] == 'reviewed'
    revision = source_ref or lock['commit']
    command = ['git', '-C', str(REPO)]
    commit = subprocess.check_output(
        command + ['rev-parse', '--verify', '--end-of-options', revision + '^{commit}'],
        text=True).strip()
    for record in review['files']:
        path = Path(record['path'])
        assert not path.is_absolute() and '..' not in path.parts, record['path']
        contents = subprocess.check_output(
            command + ['show', commit + ':' + path.as_posix()])
        assert hashlib.sha256(contents).hexdigest() == record['current_sha256'], record['path']
    return commit


def main(publish, source_ref=None):
    recipe = read_json(REPO / 'configs/recovery_experiments.json')
    from scripts.check_recovery_performance import check, DECISION
    performance = check()
    reviewed_schedulers = {file_digest(DECISION): performance}
    for revision in performance.get('accepted_prior_decisions', []):
        reviewed_schedulers[revision['sha256']] = read_json(Path(revision['path']))
    source_revision = verify_reviewed_sources(source_ref)
    execution = {}
    execution_details = []
    for spec in recipe['experiments']:
        for kind in ('baseline', 'pixal'):
            selected = ('-R2-' in spec['id'] or (kind == 'pixal' and '-R1-' in spec['id']))
            if not selected or performance['workers'][kind] != 2:
                continue
            path = AUDITS / spec['id'] / ('execution-' + kind + '.json')
            result = read_json(path)
            assert result['status'] == 'passed' and result['workers'] == 2 and result['device'] == 0
            assert result['samples'] == spec['samples']
            reviewed = reviewed_schedulers[result['decision_sha256']]
            assert result['runner_sha256'] == reviewed['runner_sha256']
            assert result['workers'] == reviewed['workers'][kind]
            if result.get('execution_mode') == 'parallel-plus-reviewed-selective-memory-repair':
                assert '-R2-' in spec['id'] and kind == 'baseline'
                from scripts.repair_recovery_memory import verify_completion, DECISION as MEMORY_DECISION, REPORT as MEMORY_REPORT
                verify_completion(OUTPUT_ROOT / 'experiments' / spec['id'])
                assert result['completion_runner_sha256'] == file_digest(REPO / 'scripts/repair_recovery_memory.py')
                assert result['memory_decision_sha256'] == file_digest(MEMORY_DECISION)
                assert result['memory_repair_sha256'] == file_digest(MEMORY_REPORT)
                assert result['worker_exits'] == [1, 1] and result['original_serial_retry_exit'] == 1
                assert result['final_memory_repair_exit'] == 0
                execution[str(MEMORY_DECISION)] = file_digest(MEMORY_DECISION)
                execution[str(MEMORY_REPORT)] = file_digest(MEMORY_REPORT)
            execution[str(path)] = file_digest(path)
            resources = read_json(Path(result['control']) / 'resources.json')
            observed_gpu = [r['gpu_mib'] for r in resources if r.get('gpu_mib') is not None]
            execution_details.append(dict(
                experiment=spec['id'], phase=kind, workers=result['workers'],
                elapsed_seconds=result['elapsed_seconds'],
                execution_mode=result.get('execution_mode', 'reviewed-parallel-runner'),
                elapsed_scope=result.get('elapsed_scope', 'Worker-stage wall time including internal retries; excludes parent WT preflight, audits and earlier attempts.'),
                worker_exits=result['worker_exits'], resource_guard=result['resource_guard'],
                archived_retry_runs=len(result['retries']),
                monitored_parallel_peak_gpu_gib=max(observed_gpu, default=0) / 1024,
                monitored_parallel_peak_working_set_gib=max(
                    (r['working_set_bytes'] for r in resources), default=0) / 1024**3,
                monitor_query_error_count=sum(r.get('monitor_error') is not None for r in resources),
                resource_samples_sha256=file_digest(Path(result['control']) / 'resources.json'),
                report=str(path), report_sha256=file_digest(path)))
    storage = read_json(OUTPUT_ROOT / 'validation/artifact-storage.json')
    assert storage['status'] == 'passed' and storage['source_sha256'] == file_digest(REPO / 'wt/artifacts.py')
    assert read_json(PROCESSED_ROOT / 'gso/v1/recovery_audit.json')['status'] == 'passed'
    assert read_json(REPO / '.runtime/logs/recovery-20261105/base-validation.status.json')['status'] == 'passed'
    assert read_json(OUTPUT_ROOT / 'validation/pixal3d-environment.json')['status'] == 'passed'
    crop = read_json(OUTPUT_ROOT / 'validation/z-root-cause-20261020/recovery-validation.json')
    texture = read_json(OUTPUT_ROOT / 'experiments/20261020-icecream-texture-seeds-v1/validation.json')
    assert crop['status'] == 'passed' and crop['runs'] == 15
    assert texture['status'] == 'passed' and len(texture['runs']) == 6
    summaries = []
    for spec in recipe['experiments']:
        audit = read_json(AUDITS / spec['id'] / 'all-methods.json')
        assert audit['status'] == 'passed' and audit['expected'] == spec['runs']
        assert audit['auditor_sha256'] == file_digest(REPO / 'scripts/audit_recovery_experiment.py')
        summaries.append(summarize(OUTPUT_ROOT / 'experiments' / spec['id'], audit))
    assert sum(x['runs'] for x in summaries) == 600
    r2_root = OUTPUT_ROOT / 'experiments/20261013-R2-gso-quant-v1'
    r2_audit = read_json(AUDITS / r2_root.name / 'all-methods.json')
    pixal_timings = []
    for path in r2_root.glob('samples/*/pixal3d/*/seed-0042/runtime.json'):
        checksum = file_digest(path)
        state_path = path.parent / 'run.json'
        assert file_digest(state_path) == r2_audit['artifact_sha256'][str(state_path.relative_to(r2_root))]
        runtime = read_json(path)
        for key in ('generation_seconds', 'export_seconds', 'total_inference_seconds'):
            value = runtime[key]
            assert type(value) in (int, float) and math.isfinite(value) and value >= 0
        assert runtime['total_inference_seconds'] >= max(runtime['generation_seconds'], runtime['export_seconds'])
        pixal_timings.append(dict(
            sample=path.parents[3].name, source=str(path), source_sha256=checksum,
            generation_seconds=runtime['generation_seconds'],
            export_seconds=runtime['export_seconds'],
            total_inference_seconds=runtime['total_inference_seconds']))
    assert len(pixal_timings) == 100
    pixal_timings.sort(key=lambda row: row['export_seconds'], reverse=True)
    comparison = compare(require_complete=True)
    depth_rows = [
        row for row in comparison['rows']
        if '-R2-' in row['identity'][0]
        and row['protocol_id'] == 'gso-depth-ssi-v1'
        and row['metric'] == 'absrel'
    ]
    depth_by_method = {
        method: {row['identity'][1]: row for row in depth_rows if row['identity'][2] == method}
        for method in ('wt', 'wt_trellis2')
    }
    hybrid_rows = list(depth_by_method['wt_trellis2'].values())
    paired = [
        row for row in hybrid_rows
        if row['old_status'] == row['new_status'] == 'complete'
    ]
    common_ids = [
        sample for sample in depth_by_method['wt']
        if all(depth_by_method[method][sample]['new_status'] == 'complete'
               for method in depth_by_method)
    ]
    depth_review = dict(
        hybrid_old_valid=sum(row['old_status'] == 'complete' for row in hybrid_rows),
        hybrid_new_valid=sum(row['new_status'] == 'complete' for row in hybrid_rows),
        hybrid_paired_count=len(paired),
        hybrid_paired_old_mean=statistics.fmean(row['old'] for row in paired),
        hybrid_paired_new_mean=statistics.fmean(row['new'] for row in paired),
        transitions=[
            dict(sample=row['identity'][1], old=row['old_status'],
                 new=row['new_status'], reason=row['new_reason'])
            for row in hybrid_rows if row['old_status'] != row['new_status']
        ],
        current_common_count=len(common_ids),
        current_common_means={
            method: statistics.fmean(depth_by_method[method][sample]['new'] for sample in common_ids)
            for method in depth_by_method
        })
    if publish:
        crop_review = OUTPUT_ROOT / 'validation/z-root-cause-20261020/review'
        review = read_json(crop_review / 'review.json')
        assert review['status'] == 'reviewed' and review['manifest_sha256'] == file_digest(crop_review / 'manifest.json')
        crop_manifest = read_json(crop_review / 'manifest.json')
        assert crop_manifest['runs'] == 15
        assert all(file_digest(Path(path)) == checksum for path, checksum in crop_manifest['source_sha256'].items())
        for spec in recipe['experiments']:
            review = read_json(AUDITS / spec['id'] / 'visuals/review.json')
            assert review['status'] == 'reviewed'
            assert review['manifest_sha256'] == file_digest(AUDITS / spec['id'] / 'visuals/manifest.json')
        texture_review = OUTPUT_ROOT / 'experiments/20261020-icecream-texture-seeds-v1/review'
        review = read_json(texture_review / 'review.json')
        assert review['status'] == 'reviewed' and review['manifest_sha256'] == file_digest(texture_review / 'manifest.json')
    workbook = publish_workbook() if publish else None
    report = dict(status='passed' if publish else 'validated-awaiting-publication',
        finished=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        main_runs=600, crop_background_runs=15, texture_seed_runs=6, total_runs=621,
        experiments=[{k:v for k,v in x.items() if k not in ('records','source_sha256')} for x in summaries],
        performance_decision_sha256=file_digest(DECISION), execution_sha256=execution,
        execution_details=execution_details, r2_depth_review=depth_review,
        r2_pixal_longest_exports=pixal_timings[:5],
        source_revision=source_revision,
        source_review_sha256=file_digest(AUDITS / 'source-review.json'),
        finalizer_sha256=file_digest(Path(__file__)),
        workbook=workbook, historical_comparison_sha256=file_digest(AUDITS / 'historical-comparison.json'),
        recipe_sha256=file_digest(REPO / 'configs/recovery_experiments.json'))
    atomic_json(AUDITS / ('final.json' if publish else 'prepublication.json'), report)
    lines = ['# 新服务器实验恢复结果', '',
        '本轮恢复包含主实验 600 项、裁剪/背景对照 15 项、纹理种子对照 6 项，使用历史样本、配置及 seed。', '',
        '## 定量结果', '',
        'CD 为独立注册与评价点集下的 Sim(3) Chamfer 欧氏距离，F@0.01 为比例。网格方法的形状评分使用导出重网格前的 decoded_mesh.ply。SSI 均值使用通过质量门槛的样本，缺失原因保存在 summary.json。', '',
        '| 实验 | 方法 / 配置 | 形状有效数 | CD-L1 | F@0.01 | SSI 有效数 | SSI AbsRel |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for summary in summaries:
        lookup = {(r['method'],r['config_id'],r['protocol_id'],r['metric']):r for r in summary['records']}
        for method, config in sorted({(r['method'],r['config_id']) for r in summary['records']}):
            cd = lookup[method,config,'gso-shape-sim3-v1','cd_euclidean_mean']
            f1 = lookup[method,config,'gso-shape-sim3-v1','f@0.01']
            depth = lookup[method,config,'gso-depth-ssi-v1','absrel']
            value = 'N/A' if depth['mean'] is None else format(depth['mean'], '.6f')
            lines.append(f"| {summary['experiment'].split('-')[1]} | {method} / {config} | {cd['valid']}/{cd['total']} | {cd['mean']:.6f} | {f1['mean']:.6f} | {depth['valid']}/{depth['total']} | {value} |")
    lines += ['', '## 与旧工作簿的差异', '',
        '450 个定量 run 的历史样本与参数身份逐项核对通过。下表比较旧工作簿保存的数值与本轮重算值。', '',
        '| 实验 | 方法 / 配置 | 旧 CD-L1 均值 | 新 CD-L1 均值 | 单样本最大绝对变化 |',
        '| --- | --- | ---: | ---: | ---: |']
    for row in comparison['groups']:
        if row['protocol_id'] == 'gso-shape-sim3-v1' and row['metric'] == 'cd_euclidean_mean':
            lines.append(f"| {row['experiment'].split('-')[1]} | {row['method']} / {row['config']} | {row['old_mean']:.6f} | {row['new_mean']:.6f} | {row['max_abs_paired_delta']:.6f} |")
    lines += [
        '',
        f"R2 hybrid 的 SSI 有效样本由 {depth_review['hybrid_old_valid']} 个变为 {depth_review['hybrid_new_valid']} 个。"
        f"前后共同有效的 {depth_review['hybrid_paired_count']} 个样本中，AbsRel 均值从 "
        f"{depth_review['hybrid_paired_old_mean']:.6f} 变为 {depth_review['hybrid_paired_new_mean']:.6f}。",
        f"本轮 WT 与 hybrid 共同有效的 {depth_review['current_common_count']} 个样本中，AbsRel 均值分别为 "
        f"{depth_review['current_common_means']['wt']:.6f} 和 {depth_review['current_common_means']['wt_trellis2']:.6f}。",
        '',
        '| 深度质量状态改变的样本 | 旧状态 | 新状态 | 本轮原因 |',
        '| --- | --- | --- | --- |']
    for transition in depth_review['transitions']:
        lines.append(
            f"| {transition['sample']} | {transition['old']} | {transition['new']} | "
            f"{transition['reason'] or '通过原有质量门槛'} |")
    lines += ['', '旧逐样本预测和冻结输入摘要缺失，跨服务器数值差异的来源尚未定位。新机三个默认 WT 重放的 XYZ 和掩码与本轮 P0 逐元素一致。15 项裁剪与背景对照全部完成。旧工作簿和首轮 Pixal 环境修复前的结果已有归档。', '',
        f"- [逐项历史差异审计]({AUDITS / 'historical-comparison.json'})"]
    lines += ['', '## 单卡执行策略', '',
        'R2 前的固定小样本测试测得，WT batch=2/4 吞吐提高约 5%–7%，同时 XYZ 出现数值差异。正式运行采用 WT batch=1。按完整样本分配的 TRELLIS.2 / hybrid 两进程测得 1.530 倍吞吐，Pixal 两进程测得 1.511 倍吞吐，测试中的解码几何及导出前纹理一致。',
        '', '正式阶段通常约每两秒采样整卡显存和实例工作集。单次 GPU 查询限时十秒，连续三次查询失败或资源达到门槛时停止自己的工作进程。查询与资源余量恢复后，归档不完整尝试并串行重试。首轮 R2 因查询超时异常退出，v2 修复通过十四项回归。原尝试、旧版本决策、实际退出码和耗时均已归档。',
        '', f"- [单卡测试与决策]({REPO / 'docs/archived/20261105_recovery-results.md'})",
        f"- [复核决策与证据摘要]({DECISION})",
        '', 'R2 两个 hybrid 在并行及原方案串行重试中均显存不足。修复采用历史方案中的独立行 LayerNorm 分块、同序拓扑分块和用后缓存释放，配置身份审计通过。59 个 CUDA 算例、自动求导回退及十三项文件保护测试通过，两个固定完整预训练样本的解码网格与导出前几何、纹理张量逐元素一致。两个失败 run 已重跑，各自新 WT 父缓存与原数组及 RGBA 精确相同。另外 298 个基线 run 的 1,689 个文件前后哈希一致。原失败日志和内存策略来源均有记录。',
        f"- [内存策略验证及决定]({AUDITS / '20261013-R2-gso-quant-v1/memory-policy-decision.json'})",
        f"- [两项修复与原产物保护证明]({AUDITS / '20261013-R2-gso-quant-v1/memory-repair.json'})"]
    lines += ['', '| 正式阶段 | 记录时长（分钟） | 并行显存峰值 GiB | 并行实例工作集 GiB | 初始工作进程退出码 | 归档后重试 run 数 |',
        '| --- | ---: | ---: | ---: | --- | ---: |']
    for item in execution_details:
        lines.append(
            f"| {item['experiment'].split('-')[1]} / {item['phase']} | "
            f"{item['elapsed_seconds']/60:.2f} | {item['monitored_parallel_peak_gpu_gib']:.2f} | "
            f"{item['monitored_parallel_peak_working_set_gib']:.2f} | {item['worker_exits']} | "
            f"{item['archived_retry_runs']} |")
    lines += ['', 'R1 / Pixal 和 R2 / Pixal 的记录覆盖工作进程从启动到退出的加载、推理、导出及内部重试。R2 / baseline 的记录为 v2 尝试与两项内存修复的时长之和，其中包括该次 WT 缓存预检、原方案串行重试、两项 WT 重放和产物保护核验。早期 WT 生成、排查、验证及阶段间隔另见任务日志。资源峰值来自并行阶段采样。全量串行对照缺失，正式阶段按实际耗时和资源记录呈现。']
    longest = pixal_timings[0]
    lines += [
        '',
        f"R2 Pixal 的最长单样本为 {longest['sample']}，生成耗时 "
        f"{longest['generation_seconds']:.2f} 秒，导出耗时 "
        f"{longest['export_seconds']:.2f} 秒（{longest['export_seconds']/60:.2f} 分钟）。"
        "该样本已通过产物和指标审计，导出长尾是本轮实际耗时的重要组成部分。",
        f"- [该样本分阶段耗时]({longest['source']})"]
    lines += ['', '## 验收与证据', '',
        'GSO 使用 1030 个历史原始 ID 与固定 revision 的原始 ZIP 镜像。NumPy 1.26.4 / PCG64(20261013) 重放的 P0、R2 样本与原工作簿一致。旧 MegaPose 整包链接失效，原始 ZIP 的 SHA/CRC、派生资产及冻结输入构成本轮数据验证证据。', '',
        '逐项检查覆盖原始输入/GT 哈希、历史参数、WT 缓存和父结果、可重载网格/材质、独立 Stage 1、完整指标与质量失败。TRELLIS.2 / Pixal3D 的相机、深度指标保留 N/A。', '',
        '图像复核覆盖 110 张冻结 GSO 输入、P0 全部十个样本和 R1 全部三十个样本的两视图。R2 选择前五个冻结 ID 加 hybrid CD-L1 最大的样本，去重补足十个，各看两视图。R2 的一百个样本全部完成自动产物和指标审计。裁剪与背景十五项、纹理种子六项均已检查。R1 按定性协议验收，显示采用各自边界归一化。', '',
        '复核记录了 P0 Hat hybrid 帽檐破碎、Horse Pixal 端部变形，R1 细环与首饰结构缺损、部分恐龙模型带暗色平板底座等现象。R2 的收纳箱 hybrid 顶部被表面填充，餐具与 Speed Boat 的 hybrid 显示朝向偏离输入，Office Depot hybrid 纹理出现大片浅色蓝灰斑块。纹理种子对照的眼睛、嘴部与背面颜色变化也有记录。', '',
        f"- [P0 图像复核]({AUDITS / '20261013-P0-gso-pilot-v1/visuals/review.json'})",
        f"- [R1 图像复核]({AUDITS / '20261013-R1-object-qual-v1/visuals/review.json'})",
        f"- [R2 图像复核]({AUDITS / '20261013-R2-gso-quant-v1/visuals/review.json'})",
        '', '工作簿已更新为本轮数值，既有人工结论和备注随相同实验身份保留。', '',
        f"- [迁移前后核心代码复核]({AUDITS / 'source-review.json'})",
        f"- [总验收记录]({AUDITS / 'final.json'})",
        f"- [工作簿数值与来源审计]({AUDITS / 'workbook.json'})",
        f"- [实验工作簿]({REPO / '.runtime/experiments-protocolv0-regenerated.xlsx'})",
        f"- [环境与执行记录]({REPO / 'RUNBOOK.md'})", '']
    if publish:
        (AUDITS / 'recovery-results-regenerated.md').write_text(chr(10).join(lines))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish-workbook', action='store_true')
    parser.add_argument('--source-ref', help='Git revision matching the recorded recovery source')
    args = parser.parse_args()
    with (REPO / '.runtime/recovery-gpu.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main(args.publish_workbook, args.source_ref)
