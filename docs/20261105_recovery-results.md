# 新服务器实验恢复结果

本轮恢复包含主实验 600 项、裁剪/背景对照 15 项、纹理种子对照 6 项，使用历史样本、配置及 seed。

## 定量结果

CD 为独立注册与评价点集下的 Sim(3) Chamfer 欧氏距离，F@0.01 为比例。网格方法的形状评分使用导出重网格前的 decoded_mesh.ply。SSI 均值使用通过质量门槛的样本，缺失原因保存在 summary.json。

| 实验 | 方法 / 配置 | 形状有效数 | CD-L1 | F@0.01 | SSI 有效数 | SSI AbsRel |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| P0 | pixal3d / resolution1024-v1 | 10/10 | 0.014710 | 0.490073 | 0/10 | N/A |
| P0 | trellis2 / defaults-v1 | 10/10 | 0.009730 | 0.692355 | 0/10 | N/A |
| P0 | wt / defaults-v1 | 10/10 | 0.013857 | 0.510309 | 10/10 | 0.011925 |
| P0 | wt_trellis2 / defaults-v1 | 10/10 | 0.016656 | 0.424896 | 8/10 | 0.021827 |
| P0 | wt_trellis2 / shared-wt-v1 | 10/10 | 0.017740 | 0.399953 | 9/10 | 0.022820 |
| R2 | pixal3d / resolution1024-v1 | 100/100 | 0.011796 | 0.641301 | 0/100 | N/A |
| R2 | trellis2 / defaults-v1 | 100/100 | 0.009297 | 0.707455 | 0/100 | N/A |
| R2 | wt / defaults-v1 | 100/100 | 0.013285 | 0.569393 | 99/100 | 0.013624 |
| R2 | wt_trellis2 / defaults-v1 | 100/100 | 0.017753 | 0.443044 | 80/100 | 0.028675 |

## 与旧工作簿的差异

450 个定量 run 的历史样本与参数身份逐项核对通过。下表比较旧工作簿保存的数值与本轮重算值。

| 实验 | 方法 / 配置 | 旧 CD-L1 均值 | 新 CD-L1 均值 | 单样本最大绝对变化 |
| --- | --- | ---: | ---: | ---: |
| P0 | pixal3d / resolution1024-v1 | 0.014763 | 0.014710 | 0.000654 |
| P0 | trellis2 / defaults-v1 | 0.009740 | 0.009730 | 0.000244 |
| P0 | wt / defaults-v1 | 0.014764 | 0.013857 | 0.010489 |
| P0 | wt_trellis2 / defaults-v1 | 0.017195 | 0.016656 | 0.007269 |
| P0 | wt_trellis2 / shared-wt-v1 | 0.017190 | 0.017740 | 0.003321 |
| R2 | pixal3d / resolution1024-v1 | 0.011763 | 0.011796 | 0.004748 |
| R2 | trellis2 / defaults-v1 | 0.009319 | 0.009297 | 0.003781 |
| R2 | wt / defaults-v1 | 0.012963 | 0.013285 | 0.010654 |
| R2 | wt_trellis2 / defaults-v1 | 0.017255 | 0.017753 | 0.012108 |

R2 hybrid 的 SSI 有效样本由 82 个变为 80 个。前后共同有效的 79 个样本中，AbsRel 均值从 0.028529 变为 0.028805。
本轮 WT 与 hybrid 共同有效的 79 个样本中，AbsRel 均值分别为 0.013214 和 0.028135。

| 深度质量状态改变的样本 | 旧状态 | 新状态 | 本轮原因 |
| --- | --- | --- | --- |
| Cole_Hardware_Dishtowel_Stripe | complete | failed | Depth coverage below protocol threshold |
| Cole_Hardware_Flower_Pot_1025 | complete | failed | Rank-deficient or nonpositive scale fit |
| OXO_Soft_Works_Can_Opener_SnapLock | complete | failed | Depth coverage below protocol threshold |
| Wilton_PreCut_Parchment_Sheets_10_x_15_24_sheets | failed | complete | 通过原有质量门槛 |

旧逐样本预测和冻结输入摘要缺失，跨服务器数值差异的来源尚未定位。新机三个默认 WT 重放的 XYZ 和掩码与本轮 P0 逐元素一致。15 项裁剪与背景对照全部完成。旧工作簿和首轮 Pixal 环境修复前的结果已有归档。

- [逐项历史差异审计](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/historical-comparison.json)

## 单卡执行策略

R2 前的固定小样本测试测得，WT batch=2/4 吞吐提高约 5%–7%，同时 XYZ 出现数值差异。正式运行采用 WT batch=1。按完整样本分配的 TRELLIS.2 / hybrid 两进程测得 1.530 倍吞吐，Pixal 两进程测得 1.511 倍吞吐，测试中的解码几何及导出前纹理一致。

正式阶段通常约每两秒采样整卡显存和实例工作集。单次 GPU 查询限时十秒，连续三次查询失败或资源达到门槛时停止自己的工作进程。查询与资源余量恢复后，归档不完整尝试并串行重试。首轮 R2 因查询超时异常退出，v2 修复通过十四项回归。原尝试、旧版本决策、实际退出码和耗时均已归档。

- [单卡测试与决策](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_single-gpu-batch-review.md)
- [复核决策与证据摘要](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/single-gpu-batch-20261105/decision.json)

R2 两个 hybrid 在并行及原方案串行重试中均显存不足。修复采用历史方案中的独立行 LayerNorm 分块、同序拓扑分块和用后缓存释放，配置身份审计通过。59 个 CUDA 算例、自动求导回退及十三项文件保护测试通过，两个固定完整预训练样本的解码网格与导出前几何、纹理张量逐元素一致。两个失败 run 已重跑，各自新 WT 父缓存与原数组及 RGBA 精确相同。另外 298 个基线 run 的 1,689 个文件前后哈希一致。原失败日志和内存策略来源均有记录。

- [内存策略验证及决定](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/20261013-R2-gso-quant-v1/memory-policy-decision.json)
- [两项修复与原产物保护证明](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/20261013-R2-gso-quant-v1/memory-repair.json)

| 正式阶段 | 记录时长（分钟） | 并行显存峰值 GiB | 并行实例工作集 GiB | 初始工作进程退出码 | 归档后重试 run 数 |
| --- | ---: | ---: | ---: | --- | ---: |
| R1 / pixal | 97.17 | 37.45 | 104.32 | [0, 0] | 0 |
| R2 / baseline | 373.25 | 76.27 | 93.20 | [1, 1] | 2 |
| R2 / pixal | 425.25 | 36.22 | 115.64 | [0, 0] | 0 |

R1 / Pixal 和 R2 / Pixal 的记录覆盖工作进程从启动到退出的加载、推理、导出及内部重试。R2 / baseline 的记录为 v2 尝试与两项内存修复的时长之和，其中包括该次 WT 缓存预检、原方案串行重试、两项 WT 重放和产物保护核验。早期 WT 生成、排查、验证及阶段间隔另见任务日志。资源峰值来自并行阶段采样。全量串行对照缺失，正式阶段按实际耗时和资源记录呈现。

R2 Pixal 的最长单样本为 Hefty_Waste_Basket_Decorative_Bronze_85_liter，生成耗时 23.22 秒，导出耗时 16453.28 秒（274.22 分钟）。该样本已通过产物和指标审计，导出长尾是本轮实际耗时的重要组成部分。

- [该样本分阶段耗时](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/experiments/20261013-R2-gso-quant-v1/samples/Hefty_Waste_Basket_Decorative_Bronze_85_liter/pixal3d/resolution1024-v1/seed-0042/runtime.json)

## 验收与证据

GSO 使用 1030 个历史原始 ID 与固定 revision 的原始 ZIP 镜像。NumPy 1.26.4 / PCG64(20261013) 重放的 P0、R2 样本与原工作簿一致。旧 MegaPose 整包链接失效，原始 ZIP 的 SHA/CRC、派生资产及冻结输入构成本轮数据验证证据。

逐项检查覆盖原始输入/GT 哈希、历史参数、WT 缓存和父结果、可重载网格/材质、独立 Stage 1、完整指标与质量失败。TRELLIS.2 / Pixal3D 的相机、深度指标保留 N/A。

图像复核覆盖 110 张冻结 GSO 输入、P0 全部十个样本和 R1 全部三十个样本的两视图。R2 选择前五个冻结 ID 加 hybrid CD-L1 最大的样本，去重补足十个，各看两视图。R2 的一百个样本全部完成自动产物和指标审计。裁剪与背景十五项、纹理种子六项均已检查。R1 按定性协议验收，显示采用各自边界归一化。

复核记录了 P0 Hat hybrid 帽檐破碎、Horse Pixal 端部变形，R1 细环与首饰结构缺损、部分恐龙模型带暗色平板底座等现象。R2 的收纳箱 hybrid 顶部被表面填充，餐具与 Speed Boat 的 hybrid 显示朝向偏离输入，Office Depot hybrid 纹理出现大片浅色蓝灰斑块。纹理种子对照的眼睛、嘴部与背面颜色变化也有记录。

- [P0 图像复核](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/20261013-P0-gso-pilot-v1/visuals/review.json)
- [R1 图像复核](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/20261013-R1-object-qual-v1/visuals/review.json)
- [R2 图像复核](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/20261013-R2-gso-quant-v1/visuals/review.json)

工作簿已更新为本轮数值，既有人工结论和备注随相同实验身份保留。

- [迁移前后核心代码复核](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/source-review.json)
- [总验收记录](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/final.json)
- [工作簿数值与来源审计](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/workbook.json)
- [实验工作簿](/mnt/cpfs1/shuqiliu/code/world_tracing/experiments.xlsx)
- [环境与执行记录](/mnt/cpfs1/shuqiliu/code/world_tracing/RUNBOOK.md)

## 发布后复核与清理

2026-11-07 完成工作簿结构复核，三页分别为 25×32、55×32、405×32。合并区、列宽、行高和冻结窗格与旧版一致，所有本地目标链接可访问。20 个样式变化对应已报告的四个 SSI 质量状态变化。4 条人工结论、4 条实验目的和 11 条备注已保留。正式工作簿 SHA-256 为 `83d72e6b3505864b9c18e2b7c1c0db6261449782618820bfe181dffe7f6f6fcf`。

预览工具生成六张图像后异常退出，逐样本页的合并单元格有遮挡，旧工作簿预览出现相同现象。原生 Excel 界面尚未验证，数值、格式结构和链接已独立核对。[工作簿复核记录](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/workbook-review.json)

发布脚本新增的耗时检查首次误用了产物审计字段，导致发布提前退出。修正后按已审计 run.json 绑定耗时来源并记录文件摘要，最终发布通过。失败尝试与最终成功记录均已归档。[执行记录](/mnt/cpfs1/shuqiliu/code/world_tracing/RUNBOOK.md)

已核验归档并删除 31 个旧一次性脚本，清理失败环境副本，保留当前恢复依赖的内存辅助模块。README、PROGRESS、RUNBOOK 和历史报告说明已更新。[清理记录](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/cleanup.json)
