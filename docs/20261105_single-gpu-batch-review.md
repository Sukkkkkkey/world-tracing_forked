# R2 前单卡批量推理测试与执行复核

2026-11-07 完成复核。测试与正式推理使用 A100 80GB、10 CPU 配额和 128 GiB 实例内存。

## 固定样本测试

WT 每个设置运行四个固定样本，各用灰底与黑底并重复两轮，共十六次。网格测试使用两个样本的 native 与 hybrid，共四项。Pixal 使用相同两个样本，共两项。下表为推理与导出工作段的实测。

| 路径 | 对照→候选耗时（秒） | 吞吐倍数 | 候选显存峰值 GiB | 实例工作集峰值 GiB | 采用结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| WT batch=1→2 | 152.07→144.33 | 1.054 | 11.34 | 41.44 | 正式使用 batch=1 |
| WT batch=1→4 | 152.07→141.55 | 1.074 | 14.38 | 41.45 | 正式使用 batch=1 |
| TRELLIS.2 / hybrid 单进程→双进程 | 1195.42→781.29 | 1.530 | 22.85 | 96.43 | 采用按完整样本分配的双进程 |
| Pixal3D 单进程→双进程 | 294.35→194.82 | 1.511 | 36.20 | 104.88 | 采用双进程 |

WT batch=1 的随机流适配与原路径逐元素一致。batch=2/4 的掩码、RGB 和内参一致，XYZ 最大绝对差分别为 0.24519658 和 0.26528430。因此正式推理采用单图 WT 路径。

网格测试的 decoded PLY 与本轮 P0 一致，Pixal 预处理 PNG 也一致。单进程与双进程的导出前几何、稀疏坐标和纹理张量摘要逐项匹配。一致性检验覆盖这些明确的输出表示。

首轮网格任务按方法交错分片，两个进程分别集中处理 native 和 hybrid，整体吞吐仅为单进程的 1.004 倍。按完整样本分片后测得 1.530 倍，两轮测试证据均已保留。

## 正式调度

WT 缓存先串行生成和校验，随后将完整样本分配给同卡两个独立进程。每个进程使用 CUDA device 0 和四个 CPU 线程。单写者锁、互不重叠的分片及各自汇总文件保护实验目录。

资源采样通常约每两秒执行一次。GPU 查询限时十秒，连续三次查询失败、显存超过 78 GiB 或实例工作集超过 122 GiB 时停止本任务的工作进程。资源恢复后归档不完整尝试，再串行重试。v1 的十一项调度测试加上 v2 的三项遥测异常回归，共十四项通过。

首轮 R2 于 11 月 6 日 05:29 UTC 因 GPU 查询超时异常退出。v2 增加暂时查询失败恢复、连续失败门槛和 CPU 压力检查。原 v1 记录与 R1 的执行证据均已封存，恢复继续使用二百份已完成 WT 缓存和一百个 WT 输出。

## 全量执行结果

| 阶段 | 执行报告时长（分钟） | 并行显存峰值 GiB | 并行实例工作集 GiB | 结果 |
| --- | ---: | ---: | ---: | --- |
| R1 Pixal，三十项 | 97.17 | 37.45 | 104.32 | 完成，两个进程退出 0 |
| R2 基线，含原尝试和两项修复 | 373.25 | 76.27 | 93.20 | 三百项完成并通过评价与审计 |
| R2 Pixal，一百项 | 425.25 | 36.22 | 115.64 | 完成，两个进程退出 0 |

Pixal 的记录覆盖工作进程启动、加载、推理与导出。R2 基线记录为 v2 原尝试与两项内存修复工作段的时长之和。各阶段的评价、审计、早期 WT 生成和排查时间另存任务日志。全量串行对照缺失，正式阶段使用实际耗时和资源记录描述性能。

R1 的 obj085_pterodactyl 生成耗时 21.66 秒，导出耗时 3942.41 秒。R2 的 Hefty_Waste_Basket_Decorative_Bronze_85_liter 生成耗时 23.22 秒，导出耗时 16453.28 秒，约 274.22 分钟。这两个导出长尾均最终完成，并通过产物审计。

## 两项 hybrid 显存修复

Pokémon 双游戏盒与 3M 防滑胶带在并行和原方案串行重试中都显存不足。前者在 LayerNorm 转换时失败，后者在 CuMesh fill_holes / get_edges 阶段失败。原始失败目录、退出码和日志已归档。

修复采用历史 v6 中的独立行 LayerNorm 分块、保持顺序的拓扑分块、推理参数梯度关闭及用后卷积缓存释放。实际配置身份审计通过。验证覆盖五十九个 CUDA 算例、自动求导回退、十三项文件保护测试，以及两个完整预训练 P0 hybrid 的几何和纹理张量精确比对。

两个失败 run 采用带内存策略来源记录的 backend，各自 WT 父缓存重新生成后逐数组和 RGBA 比对通过。另外二百九十八个基线 run 的 1689 个文件前后哈希一致。

Pokémon 的 decoded mesh 含 74853796 个顶点和 145358310 个面，mesh 工作段耗时 414.72 秒。3M 含 50119548 个顶点和 189504322 个面，mesh 工作段耗时 240.51 秒。两项修复均通过正式评价与产物审计。复合执行报告保留原并行退出 [1, 1]、原串行退出 1，以及最终内存修复退出 0。

## 证据与入口

- [采用决策](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/single-gpu-batch-20261105/decision.json)
- [首轮测试](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/single-gpu-batch-20261105/20261105T164410Z/report.json)
- [均衡网格复测](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/single-gpu-batch-20261105/balanced-20261106T023018Z/report.json)
- [十四项调度回归](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/parallel-runner-tests-v2.json)
- [内存策略验证与源码摘要](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/20261013-R2-gso-quant-v1/memory-policy-decision.json)
- [两项修复和产物保护证明](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/recovery-20261105/20261013-R2-gso-quant-v1/memory-repair.json)

测试入口为 scripts/benchmark_single_gpu.py、scripts/benchmark_wt_batch.py 和 scripts/benchmark_balanced_mesh.py。正式调度由 scripts/run_parallel_recovery.py 执行，scripts/check_recovery_performance.py 核对采用决策与源码摘要。两项内存修复及验证入口保存在 scripts/recovery_memory.py、scripts/repair_recovery_memory.py 和对应验证脚本中。
