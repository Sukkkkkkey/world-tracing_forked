# world_tracing 项目进度

更新于 2026-11-12（Asia/Shanghai）。

## OOD 评测

2026-11-12 正式 v2 已完成 100 资产、99 类，WT/TRELLIS.2 共 200 次推理及 300/300 个评价阶段，失败 0。6,500 张 PNG 与数值审计通过。TRELLIS.2 decoded 的完整 CD-L1、可见 CD-L1、输入深度 MAE 相比 WT 分别降低 23.6%、32.1%、43.0%，三项配对 95% 区间均未跨零。WT 原像素 L0＋SSI 有效 97/100。结论限于本次冻结样本，训练资产交集和系统抽样设计方差仍未确定。正式结果已写入 [OOD 文档](docs/20261111_ood-evaluation.md)。完整统计与 100 资产对照图见 [正式审核报告](D:/647/vertex_remote/projects/WT_for_mesh/logs/20261112-ood-formal-review/review.md)，来源与打包校验记录位于 .runtime/logs/ood-v2-20261112/packet-verification.json。

2026-11-12 进度核查完成数据准备 100/100、WT 10/100、TRELLIS.2 1/100、权威评估 3/300。第二批因 GPU 查询超时停止，已归档中断状态，修复重复监控并采用单进程推理恢复。2 项针对性回归检查通过，恢复记录见 .runtime/logs/ood-v2-20261112/telemetry-recovery。

2026-11-12 用户已授权正式执行。v2 冻结 100 资产、99 类，按类别频率和五项几何特征排序进行等概率系统抽样，seed 42。后台数据准备与逐批推理、评估已启动，计划 200 次推理、300 个阶段，控制记录位于 .runtime/logs/ood-v2-20261112。

2026-11-11 启动 OmniObject3D 独立扫描来源评测，来源证据与冻结协议见 [OOD 记录](docs/20261111_ood-evaluation.md)。24 个官方类别包经 SHA-256 核验，10 个校准输入和 100 个正式输入已准备完成。校准完成 20 次推理、30/30 评价阶段及 650 张 PNG 验收，失败 0。审核材料已生成，数值 revision 为 92a06984acb0084b35c0。

2026-11-11 的 v1 正式队列在审核阶段停止，完成预测缓存为 0。2026-11-12 的新授权与 v2 执行记录见本节开头。

2026-11-11 按更新协议完成 10 资产缓存复核，WT L0＋SSI 有效 9/10，主表补齐五项深度指标与整图图像指标，76 项指标测试通过。对官方 5,911 资产/216 类完成分布审核，当前正式清单覆盖 24 类，所覆盖类别占总体资产 11.30%，凸包填充率两端各仅 2 个资产。更新结果和 v1 正式清单审核已写入 OOD 记录，后续采用 2026-11-12 冻结的 v2 清单执行。

## 当前评测

初版单 seed 结果与四视角扩展已完成，见 [初版评测协议结果](docs/archived/20261107_multiview-geometric-consistency.md)。[v0.5](docs/evaluation_protocol_v0.5.md) 采用配准后的完整与输入可见几何、双阶段独立 best-of-8 及 30 视角。P0 已完成 70/70 阶段及校准验收。R2 已完成 100 资产、seed 42 的 700/700 项评测，复用上一轮 400 份推理输出，新增推理 0 次。seed 43–49 已按用户要求暂停。完整测试 224 项通过，工作记录位于 .runtime/logs/baseline-v05-r2-20261110。[R2 结果分析](docs/20261110_hybrid-baseline_gso-quant_eval-v0.5.md)

旧工作簿存档为 `docs/archived/20261110_experiment_baseline_protocol_v0.xlsx`，根目录 `experiments.xlsx` 为 v0.5 空白表。报告、脚本及中间输出整理清单位于输出 `archives/20261110-baseline-consolidation/manifest.json`。

## 实验恢复完成

| 范围 | 完成数量 |
| --- | ---: |
| P0 | 50 |
| R1 | 150 |
| R2 | 400 |
| 裁剪与背景对照 | 15 |
| 纹理种子对照 | 6 |
| 合计 | 621 |

GSO 1030 个原始资产及其派生数据已恢复，110 份冻结视图与 GT 已重建，历史 P0/R2 样本身份核对通过。工作簿已发布并保留人工结论、实验目的和备注。[恢复结果](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/archived/20261105_recovery-results.md)

环境为 A100 80GB、Python 3.11.11、PyTorch 2.6.0+cu124、NumPy 1.26.4。基础环境与 Pixal3D 独立环境均已通过依赖及 CUDA 验证。WT、TRELLIS.2、Pixal3D 及所需辅助权重就绪。

正式执行采用 WT batch=1，网格和 Pixal 使用同卡双进程。R2 四方法形状评价均为 100/100 有效，SSI 深度有效数为 WT 99/100、hybrid 80/100。质量失败原因和跨服务器数值差异已记录。[单卡复核](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/archived/20261105_recovery-results.md)

## 项目整理

恢复完成版本已记录为本地 Git 提交 `f00327fc86540047c38cb8553de3d480f6cc32d4`。本轮清理已归档 24 个一次性启动与核验脚本，并清除经核对的权重下载副本、pip HTTP 缓存及空失败环境目录。清理记录位于输出 `recovery/20261107-maintenance/cleanup.json`。

viewer 修复 `57565ee` 已通过 cherry-pick 合入 main，生成提交 `089b8a0`。恢复时的源码审计固定到 `f00327f`，新增回归检查已验证后续 viewer 修改与历史恢复校验的兼容性。

合入后全套测试 151/151 通过，两套环境依赖与 CUDA 检查通过。真实产物加载 112/112 通过，覆盖 P0、R1 代表样本、R2 两个内存修复样本及一个常规样本、纹理种子对照、裁剪对照，以及 3,064,990,988 字节的解码网格。验收记录位于输出 `validation/maintenance-20261107/`。

快速切换时的 Viser 组件更新错误已复现并修复。Viser 1.1.1 在同一消息批次中立即删除组件，却在批次末尾应用此前积累的属性更新。补丁在删除时清除该组件的旧更新，并纳入环境安装入口。8 项专项回归在原版上出现 6 项失败，修复后全部通过。前端全套 726 项、Python 全套 156 项、类型检查、构建、依赖检查与历史源码校验通过。浏览器完成 23 次连续配置操作及完整质量恢复，控制台错误为 0，六组几何显示正常。修复证据保存在输出 `validation/viewer-gui-fix-20261107/`。

查看器现从主项目启动，使用 `wt-recovery` tmux 的 `viewer-p0` 会话与 18090 端口。旧 viewer 工作目录的运行记录已校验归档，工作目录已移除。当前服务信息保存在 `.runtime/viewer-service.json`。

已确认清理量为 8,555,782,565 字节，另归档并移除本轮两个核验脚本。编译缓存、已验证 wheel、有效环境、实验对照与失败重试证据继续保留。错误命名的旧 Conda 缓存目录仍有约 45.4 MB 残留，CPFS 删除返回 ENOTEMPTY 并产生 `.efc` 文件，当前清理记录保留该项。

## 后续研究与验证

- 跨服务器数值差异的来源仍待定位，旧逐样本预测与输入摘要缺失。
- R2 的深度质量失败、几何缺损、朝向和纹理问题已列入恢复报告。
- WT 场景、动态权重及动态参考输出的恢复尚未执行。
- 参数扫描、best-of-N、1536 模式及论文协议的数值复现尚待独立实验。
- 工作簿结构、数值与链接已核验，原生 Excel 界面的显示验证仍待完成。

当前命令与路径见 [运行手册](/mnt/cpfs1/shuqiliu/code/world_tracing/RUNBOOK.md)。早期阶段状态及排障过程见 [历史记录](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/archived/20261105_recovery-results.md)。
