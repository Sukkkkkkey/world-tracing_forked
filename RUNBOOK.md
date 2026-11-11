# world_tracing 运行手册

当前状态见 [PROGRESS](/mnt/cpfs1/shuqiliu/code/world_tracing/PROGRESS.md)，模型和查看器使用说明见 [README](/mnt/cpfs1/shuqiliu/code/world_tracing/README.md)。历史实验、迁移和排障过程见 [历史记录](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/archived/20261105_recovery-results.md)。

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

## 调整评测协议与复用推理输出

仅调整指标、配准或渲染协议时，复用输入、checkpoint、推理与导出参数、seed 对应的有效产物。通过 `examples.evaluate_baseline_v2` 的 `--source-experiment` 指向已有输出，使用 `--seeds` 限定本轮范围，评测结果按独立 revision 保存。

新增方法、seed、生成配置、产物补齐以及明确的重复推理复现性实验，按相应范围执行推理。复用前核对来源与摘要，已有完整候选由缓存检查跳过。`scripts.run_baseline_v2` 用于补充 seed 的推理与评测队列。

当前 R2 v0.5 使用 `20261013-R2-gso-quant-v1` 的全部 400 份 seed 42 输出，完成 700 项评测。seed 43–49 队列已暂停。后续仅变更评测时继续沿用这些输出。[结果分析](docs/20261110_hybrid-baseline_gso-quant_eval-v0.5.md)

## 实验结果与历史验收

621 项恢复于 2026-11-07 完成，存档工作簿 SHA-256 为 `83d72e6b3505864b9c18e2b7c1c0db6261449782618820bfe181dffe7f6f6fcf`。恢复完成源码版本为 `f00327fc86540047c38cb8553de3d480f6cc32d4`。

- 总验收与逐项来源位于输出 `validation/recovery-20261105/`。
- 单卡策略证据位于 `validation/single-gpu-batch-20261105/`。
- 迁移前与恢复完成的源码、工作簿及日志位于 `recovery/20261105T044019Z/`。
- 质量失败样本、WT 父缓存、decoded PLY、GLB 和输入/GT 都参与结果解释与复核。

历史恢复校验通过 `configs/recovery_source.json` 定位恢复时的源码提交和审计清单摘要。`scripts/finalize_recovery.py` 的 `--source-ref` 可显式指定待核验的 Git 版本，源码必须匹配历史审计。该入口会重新生成阶段汇总，`--publish-workbook` 会重建项目 `.runtime/experiments-protocolv0-regenerated.xlsx` 与输出目录 `validation/recovery-20261105/recovery-results-regenerated.md`。[恢复结果与限制](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/archived/20261105_recovery-results.md)

## 文档与缓存整理

2026-11-07 清理采用明确的文件清单，核对实际路径、活动引用及归档摘要后执行。24 个一次性脚本已归档，权重暂存副本与正式文件 SHA 一致后清除。两套环境的 pip HTTP 缓存、项目 Python/pytest 缓存及空失败环境目录已清理。详细字节统计与保留项见输出 `recovery/20261107-maintenance/cleanup.json`。

项目安装、下载、推理、评价、审计和查看器的可复用入口继续由 Git 管理。正式结果、实验对照、失败重试证据、有效环境、权重、WT 父缓存和已验证 wheel 保留。

错误命名的 `.runtime/conda-pkgs:` 目录尚有约 45.4 MB 残留，CPFS 返回 ENOTEMPTY 并保留 `.efc` 文件。当前记录标注为保留项。两套有效环境在清理后均通过依赖检查。

2026-11-10 将八份中间报告合并为结果复现与初版评测结果，工作簿按 protocol v0 存档，根目录工作簿用于 v0.5。归档与重复文件映射见输出 `archives/20261110-baseline-consolidation/manifest.json`。

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

初次浏览器验收记录的两条组件更新错误已完成独立复现和修复，初始记录保存在输出 `validation/maintenance-20261107/viewer-browser.json`。修复后的回归结果与使用要求见下一节。

## Viser 前端修复与重建

Viser 1.1.1 把属性更新积累到消息批次末尾执行，组件删除在收到消息时立即执行。快速刷新输入图片可使同一批次同时包含属性更新和删除，导致属性更新指向已删除的组件。`scripts/patches/viser-gui-lifecycle.patch` 在组件、面板或模态框删除时清除该 UUID 之前积累的更新，重新创建后的更新仍按顺序执行。

`scripts/setup_base.sh` 自动调用 `scripts/setup_viser_client.py`。安装器检查项目环境、Viser 版本、源文件与依赖锁摘要，在项目构建目录完成前端测试、类型检查与打包后发布文件。原始前端保存在 `.runtime/cache/viser-client-original/`，已安装构建的摘要和工具版本记录在 Viser 的 `client/build/wt-gui-lifecycle.json`。重复执行会校验并复用有效构建，升级 Viser 时需同步复核补丁和锁文件。

首次构建需要 Node.js ≥24 与 npm。工具位于 PATH 时可直接执行以下命令。

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
source scripts/env.sh
python -B scripts/setup_viser_client.py
```

本服务器构建使用 Node.js 24.22.1 和 npm 11.6.3。Node 复用现有 VS Code Server 二进制，npm 来自官方注册表且已核验 SHA-512。需要重建时可指定当前工具路径。

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
source scripts/env.sh
export WT_NODE_BINARY=/root/.vscode-server/cli/servers/Stable-c4453f8ea430795f941c1b2ff6c9321135a74a02/server/node
export WT_NPM_CLI="$PWD/.runtime/toolchains/npm-11.6.3/bin/npm-cli.js"
python -B scripts/setup_viser_client.py
```

升级 VS Code Server 或更换机器后，将 `WT_NODE_BINARY` 指向可用的 Node.js，`WT_NPM_CLI` 指向 npm 的 JavaScript CLI 文件。构建成功后重启查看器并刷新浏览器页面即可加载新前端。

2026-11-07 验收完成。原版 8 项专项回归中 6 项失败，修复后 8 项全部通过。前端完整测试 726 项、Python 完整测试 156 项通过，TypeScript、Vite、依赖检查和历史恢复源码校验通过。浏览器完成三组连续操作，共 23 次，覆盖样本、质量、颜色、真值、翻页和刷新，随后恢复 full 显示。控制台错误为 0，五项结果与一项真值均显示正常。

验收报告、安装摘要、浏览器截图、JUnit 和原版失败证据位于输出 `validation/viewer-gui-fix-20261107/`，任务日志位于输出 `logs/viewer-gui-fix-20261107/`。
