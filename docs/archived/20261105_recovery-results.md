# 结果复现

2026-11-10 汇总。恢复对象为旧服务器的固定样本、配置与 seed。原始工作簿存于 [初版结果工作簿](20261110_experiment_baseline_protocol_v0.xlsx)，当前评测分析见 [初版评测协议结果](20261107_multiview-geometric-consistency.md)。

## 恢复范围

| 实验 | 输入与用途 | 完成数 |
| --- | --- | ---: |
| P0 | 10 个 GSO 资产，含 Hybrid shared-WT 对照 | 50 |
| R1 | 30 张 object 图像，定性检查 | 150 |
| R2 | 100 个 GSO 资产，四方法主定量实验 | 400 |
| 裁剪、背景对照 | 预处理敏感性 | 15 |
| 纹理种子对照 | 固定几何的纹理变化 | 6 |
| 合计 | 2026-11-07 完成恢复验收 | 621 |

GSO 1030 个原始资产、110 份 P0/R2 输入与 GT 已恢复。P0/R2 共 450 个定量运行的样本、配置和 seed 身份核对通过。R1 缺少几何 GT，结论限于定性观察。[总验收](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/final.json>)

## 旧服务器与恢复结果

下表均为完整几何经 GT 辅助正 Sim(3) 配准后的 CD-L1，seed=42，GT 对角线 D=1。Mesh 使用 decoded 输出，WT 使用六层有效点云。

| 实验 | 方法 / 配置 | 旧均值 | 恢复均值 | 单样本最大绝对变化 |
| --- | --- | ---: | ---: | ---: |
| P0 | Pixal3D / resolution1024-v1 | 0.014763 | 0.014710 | 0.000654 |
| P0 | TRELLIS.2 / defaults-v1 | 0.009740 | 0.009730 | 0.000244 |
| P0 | WT / defaults-v1 | 0.014764 | 0.013857 | 0.010489 |
| P0 | Hybrid / defaults-v1 | 0.017195 | 0.016656 | 0.007269 |
| P0 | Hybrid / shared-wt-v1 | 0.017190 | 0.017740 | 0.003321 |
| R2 | Pixal3D / resolution1024-v1 | 0.011763 | 0.011796 | 0.004748 |
| R2 | TRELLIS.2 / defaults-v1 | 0.009319 | 0.009297 | 0.003781 |
| R2 | WT / defaults-v1 | 0.012963 | 0.013285 | 0.010654 |
| R2 | Hybrid / defaults-v1 | 0.017255 | 0.017753 | 0.012108 |

R2 的完整几何均值排序延续为 TRELLIS.2、Pixal3D、WT、Hybrid。TRELLIS.2/Pixal3D 的均值变化低于 0.3%，WT/Hybrid 分别变化 +2.48%/+2.89%。R2 逐样本 CD 绝对变化均值依次为 0.000298、0.000248、0.002236、0.001937，新旧秩相关依次为 0.984、0.997、0.851、0.911。[历史对照](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/historical-comparison.json>) [配对统计](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/baseline-analysis-20261110/statistics.json>)

**可确认** WT 及 Hybrid 的跨环境变化更大。A100 环境内三个 WT 重放样本的 XYZ、mask 与恢复输出逐元素一致。108 个历史 Python 文件中 104 个逐字节一致，包含 WT 核心与几何评测。**待确认** GPU、依赖、输入重建和随机数执行路径各自的贡献。旧服务器逐样本预测、冻结输入摘要和完整运行环境缺失，现有证据不足以单独归因于 4090/A100。[源码复核](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/source-review.json>)

R2 Hybrid 的 SSI 深度有效数从 82 变为 80，三项由有效变失败、一项由失败变有效。新旧共同有效 79 个资产的 AbsRel 为 0.028529→0.028805。失败集合变化应与均值一起解释。

## 执行与验收

- 恢复环境为 A100 80GB、Python 3.11.11、PyTorch 2.6.0+cu124、NumPy 1.26.4。WT tensor batch 保持 1。Batch 2/4 的吞吐仅提升约 5.4%/7.4%，同时改变 XYZ 输出。按完整样本分配的双进程使 mesh、Pixal3D 吞吐分别提升约 53.0%、51.1%。[单卡决策](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/single-gpu-batch-20261105/decision.json>)
- 两个超大 Hybrid 样本通过分块内存修复完成推理。两个固定预训练样本的等价检查及 59 项 CUDA 检查、13 项文件保护测试通过。几何质量由评测结果单独判断。[内存修复](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/20261013-R2-gso-quant-v1/memory-repair.json>)
- 查看器已恢复，112 项真实产物加载检查通过，覆盖 3.06 GB 网格。快速切换的组件更新问题已修复，前端 726 项、Python 156 项测试通过，23 次浏览器操作未出现控制台错误。当前启动方式见运行手册。[查看器验收](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/viewer-gui-fix-20261107/>) [运行手册](../RUNBOOK.md)
- 图像复核覆盖 P0 全部 10 个资产、R1 全部 30 个样本及 R2 选取的 10 个样本。仍观察到薄结构缺失、额外底板、局部填充、朝向和纹理问题。R2 其余样本的逐图人工检查待补充。

## 记录位置

- 正式产物位于输出目录的 `experiments/20261013-{P0-gso-pilot,R1-object-qual,R2-gso-quant}-v1/`。恢复总审计、历史差异与输入核验位于 `validation/recovery-20261105/`。
- 工作簿存档 SHA-256 为 `83d72e6b3505864b9c18e2b7c1c0db6261449782618820bfe181dffe7f6f6fcf`。人工结论、目的和备注随原文件保存。
- 合并前八份报告、结束使用的脚本和过期评测尝试集中存于输出 `archives/20261110-baseline-consolidation/`。清理清单记录原路径、摘要、归档位置及重复文件的保留来源。[整理清单](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/archives/20261110-baseline-consolidation/manifest.json>)
