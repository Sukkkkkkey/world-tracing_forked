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

清理采用明确的文件清单，核对实际路径、活动引用及归档摘要后执行。24 个一次性脚本已归档，权重暂存副本与正式文件 SHA 一致后清除。两套环境的 pip HTTP 缓存、项目 Python/pytest 缓存及空失败环境目录已清理。详细字节统计与保留项见输出 `recovery/20261107-maintenance/cleanup.json`。

项目安装、下载、推理、评价、审计和查看器的可复用入口继续由 Git 管理。正式结果、实验对照、失败重试证据、有效环境、权重、WT 父缓存和已验证 wheel 保留。

错误命名的 `.runtime/conda-pkgs:` 目录尚有约 45.4 MB 残留，CPFS 返回 ENOTEMPTY 并保留 `.efc` 文件。当前记录标注为保留项。两套有效环境在清理后均通过依赖检查。

## 查看器服务与合入验收

查看器修复提交 `57565ee` 已 cherry-pick 为 main 的 `089b8a0`。旧分支保留修复历史，旧工作目录的运行记录已归档到输出 `recovery/20261107-maintenance/viewer-worktree-runtime.tar.gz` 并逐文件校验，工作目录已移除。

当前服务从 `/mnt/cpfs1/shuqiliu/code/world_tracing` 启动，tmux socket 为 `wt-recovery`、会话为 `viewer-p0`、端口为 18090。PID 与命令记录在 `.runtime/viewer-service.json`，活动日志为 `.runtime/logs/viewer-p0.log`。已有服务的连接方式如下。

```powershell
ssh -N -L 127.0.0.1:18090:127.0.0.1:18090 ali-dsw
```

浏览器访问 [P0 查看器](http://127.0.0.1:18090)。启动其他实验时，先核对当前 PID 与端口，再使用对应实验目录。

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
source scripts/env.sh
CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  python -uB viewer.py \
  --experiment "$WT_OUTPUT_ROOT/experiments/20261013-P0-gso-pilot-v1" --port 18090
```

本轮全套测试 151 项通过，两个环境的依赖检查及 CUDA 检查通过。真实产物加载检查 112 项通过，包含 R2 修复样本和 3.06 GB 解码网格。详细报告、JUnit 与服务验收保存在输出 `validation/maintenance-20261107/`，执行日志保存在输出 `logs/maintenance-20261107/`。

本轮两个临时核验脚本和日志已归档到输出 `recovery/20261107-maintenance/maintenance-checks-inputs.tar.gz`。恢复审计、数据处理、推理与查看器入口继续通过项目源码使用。

浏览器复核记录了快速切换配置时的两条 Viser 组件更新错误，最终选择与模型显示正常。该问题及控制台信息保存在输出 `validation/maintenance-20261107/viewer-browser.json`，后续修改查看器时需复查。
