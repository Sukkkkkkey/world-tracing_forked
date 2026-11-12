# 对比方法接入

模型源码使用独立 Git 仓库；本目录保存源码入口、环境准备和验证工具。
World Tracing 负责实验输入、结果契约、评价、查看器和汇总。

## Pixal3D

- 独立仓库：`/mnt/cpfs1/shuqiliu/code/Pixal3D`。
- 源码入口：`Pixal3D -> ../../Pixal3D`。Git 只记录链接，不将外部源码并入本仓库。
- 隔离环境：`/mnt/cpfs1/shuqiliu/code/world_tracing/.venv-pixal3d`，从已有 `world_tracing` 环境复制。
- 固定来源：[pixal3d/sources.lock](pixal3d/sources.lock)。MoGe-2、NAF 源码放在本仓库已忽略的 `dependencies/MoGe2`、`dependencies/NAF`。
- TRELLIS.2 原生扩展沿用根目录 `dependencies.lock` 的版本；该锁由旧安装脚本解析，因此新增方法使用独立锁，避免改变旧安装入口。
- 原始数据：`/mnt/oss1/lemonade_factory/SYNC/shuqiliu/data/raw`，只读。
- 权重：`/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/weights`；缓存/临时文件位于 CPFS 项目 `.runtime/cache/pixal3d`、`.runtime/tmp/pixal3d`，模型文件不纳入 Git。
- 恢复安装与校验日志：`/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/logs/recovery-20261105` 中的 pixal-setup、pixal-clone-repair、pixal-revalidation。
- 环境检查报告：`/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/pixal3d-environment.json`。

2026-11-07 新服务器 Pixal3D 的 140 项恢复全部完成，包括 P0 10/10、R1 30/30、R2 100/100 推理与产物验收。
P0/R2 形状评价和工作簿发布均已完成。R1/R2 使用复核后的同卡双进程，R2 工作进程阶段耗时 425.25 分钟。相机/深度指标的适用边界见下文，环境、执行及质量问题见 [恢复结果报告](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_recovery-results.md)。

`wt/baselines/pixal3d.py` 封装模型生命周期，`wt/baselines/pixal3d_batch.py` 管理追加与续跑，
`examples/infer_pixal3d_batch.py` 提供独立推理入口，输出现有 experiment schema。
推理使用新环境，评价/查看器使用原环境，通过磁盘产物联动。

## 环境准备

在专用 tmux 会话内执行，不修改 Shell、Conda 或网络全局配置：

```bash
/etc/dsw/runtime/tmux/bin/tmux -L wt-recovery new-session -s wt-pixal3d-setup
cd /mnt/cpfs1/shuqiliu/code/world_tracing
bash compare_methods/pixal3d/setup.sh prepare
bash compare_methods/pixal3d/setup.sh install
bash compare_methods/pixal3d/setup.sh check
```

`prepare` 校验现有源码的版本及工作区；不存在时克隆固定提交、创建链接，离线复制基础环境。
已有源码有改动或版本不符时停止，不自动覆盖。Conda 源只通过当前命令指定。
本轮发现 Conda 克隆会覆盖 8 个 pip 包并残留重复版本元数据；prepare/check 已纳入 reconcile_clone.py，以固定缓存 wheel 修复后校验 192 个安装文件。来源、摘要及安装步骤保存在 clone-python.lock.json 和 clone-python-repair.txt，基础环境不因此修改。
`install` 仅写入隔离环境；不直接执行上游 requirements，也不运行原 `scripts/setup_all.sh`。
安装完成后生成 `pixal3d/requirements.lock.txt`，它是本机安装快照，包含本地扩展路径，
不应脱离基础环境与源码锁单独作为跨机器安装清单。
已验证的 NATTEN wheel 保存在 `.runtime/cache/pixal3d/wheels/`，同配置安装时先校验 SHA-256 后复用；
当前恢复使用 Python 3.11 / PyTorch 2.6.0+cu124 / SM80 的重新编译 wheel，摘要见 pixal3d/natten-sm80.lock.json；其他 Python、PyTorch 或 GPU 架构不能直接套用该二进制。

常规运行环境入口：

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
source /mnt/cpfs1/shuqiliu/code/world_tracing/compare_methods/pixal3d/env.sh
```

`env.sh` 将独立环境加入当前 PATH；setup 通过 Conda 激活并校验目标环境。
当前默认使用 CUDA 12.4、A100 架构 8.0，NATTEN 使用 4 个编译 worker。NATTEN 0.21.0 的 `NATTEN_CUDA_ARCH`
也必须采用小数形式 `8.0`，不能填 `80`。
依赖下载默认直连；需要镜像时可针对当前命令指定 `WT_PIXAL3D_PIP_INDEX`。

## 与上游安装说明的差异

1. 保留 PyTorch 2.6.0/cu124、NumPy 1.26.4 和既有 OpenCV/Transformers，避免替换已验证的原生扩展 ABI。
2. 固定 MoGe-2 源码，通过 `PYTHONPATH` 导入其推理模块；不安装其完整训练/Gradio distribution。
   上游未固定的 MoGe Git 依赖现在会获取 MoGe-3，不能用于本实验的复现。
3. 安装官方指定的 utils3d wheel，仅替换新环境中的副本。
   文件 URL 为 `https://github.com/LDYang694/Storages/releases/download/20260430/utils3d-0.0.2-py3-none-any.whl`，
   SHA-256 为 `ff63440827d6933807dd06c8a5a2db7e51fd5f33c7f3dddcc766a80e0f419252`。
   它与基础环境同名同版本，但包含 MoGe-2 的 `utils3d.pt` 与深度反投影兼容接口。
4. NAF 使用固定本地源码，后续权重加载也须固定来源；不让正式实验隐式拉取 Torch Hub 最新代码。
5. 原生 Pixal3D 普通模式默认 1536；已采用的对齐配置显式指定 1024，配置名使用 `resolution1024-v1`。

## 第一阶段验证边界

`check_environment.py` 在离线模式下检查推理类导入，以及真实 CUDA 上的
NATTEN/FlashAttention 与 SDPA 对照、NAF 常量特征上采样、MoGe 焦距/平移恢复与相机 API、
Pixal3D 稀疏卷积与 dense Conv3d 对照、O-Voxel 编解码、CuMesh 和 nvdiffrast。
NAF 使用随机参数，不下载模型权重；这些检查不代表预训练推理、GLB 纹理导出或 R1/R2 已完成。
只有报告存在且 `status=passed` 才表示该轮检查通过；实际执行状态见根目录 RUNBOOK 和 PROGRESS。

## 权重和批量运行

`pixal3d/weights.lock.json` 固定 Pixal3D 单视图、MoGe-2、DINOv3、NAF 的版本、文件大小及摘要。
下载器优先按 SHA-256 复用旧 TRELLIS 权重；镜像只接收匿名请求。
NAF 从固定本地源码创建，显式加载已校验的 checkpoint，不执行远程 Torch Hub 代码。

在专用 tmux 中激活新环境、source `env.sh` 后执行：

```bash
python compare_methods/pixal3d/fetch_weights.py
python examples/infer_pixal3d_batch.py \
  --experiment /mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/experiments/20261013-R1-object-qual-v1 \
  --sample-ids obj014_leather_briefcase
```

去掉 `--sample-ids` 运行该实验全部冻结输入；将实验名替换为
`20261013-P0-gso-pilot-v1` / `20261013-R2-gso-quant-v1` 即运行已有 10 / 100 个 GSO 输入。
当前服务器只有一张 A100，常规入口使用 device 0。恢复队列通过 scripts/run_parallel_recovery.py 在同一张卡上运行两个独立进程，各处理不重叠的完整样本；显存仍为单图张量 batch=1，资源监控与回退见 [单卡复核](../docs/20261105_single-gpu-batch-review.md)。多卡参数仅在实际存在对应 GPU 时适用。
入口持有原批量入口相同的 `.writer.lock`，拒绝同一实验的并发写入。
它不改写 `input.json`、旧方法结果或旧配置。配置/源码摘要不一致时拒绝覆盖；完整产物校验通过时跳过。
遇到第一个模型错误即停止，保留后续 `planned` 状态，修复后可恢复。

产物位置：`samples/<sample_id>/pixal3d/resolution1024-v1/seed-0042/`。
保存 decoder 原始网格、纹理 GLB、实际预处理图、MoGe 内参/归一化距离、耗时/峰值显存、逐样本日志和摘要。
`runtime.json` 的显存峰值来自 PyTorch allocator，不包含 CuMesh 等扩展直接分配的 CUDA 内存；不能据此单独估计整卡峰值。
解码坐标是 `pixal3d_yup`；官方 GLB 变换与 O-Voxel 变换复合为 `diag(-1,1,-1)`，查看器已单独适配。

评价使用原 `world_tracing` 环境及 `scripts/env.sh`，只选择新增方法：

```bash
python examples/evaluate_gso.py \
  --experiment /mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/experiments/20261013-P0-gso-pilot-v1 \
  --methods pixal3d --workers 2
```

继续使用 `gso-shape-sim3-v1` 比较 remesh/decimation 前的 decoder mesh。
Pixal3D 的 FoV 来自 MoGe，距离由归一化物体立方体计算，尚未建立到原始视图真实尺度的变换；
因此当前 native-camera 和 SSI-depth 指标标记 N/A，并记录原因，不借用 GT 内参或 GT 拟合位姿。
当前工作簿由 `evaluation/research_workbook.py` 生成实验总览、P0_逐样本和 R2_逐样本；保留人工注释，按实际成功状态汇总。旧 `FourMethodShape`/`MetricSummary` 名称仅属于历史版本。
查看器初始显示所有配置，避免隐藏名称不同的 Pixal3D 配置。
