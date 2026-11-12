# World Tracing

**Generative Pixel-Aligned Geometry Beyond the Visible**

World Tracing（WT）从单张图像或视频预测像素对齐的多层三维几何，包括被遮挡的表面。本仓库提供物体、场景和动态几何的推理代码，以及 WT + TRELLIS.2 纹理网格方向的开发基础；不包含训练流程。

[论文](https://arxiv.org/abs/2606.13652) · [上游代码](https://github.com/haoz19/world-tracing) · [本仓库来源](https://github.com/Sukkkkkkey/world-tracing_forked)

按推理顺序的 class/function 调用链、张量形状及坐标/尺度约定见本地文档 `docs/20261013_CODE-STRUCTURE.md`。

定量评测的指标公式、配准与采样、失败判定及复现约定见 [评估协议](docs/archived/evaluation_protocol_v0.md)。

新一轮评测采用 [v0.5 协议](docs/evaluation_protocol_v0.5.md)，以配准后的完整与输入可见几何为主，四方法各 8 个 seed，decoded/GLB 分组独立按完整 CD-L1 选 seed。P0 已完成 10 资产、seed 42 的 70 项校准验收。默认保存 input-view PNG，--save-multiview-renders 开启 30 视角 PNG，全部视角指标与 NPZ 均保存。

多视角几何采用原生 mesh 与统一 surfel 两条路径。加载 `scripts/env.sh` 后运行 `python -B -m scripts.setup_multiview`，再运行 `python -B -m examples.evaluate_multiview "$WT_OUTPUT_ROOT/experiments/20261013-R2-gso-quant-v1"`。逐运行结果由 `multiview.json` 索引，分组统计与 mesh 配对差异保存在 `$WT_OUTPUT_ROOT/evaluation/multiview/<revision>/<experiment>/summary.json`。已有结果的校验与汇总可运行 `python -B -m examples.summarize_multiview "$WT_OUTPUT_ROOT/experiments/20261013-R2-gso-quant-v1"`。[参数选择、P0 验收与 R2 结果](docs/archived/20261107_multiview-geometric-consistency.md)

## Package layout

```text
wt/                         Python 包
├── model.py                MultilayerXYZModel 与模型骨干封装
├── inference.py            单图、多视图、视频推理接口
├── sampling.py             Euler ODE / flow-matching 采样
├── data.py                 图像、视频加载，前景抠图与预处理
├── viz.py                  Rerun 点云、层与时间轴可视化
├── intrinsics.py           从预测 XYZ 恢复相机内参
├── checkpoint.py           模型配置、权重解析与加载
├── postproc.py             可选点云后处理
├── cli.py                  示例共用的命令行参数
├── paths.py                数据、输出及缓存路径约定
├── textured_mesh/          上游 WT → TRELLIS.2 桥接代码
│   ├── canon.py            相机坐标与 TRELLIS 标准坐标变换
│   ├── voxelise.py         点云扩展与体素化
│   └── pipeline.py         pipeline 加载、坐标注入与 GLB 导出
└── _core/                  内置 MoGe、Wan2.1 等骨干实现
examples/
├── infer_rgba.py            单图物体推理
├── infer_scene.py           单图场景推理
├── infer_video.py           动态片段推理
├── infer_textured_mesh.py   上游纹理网格入口
├── infer_batch.py           模型常驻、分阶段批量推理与断点续跑
├── prepare_gso_inventory.py GSO 原始 mesh 入库校验与固定划分
├── export_experiments.py    从实验 JSON 重建 Excel 记录
├── check_reproduction.py    DAVIS 动态结果复现检查
└── test_images/             随仓库提供的示例输入
scripts/                    环境安装、权重下载和独立验证工具
tests/                      路径行为测试
dependencies/               独立克隆的 TRELLIS.2 与原生扩展源码
evaluation/                 GSO 相机/纹理渲染、Sim(3)/深度指标与逐资产汇总
viewer.py                   网页查看入口：通用交互、按需加载、进度与网格布局
viewer_utils/               查看器文件格式与数据布局适配
├── glb.py / mesh.py         GLB、mesh 材质/贴图读取与显示准备
├── experiments.py          标准实验与 ablation 索引分发
├── ablation.py             WT 消融输出目录与配置记录适配
└── gso.py                  GSO 带纹理 GT 来源及坐标变换
```

## 环境与安装

当前服务器使用项目内独立环境 `.venv`（Python 3.11、PyTorch 2.6.0 / CUDA 12.4），GPU 为 A100 80GB（SM80）。安装与执行入口见 RUNBOOK，当前状态见 PROGRESS。旧服务器及恢复过程记录在 [项目历史](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/archived/20261105_recovery-results.md)。

2026-11-07 已完成 621 项实验恢复及工作簿发布，包括 P0、R1、R2 和既有两组对照。新旧数值差异、质量失败、单卡执行策略和验收限制均有记录。[恢复结果报告](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/archived/20261105_recovery-results.md)

通过 `ssh ali-dsw` 登录后，在项目目录启动专用 tmux 会话：

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
/etc/dsw/runtime/tmux/bin/tmux -L wt-recovery new-session -s wt-run
source scripts/env.sh
```

`env.sh` 将项目 `.venv/bin` 与 CUDA 12.4 加入当前进程 PATH，不修改全局环境。新建环境使用 Python 3.11；安装步骤为 `bash scripts/setup_all.sh`。当前默认 `TORCH_CUDA_ARCH_LIST=8.0`、`MAX_JOBS=4`，更换 GPU 时须重新编译原生扩展。

[environment.yml](environment.yml) 声明基础环境，[requirements.recovery.txt](requirements.recovery.txt) 固定迁移前可移植包版本，[constraints.txt](constraints.txt) 引用这些约束，[dependencies.lock](dependencies.lock) 锁定外部源码。[requirements.lock.txt](requirements.lock.txt) 已在新环境验收后重新导出，记录本机实际版本和安装来源；跨机器重建使用安装脚本和固定来源清单，不能直接照搬其中的本机路径。

Viser 固定为 1.1.1，并通过 `scripts/setup_viser_client.py` 安装快速切换配置的前端修复。`setup_all.sh` 会自动调用该步骤，首次构建需要 Node.js ≥24 和 npm，已验证的构建可直接复用。自定义工具位置使用 `WT_NODE_BINARY` 与 `WT_NPM_CLI`，重建与验收说明见 [查看器前端修复](/mnt/cpfs1/shuqiliu/code/world_tracing/RUNBOOK.md#viser-前端修复与重建)。

Pixal3D 使用同级源码 `../Pixal3D` 和独立环境 `.venv-pixal3d`。详见 [对比方法接入](compare_methods/README.md)。

## 存储路径

| 用途 | 当前路径 |
| --- | --- |
| 代码与环境 | `/mnt/cpfs1/shuqiliu/code/world_tracing` |
| 原始数据，只读 | `/mnt/oss1/lemonade_factory/SYNC/shuqiliu/data/raw` |
| 处理数据 | `/mnt/oss1/lemonade_factory/SYNC/shuqiliu/data/processed/world_tracing` |
| 结果、权重、归档日志 | `/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing` |
| 执行缓存、构建、临时文件 | 项目 `.runtime/cache/`、`.runtime/tmp/` |
| 运行中的日志 | 项目 `.runtime/logs/`；任务结束后复制到输出 `logs/` |

OSS 挂载不支持符号链接，动态模块、CUDA/Triton 构建缓存和活动日志使用 CPFS。权重保存在输出 `weights/`。完整性核验通过的原始数据不得修改；裁剪、兼容副本、划分和渲染写入处理数据目录。

GSO 原始资产位于数据根目录 `raw/gso/`；`archives/` 保存 ZIP，`objects/` 保存未修改的解压内容，`integrity/` 保存校验记录。全部 1030 个资产通过 SHA-256、ZIP CRC 与必要文件检查后才生成 `COMPLETE.json`。冻结的原始 ID、来源与历史 P0/R2 样本审计见 `configs/gso_recovery.json`、`configs/historical_gso_samples.json`。

[wt/paths.py](wt/paths.py) 与 [scripts/env.sh](scripts/env.sh) 统一默认值，支持 `WT_DATA_ROOT`、`WT_PROCESSED_ROOT`、`WT_OUTPUT_ROOT`、`WT_WEIGHTS_ROOT`、`WT_CACHE_ROOT` 和 `WT_TRELLIS2_ROOT`。显式 HF/Torch 缓存变量优先。数据、权重、环境、日志及构建产物不纳入 Git。

## 模型与快速使用

| 配置 | 任务 | 输入尺寸 | 参数量 | Hugging Face 权重 |
| --- | --- | --- | --- | --- |
| `r75b` | 物体 | 504 × 504 | 1.7B | [object-model-6layer](https://huggingface.co/haoz19/object-model-6layer) |
| `r69l` | 场景 | 840 × 840 | 1.5B | [scene-model-6layer-840](https://huggingface.co/haoz19/scene-model-6layer-840) |
| `r76` | 动态 | 16 帧，336 × 336 | 2.1B | [dynamic-model-16frame](https://huggingface.co/haoz19/dynamic-model-16frame) |

在上述环境中运行；需要授权的权重通过进程环境 `HF_TOKEN` 提供凭据。物体下载工具固定权重版本并返回本地路径；已缓存时可设置 `HF_HUB_OFFLINE=1` 离线使用。

```bash
# 物体：使用仓库自带 RGBA 图像
object_ckpt="$(python scripts/download_object.py)"
CUDA_VISIBLE_DEVICES=0 python examples/infer_rgba.py \
  --image examples/test_images/object/obj014_leather_briefcase.png \
  --ckpt "$object_ckpt" --config r75b --seed 42 \
  --out "$WT_OUTPUT_ROOT/object_seed42.rrd"

# 场景：需要对应权重
CUDA_VISIBLE_DEVICES=0 python examples/infer_scene.py \
  --image examples/test_images/scene/scene_outdoor_14_brooklyn_apartment__seed61.png \
  --ckpt r69l --config r69l --seed 42

# 动态：需要对应权重，输入为 16 帧 RGBA
CUDA_VISIBLE_DEVICES=0 python examples/infer_video.py \
  --image_dir examples/test_images/dynamic/davis__camel \
  --ckpt r76 --config r76 --seed 42
```

用 `rerun <结果文件.rrd>` 查看点云。示例默认运行 4 个种子；`--seed 42` 选择单次推理。单图可加 `--layer-timeline` 按层查看；视频可用 `--frame_indices` 从较长序列选取 16 帧。更多参数见各入口的 `--help`，示例来源见 [test_images/README.md](examples/test_images/README.md)。

`--ckpt` 支持配置名（如 `r75b`）、`hf://仓库名/文件名` 和本地 `.pt` 路径；HF 简写省略文件名时使用 `model.pt`。加载器支持原始 `state_dict` 或包含 `model_state_dict` / `ema_state_dict` 的字典，优先使用 EMA。

## 网页查看

批量推理在同一进程中先加载一次 WT 处理全部图像，再加载一次 TRELLIS.2 处理原生与 hybrid 结果。激活上述环境后，在专用 tmux 中运行：

```bash
object_ckpt="$(python scripts/download_object.py)"
python examples/infer_batch.py \
  --input-dir examples/test_images/object --ckpt "$object_ckpt" \
  --out "$WT_OUTPUT_ROOT/experiments/20261013-R1-object-qual-v1" --seeds 42

python viewer.py --experiment "$WT_OUTPUT_ROOT/experiments/20261013-R1-object-qual-v1"
```

每个结果存为 `samples/<sample_id>/<method>/<config_id>/seed-0042/`，用 `run.json` 标记完成或失败；WT 原始点图为 `prediction.npz`，mesh 为 `mesh.glb`，导出前后坐标说明存于 `mesh.json`。重复执行同一命令会跳过已完成结果；参数、输入或源码变更使用新配置/实验 ID。`--methods wt trellis2 wt_trellis2` 可选方法，`--configs` 接收 JSON 配置列表，`--inputs` 接收带 `sample_id/image` 的 JSONL 清单。批处理是模型复用的单图队列，显存 batch=1；TRELLIS 的 low-VRAM 模式仍可在 CPU/GPU 间移动已加载权重。

根目录 `experiments.xlsx` 为 v0.5 空白记录表，沿用实验总览、P0/R2 逐样本三张表及原样式，按输出阶段、统计口径和 seed 记录完整几何、输入可见几何与渲染结果。初版完整工作簿存于 [docs/archived/20261110_experiment_baseline_protocol_v0.xlsx](docs/archived/20261110_experiment_baseline_protocol_v0.xlsx)。历史协议中的工作簿路径对应此存档。旧版导出入口 `python examples/export_experiments.py --experiments "$WT_OUTPUT_ROOT/experiments"` 默认写入项目 `.runtime/experiments-protocolv0-regenerated.xlsx`。v0.5 自动填表待后续接入，逐视角图与完整统计通过结果来源列引用。

批量查看器启动时只读取 JSON 索引；在 `Sample` 选择样本后，才加载该样本的图像、全部匹配结果和 GT（默认开启）。切换样本清除旧显示，过期加载在可中断阶段退出；不会预加载其他样本，也不限制比较结果数量。展开 `Method / Config / Seed` 可勾选多个选项，各组提供“全选／清空”；Method、Config 默认全选，Seed 默认选中第一个种子。组内匹配任一选项，组间同时满足；任一组清空则不加载方法结果，GT 仍由独立开关控制。刷新保留有效选择，全选时包含新增选项。支持前一张/后一张、刷新结果；当前样本最多同时准备两份结果，已准备结果使用最多 256 MiB 的内存缓存，源文件变更后重新加载。

WT ablation 输出也使用 `--experiment`，自动识别 `<样本>/<配置>/prediction.npz` 布局，无须生成 `experiment.json`：

```bash
python viewer.py --experiment "$WT_OUTPUT_ROOT/validation/z-root-cause-20261020/inference"
```

每个配置目录可附 `input.png` 和 `metrics.json`；后者提供 seed、裁剪比例、背景色等参数，未记录的 seed 显示为 `unknown`。选择 `Sample` 后，`Config` 多选控制并排比较；`Input / configuration` 切换对应输入图与参数，不重新加载几何。默认 full / 表面颜色，坐标按 WT camera RDF 解释，保留原尺度。不同配置使用各自 NPZ 中的 RGB，仅给 layer-0 着色。可选的 `<样本>/input.json` 沿用标准实验的 `ground_truth`、`dataset`、`evaluation_dir` 字段，相对路径以该文件目录为基准；未声明完整 GT 时页面提示缺失，不把 NPZ 的单视图 `gt_depth` 当成完整 GT。其他模型或目录布局需单独适配，不套用 WT 坐标约定。

进度条显示服务器准备百分比、当前阶段和耗时（按文件任务及读取/解析/打包阶段计算），100% 表示场景已准备并提交发送，浏览器传输与渲染可能仍在继续。`View` 只控制已加载结果的显示；`Sample / Method / Config / Seed` 决定读取哪些文件。`Mesh representation` 默认 Exported GLB（纹理导出结果）；Decoded mesh 是解码器原始几何，往往更大。默认按元数据将 hybrid 恢复到它自己的 WT 预测尺度，TRELLIS 保持原生尺度；居中后按网格展示，不做 GT 配准。画布标签分行显示，完整坐标与来源说明保留在 View 选项中；Reset view 按当前窗口宽高比和视场角容纳几何及标签。选择状态在已连接浏览器间共享。输出契约见本地实验方案 `docs/20261013_hybrid-baseline.md`。

在已激活环境的专用 tmux 中运行，无需 GPU。网页使用 Viser（包含在 `viz` 依赖中），Rerun 仅用于读取已有 `.rrd`：

```bash
python viewer.py \
  --image examples/test_images/object/obj014_leather_briefcase.png \
  --points "$WT_OUTPUT_ROOT/validation/object_seed42.rrd" \
  --mesh "$WT_OUTPUT_ROOT/validation/hybrid-cascade/briefcase.glb"
```

打开终端打印的网址，默认 `http://127.0.0.1:8080`。HTTP 和 WebSocket 共用一个端口；仅监听 `127.0.0.1`，远程访问使用 `ssh -L 8080:127.0.0.1:8080 ali-dsw`。`--port` 指定端口，`--port 0` 自动选择空闲端口；指定端口被占用时会尝试后续端口，以终端打印值为准，相应调整 SSH 转发。`Ctrl-C` 停止服务，无后台子进程或临时录制文件。

页面分为左侧三维画布与右侧控制栏，控制栏默认宽 420 px，可拖动分隔线调整；画布不延伸到控制栏下方。侧栏显示输入图像。`--mesh`、`--gt`、`--trellis` 可省略；后两者接受点云或 mesh，例如 `--trellis /路径/trellis_output.glb`。3D 结果按接近方形的网格排列：4 项为 2×2，6 项为 2 行×3 列，9 项为 3×3；不足一行时居中，按最大几何尺寸统一留出间距。`View` 可切换单项并自动调整视角，支持旋转、缩放、点大小调整和视角重置。各结果仅为展示而居中、平移，保留原尺度，不作配准；源文件保持不变。

画布左上角提供视角按钮：缩放 `− / ＋`、平移 `← → ↑ ↓`、旋转 `← → ↑ ↓`。缩放每次约 20%，平移沿当前屏幕方向移动视点，旋转以当前观察中心为轴每次 15°。按钮仅改变当前浏览器的相机，切换样本后仍保留；鼠标操作与右侧 Reset view 可继续使用。

命令行有两种互斥模式，`python viewer.py --help` 按以下用途分组：

| 参数 | 用途 |
| --- | --- |
| `--experiment DIR` | 自动识别标准实验清单或 WT ablation 目录，按样本/配置浏览；不再传单文件参数 |
| `--image FILE --points FILE` | 单样本模式的必选图像和 WT 点云 |
| `--mesh / --gt / --trellis FILE` | 单样本模式的主 mesh（例如 hybrid）、真值、独立 TRELLIS 对照结果；只读取文件，不运行模型 |
| `--entity / --gt-entity / --trellis-entity` | 对应 RRD 文件内部的点云实体路径，通常省略；不是文件路径 |
| `--quality fast / balanced / full` | 两种模式通用的显示预算，默认 full；实验模式也可在网页切换 |
| `--color-mode gray / surface / depth` | 默认 surface（表面颜色），两种模式均可通过网页 Color mode 切换 |
| `--max-points N` | 覆盖每份点云上限，0 表示全部点；不限制完整 mesh 面数 |
| `--port N` | 网页与 WebSocket 共用端口，默认 8080，0 自动选择 |

质量档位：默认 `full` 保留全部有效点、完整 mesh 和原始纹理。`balanced` 使用最多 5 万点、完整 mesh 拓扑、最长边 1024 px 纹理；GLB 沿用原顶点、面索引和法线，不把大 mesh 转成点云。`fast` 使用最多 2 万点、512 px 纹理，超过 5 万面的 mesh 使用明确标注的**顶点预览**。预算按每个结果计算，不减少比较数量，所有处理仅在内存中进行。默认 Exported GLB 以快速加载为目标；Decoded mesh、full、大量比较项或较慢的远程网络仍可能需要更久。

`Color mode` 的三种显示方式：

| 模式 | WT 点云 | Mesh / GT / TRELLIS |
| --- | --- | --- |
| 灰色（gray） | 全部灰色，WT 不预测纹理 | 保留已有纹理或顶点颜色，无颜色处填灰 |
| 表面颜色（surface，默认） | 仅 layer-0 使用与点图像素对齐的输入 RGB，隐藏层灰色 | 保留已有表面颜色，无颜色处填灰 |
| 深度（depth） | 按深度着色 | 覆盖原纹理，采用相同的近蓝、远红色表 |

表面颜色优先使用 WT `prediction.npz` 中预处理后的 `rgb`；这是输入图像在 layer-0 的像素对应，不是模型预测的纹理。没有层/像素对应关系的扁平 RRD/PLY 点云保持灰色并标注原因；不会将输入 RGB 复制到隐藏层。深度使用坐标恢复后、布局平移前的显示坐标 `−Z`，按每个结果的有效深度范围独立归一化，旋转视角不改变颜色，因此不同结果的同色不代表相同度量距离。

点云支持 `.rrd/.npy/.npz/.ply`；NumPy 坐标为 `[N,3]`、`[H,W,3]` 或 `[L,H,W,3]`，NPZ 使用 `xyz` / `xyz_pred` / `points`，可附 `mask` / `mask_pred` 和 `colors` / `rgb`。RRD 显示最后一个快照，默认选择唯一的 `pointcloud/all`，多种子文件可用实体参数指定。

Mesh 支持 GLB、GLTF、OBJ、PLY，以及只含几何的 STL/OFF。OBJ 需保留 MTL 和贴图目录，支持多个材质库、材质分组和相对路径；GLTF 可引用外部 BIN/图片或内嵌资源。PLY 有面时按 mesh 显示，可读取顶点颜色或 `TextureFile` + UV；无面时按点云显示。`--points` 始终按 WT 点云处理。贴图在内存中嵌入 GLB 后发送到网页，修改外部材质/贴图后刷新会重新加载；缺失资源在状态栏提示。普通 `map_Kd` 贴图路径受支持，带额外 MTL 贴图选项的写法会提示不支持。单文件模式的点云假定相机 RDF、mesh 假定 Y-up；实验模式按清单中的 kind/frame 读取。其他坐标约定须先转换。

GSO 实验的 GT 优先通过 `evaluation_dir` 下的 `camera.json` 和数据集 `inventory.jsonl` 定位原始带纹理模型，并应用已保存的资产归一化和相机变换。原始模型或坐标信息不可用时，提示原因并回退到清单中的评测几何；评测 PLY、冻结清单和原始数据均不改写。其他数据集直接显示 `ground_truth` 指定的文件。

## 输入与输出约定

物体与动态输入优先使用带准确 alpha 的 RGBA。单图在缩放前按软 alpha 与背景色合成，mask 使用 `alpha > 127`；视频在缩放和 mask 腐蚀后填充无效区域。`--bg-color none` 保留原 RGB。RGB 物体输入可能触发 `ZhengPeng7/BiRefNet_HR` 自动抠图并下载额外权重，它与 TRELLIS.2 的 RMBG-2.0 是不同模型。

WT 预测几何：单图 `xyz_pred` 为 `[B, L, H, W, 3]`，视频为 `[B, T, L, H, W, 3]`，坐标位于相机空间；`r75b` / `r76` 使用度量尺度，`r69l` 使用相对尺度。有效掩码来自输入 alpha，可视化使用输入 RGB 或深度灰度，模型不预测颜色或可见性。[wt.solve_intrinsics_from_xyz](wt/intrinsics.py) 可从第 0 层几何拟合相机内参。

## TRELLIS hybrid 与验证工具

[论文 §5.3](https://arxiv.org/html/2606.13652v1#S5.SS3) 的 hybrid 方案将 WT 点图转为体素坐标，替换 TRELLIS 的 Stage 1 sparse structure，再使用形状、纹理 SLat 与 mesh decoder。[TRELLIS.2](https://github.com/microsoft/TRELLIS.2) 和所需扩展放在 `dependencies/`；衔接入口为 `examples/infer_textured_mesh.py`，只加载所选模式需要的形状、纹理模型，默认优先使用本地权重配置。

```bash
object_ckpt="$(python scripts/download_object.py)"
CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python examples/infer_textured_mesh.py \
  --image examples/test_images/object/obj014_leather_briefcase.png \
  --ckpt "$object_ckpt" --seed 42 --pipeline-type 512 \
  --texture-size 512 --out "$WT_OUTPUT_ROOT/briefcase.glb"
```

`--pipeline-type` 默认 `1024_cascade`；`512` 和两个 cascade 模式自动使用 32³ 输入体素网格，直接 `1024` 使用 64³。`--shape-steps` / `--tex-steps` 可缩短调试采样；`--max-num-tokens` 控制上游 cascade 分辨率回退，不能保证 1024 模式的显存上限。输出 GLB 为 glTF Y-up，同名 JSON 保存坐标变换、种子和采样参数；恢复相机坐标时，先用 `glb_to_canonical` 矩阵转回 TRELLIS Z-up，再调用 `canon_inverse`。

权重工具：[fetch_weights.py](scripts/fetch_weights.py) 下载 TRELLIS 权重；[fetch_modelscope_aux.py](scripts/fetch_modelscope_aux.py) 从 ModelScope 获取 DINOv3、RMBG-2.0；[prepare_trellis2_local.py](scripts/prepare_trellis2_local.py) 生成全部指向本地权重的配置，存入 `$WT_WEIGHTS_ROOT/local-pipelines/TRELLIS.2/`。移动权重目录后需重新生成配置。下载、镜像及离线加载命令见 [RUNBOOK](RUNBOOK.md#权重下载与离线使用)。

| 验证入口 | 范围 |
| --- | --- |
| `scripts/smoke_wt.py`、`scripts/smoke_trellis2.py` | 无权重的随机张量、独立模型和 CUDA 算子检查 |
| `scripts/smoke_hybrid.py` | 随机多层点图经体素化、坐标注入及真实 shape/texture flow；不执行 mesh decoder |
| `scripts/run_object_validation.sh` | WT 预训练物体推理 |
| `scripts/validate_pretrained_stage2.py` | TRELLIS.2 真实 flow 权重与随机条件采样 |
| `scripts/validate_aux_models.py` | DINOv3、RMBG-2.0 独立图像推理 |
| `scripts/verify_weights.py` | 本地权重完整性检查 |

在专用 tmux 中执行。随机张量检查用于验证代码与数值逻辑，不代表生成质量。实验命令与结果保存在 [RUNBOOK](RUNBOOK.md)，当前完成情况、缺失数据与后续事项见 [PROGRESS](PROGRESS.md)。

## 引用与许可

```bibtex
@inproceedings{zhang2026worldtracinggenerativepixelaligned,
  title = {World Tracing: Generative Pixel-Aligned Geometry Beyond the Visible},
  author = {Hao Zhang and Mohamed El Banani and Jen-Hao Cheng and Paul Zhang and Yi Hua and Ben Mildenhall and Christoph Lassner and Narendra Ahuja and Gengshan Yang},
  booktitle = {Advances in Neural Information Processing Systems (NeurIPS)},
  year = {2026},
  eprint = {2606.13652},
  url = {https://arxiv.org/abs/2606.13652}
}
```

项目许可见 [LICENSE](LICENSE)（CC BY-NC-ND 4.0），外部依赖遵循各自许可证。模型实现使用了 [MoGe](https://huggingface.co/microsoft/moge-2-vitl) 与 [Wan 2.1](https://github.com/Wan-Video/Wan2.1) 的骨干组件。
