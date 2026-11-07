# world_tracing 运行手册

当前状态见 [PROGRESS](/mnt/cpfs1/shuqiliu/code/world_tracing/PROGRESS.md)，模型和查看器使用说明见 [README](/mnt/cpfs1/shuqiliu/code/world_tracing/README.md)。历史实验、迁移和排障过程见 [历史记录](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261107_project-history.md)。

## 当前目录与环境

| 用途 | 路径 |
| --- | --- |
| 代码与两套隔离环境 | `/mnt/cpfs1/shuqiliu/code/world_tracing` |
| 原始数据 | `/mnt/oss1/lemonade_factory/SYNC/shuqiliu/data/raw` |
| 处理数据 | `/mnt/oss1/lemonade_factory/SYNC/shuqiliu/data/processed/world_tracing` |
| 实验、权重与验收记录 | `/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing` |
| 活动日志及执行缓存 | 项目 `.runtime/` |

当前实例使用 A100 80GB / SM80、Python 3.11.11、PyTorch 2.6.0+cu124、NumPy 1.26.4。进入项目后加载基础环境。

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
source scripts/env.sh
python -m pip check
```

Pixal3D 使用独立环境入口。

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
source compare_methods/pixal3d/env.sh
python -m pip check
```

安装来源固定在 `dependencies.lock`、`requirements.recovery.txt`、`configs/conda_runtime.lock.json` 和 `compare_methods/pixal3d/` 的锁文件。NATTEN、FlashAttention 和 Pixal 克隆修复所需 wheel 具有已核验的本地副本。安装步骤见 README 和对比方法说明。

## 权重下载与离线使用

已恢复 WT object、TRELLIS.2、Pixal3D 及所需 DINOv3、RMBG-2.0、MoGe/NAF 权重。固定来源和摘要保存在权重清单与对应锁文件。DINOv3/RMBG-2.0 使用 ModelScope，公开 HF 文件经 hf-mirror 取得。

`scripts/download_object.py` 返回已缓存的 WT checkpoint。授权凭据从权限为 600 的 `.runtime/hf_token` 读取，下载与核验工具见 README。已有权重的常规推理可启用离线模式，以下命令离线核验 WT 物体权重。

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
source scripts/env.sh
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python scripts/verify_weights.py --models object
```

## 长时任务与日志

使用专用 tmux 会话，并由 `scripts/run_task.py` 记录 PID、命令、时间和退出码。下面的命令可为新任务创建会话。

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
/etc/dsw/runtime/tmux/bin/tmux -L wt-recovery new-session -s wt-run
source scripts/env.sh
```

活动日志位于 CPFS，完成记录复制到输出目录。SSH 断线后先核对已有 PID 和状态文件。运行前检查 GPU、实例内存及目标目录。

## 实验结果与历史验收

621 项恢复于 2026-11-07 完成，工作簿 SHA-256 为 `83d72e6b3505864b9c18e2b7c1c0db6261449782618820bfe181dffe7f6f6fcf`。恢复完成源码版本为 `f00327fc86540047c38cb8553de3d480f6cc32d4`。

- 总验收与逐项来源位于输出 `validation/recovery-20261105/`。
- 单卡策略证据位于 `validation/single-gpu-batch-20261105/`。
- 迁移前与恢复完成的源码、工作簿及日志位于 `recovery/20261105T044019Z/`。
- 质量失败样本、WT 父缓存、decoded PLY、GLB 和输入/GT 都参与结果解释与复核。

历史恢复校验通过 `configs/recovery_source.json` 定位恢复时的源码提交和审计清单摘要。`scripts/finalize_recovery.py` 的 `--source-ref` 可显式指定待核验的 Git 版本，源码必须匹配历史审计。该入口会重新生成阶段汇总，`--publish-workbook` 会发布工作簿。[恢复结果与限制](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_recovery-results.md)

## 本轮文档与缓存整理

清理采用明确的文件清单，核对实际路径、活动引用及归档摘要后执行。24 个一次性脚本已归档，权重暂存副本与正式文件 SHA 一致后清除。两套环境的 pip HTTP 缓存及空失败环境目录已清理。详细字节统计与保留项见输出 `recovery/20261107-maintenance/cleanup.json`。

项目安装、下载、推理、评价、审计和查看器的可复用入口继续由 Git 管理。正式结果、实验对照、失败重试证据、有效环境、权重、WT 父缓存和已验证 wheel 保留。

viewer 合入与服务迁移的最终记录将在本轮验收后补充。
