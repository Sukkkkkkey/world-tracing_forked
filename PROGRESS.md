# world_tracing 项目进度

更新于 2026-11-07（Asia/Shanghai）。

## 实验恢复完成

| 范围 | 完成数量 |
| --- | ---: |
| P0 | 50 |
| R1 | 150 |
| R2 | 400 |
| 裁剪与背景对照 | 15 |
| 纹理种子对照 | 6 |
| 合计 | 621 |

GSO 1030 个原始资产及其派生数据已恢复，110 份冻结视图与 GT 已重建，历史 P0/R2 样本身份核对通过。工作簿已发布并保留人工结论、实验目的和备注。[恢复结果](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_recovery-results.md)

环境为 A100 80GB、Python 3.11.11、PyTorch 2.6.0+cu124、NumPy 1.26.4。基础环境与 Pixal3D 独立环境均已通过依赖及 CUDA 验证。WT、TRELLIS.2、Pixal3D 及所需辅助权重就绪。

正式执行采用 WT batch=1，网格和 Pixal 使用同卡双进程。R2 四方法形状评价均为 100/100 有效，SSI 深度有效数为 WT 99/100、hybrid 80/100。质量失败原因和跨服务器数值差异已记录。[单卡复核](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_single-gpu-batch-review.md)

## 项目整理

恢复完成版本已记录为本地 Git 提交 `f00327fc86540047c38cb8553de3d480f6cc32d4`。本轮清理已归档 24 个一次性启动与核验脚本，并清除经核对的权重下载副本、pip HTTP 缓存及空失败环境目录。清理记录位于输出 `recovery/20261107-maintenance/cleanup.json`。

viewer 修复正在按 `57565ee` 合入。文档、历史验收版本定位和合入后的验证随本轮整理更新。

## 后续研究与验证

- 跨服务器数值差异的来源仍待定位，旧逐样本预测与输入摘要缺失。
- R2 的深度质量失败、几何缺损、朝向和纹理问题已列入恢复报告。
- WT 场景、动态权重及动态参考输出的恢复尚未执行。
- 参数扫描、best-of-N、1536 模式及论文协议的数值复现尚待独立实验。
- 工作簿结构、数值与链接已核验，原生 Excel 界面的显示验证仍待完成。

当前命令与路径见 [运行手册](/mnt/cpfs1/shuqiliu/code/world_tracing/RUNBOOK.md)。早期阶段状态及排障过程见 [历史记录](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261107_project-history.md)。
