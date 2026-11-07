# TRELLIS.2 hybrid 基线实验

日期：2026-10-13。目的：比较 **WT、TRELLIS.2、WT + TRELLIS.2 hybrid** 的默认输出，再用单因素实验检查各方法的参数影响。模型推理采用固定 seed 的单次结果；不是论文 best-of-8 数值复现。

## 1. 实验内容

| 实验 | 数据与规模 | 比较内容 |
| --- | --- | --- |
| R1 定性 | `examples/test_images/object` 全部 30 张图 | 三方法默认配置；渲染图 + `viewer.py`（Viser）并排查看 |
| P0 协议调试 | GSO 独立 10 个物体，每物体 1 张固定视图 | 核验渲染/评价协议，并进行参数扫描；不纳入正式均值 |
| R2 定量 | GSO 独立 100 个物体，每物体 1 张固定视图 | 只运行三方法默认基线，沿用 Table 1 指标类别 |

GSO 原始数据固定存于 `/home/LiuShuqi/Workspace/data/world_tracing/raw/gso/`，**全部 1030 个资产下载、解压和校验完成后才推进 GSO 实验**。按有效 asset ID 排序，用 `PCG64(20261013)` 打乱一次，前 10 个为 P0、接着 100 个为 R2，其余保留；若均有效，即 10/100/920。清单在模型推理前冻结，三方法共享输入与视图；失败样本不替换，正式集不参与调参。

## 2. 对比方法与配置

| 关键配置 | WT | TRELLIS.2 | WT + TRELLIS.2 hybrid |
| --- | --- | --- | --- |
| 模型 | r75b，6 层，输入 504² | TRELLIS.2-4B | r75b + TRELLIS.2-4B |
| WT 步数 / 背景 / **mask 腐蚀** | 20 / 灰 128 / 0 px | — | 20 / 黑 0 / **2 px** |
| WT crop | 前景占画布 2/3 | — | 前景占画布 2/3 |
| TRELLIS 流程 | — | Stage 1 → shape → texture | WT 体素替代 Stage 1 → shape → texture |
| 模式 / steps | — | 1024_cascade；Stage 1、低/高 shape、texture 各 12 | 1024_cascade；低/高 shape、texture 各 12 |
| 体素化 | — | 原生 Stage 1 | R=32，ray_steps=4，closing=1，填洞，目标半宽 0.45，不截断 |
| GLB 导出 | — | 4096² 纹理、100 万面目标 | 同左 |
| 原生输出 | XYZ + mask 点图 | PBR mesh | PBR mesh + 上游 WT 引用 |

这是**各入口默认流程比较**：WT 与 hybrid 的预处理不同，不能单独归因于 Stage 2。另做 `shared-wt-v1` 受控对照：hybrid 复用 WT 默认输出的同一份 XYZ/mask，记录其文件哈希；仅用于 R1 和 P0。

纵向比较仅在固定 6 张 R1 图像和 10 个 P0 物体上进行，每次改变一项：

| 方法 | 扫描项（含默认） |
| --- | --- |
| WT | 步数 10 / **20** / 40 |
| TRELLIS.2、hybrid | 512 / **1024_cascade** |
| hybrid | ray_steps 0 / **4** / 8 |

默认 420 个结果、shared-WT 40 个、扫描额外 96 个，共 **556 个逻辑结果**；缓存复用不改变比较样本数。正式 GSO 100 物体本轮不扩展参数扫描。

## 3. 评价协议

论文未公开完整协议，本项目在 GSO 上固定自己的协议，不把结果直接等同于 Table 1。**形状与相机框架表现分表**：

| 表 / 协议 | 适用方法 | 核心约定与指标 |
| --- | --- | --- |
| 完整形状 `gso-shape-sim3-v1` | 三方法 | 同一 GT 辅助 Sim(3) 配准，允许正尺度/旋转/平移，禁止镜像；报告对称 CD-L1、CD-L2、F@0.01、F@0.05 |
| 相机框架 `gso-camera-native-v1` | WT、hybrid | 不做 GT 配准；hybrid 先恢复自己的 WT 框架。TRELLIS 无输入相机姿态，记 N/A |
| 可见深度 `gso-depth-ssi-v1` | WT、hybrid | WT 第 0 层 / hybrid z-buffer；同一 K 和裁剪、正尺度 scale–shift 对齐；MAE、RMSE、AbsRel、δ<1.25、δ<1.25²，另报覆盖率与轮廓 IoU |

完整形状使用**导出前 decoder mesh / WT 全层有效点**与完整 GT mesh；不使用 hybrid 填充内部点。评测最多 10 万点，mesh 按面积采样；GT 配准另用独立 1 万点。距离以同一 GT 资产归一化前的 AABB 对角线为基准，F 阈值为其 1%/5%；L1 指欧氏距离均值，L2 指平方距离均值，双向取平均。公式和配准细节见附录。

GSO 输入按固定相机渲染：1024²、FoV 40°、俯仰 20°、逐资产固定方位角、透明背景，保存线性相机 Z 深度、K 和外参。评测 GT 和 WT 裁剪/像素中心严格一致。渲染资产统一等比归一为对角线 1 的实验单位，不宣称真实米制精度。具体轴/材质设置经 P0 检验后写入渲染清单并冻结。

按资产统计均值、成功数/总数与失败率，同时报告三方法共同有效集合的均值；失败不记为零误差，也不换样本。深度覆盖低于 95% 或正尺度拟合失败记不可比，报告覆盖率及失败率。GT 配准结果不用于宣称姿态准确。R1 无 GT，几何指标为 N/A；纹理观感与几何质量分开查看。

## 4. 随机性、复现与产物

- **推理 seed=42，batch=1**；每样本的 WT 入口及 TRELLIS 整条 pipeline 入口重置 Python、NumPy、Torch/CUDA RNG；TRELLIS 内部各阶段顺序使用该随机流，不在每个 sampler 之间重置。数据划分 seed=20261013，与推理 seed 独立。
- 视图、GT 配准采样、GT 评测采样、预测采样、bootstrap 各用 `SHA256("20261013|用途|asset_id")` 前 8 个十六进制位派生独立 seed；保存实际 seed、视图和点样本，任务顺序不改变结果。首轮不选择最佳 seed。
- 冻结输入/split 哈希、代码快照、依赖提交与环境、权重来源/校验、实际模型/预处理/sampler/渲染/配准参数、GPU与精度设置。固定种子不等于承诺不同 CUDA/硬件位级一致；不确定性限制随配置记录。
- 模型常驻分阶段批处理：一次加载 WT 完成点图缓存，再一次加载 TRELLIS 生成原生与 hybrid；不逐图重新加载。成功标记、输入和配置哈希用于断点续跑。
- 输出：`/data1/LiuShuqi/output/world_tracing/experiments/<实验>/samples/<样本>/<方法>/<配置>/seed-0042/`；Viser 使用 `--experiment` 按样本/方法/配置/seed 比较。
- 汇总：仓库根目录 `experiments.xlsx`，记录两轮实验名称、参数、逐样本指标、汇总与失败原因；JSON/CSV 为可重建的数据源。方案仅保留设计，执行进度/日志记入 RUNBOOK、PROGRESS。

---

## 附录 A：依据、数据与采样细节

- [WT 论文 Table 1](https://arxiv.org/html/2606.13652v1#S4) 包括可见深度 MAE、RMSE、AbsRel、δ<1.25、δ<1.25²，以及完整几何 L1、L2、F@0.01、F@0.05。可见深度使用逐样本 scale–shift 对齐；生成式方法报告 best-of-8。本文复用指标类别，不复制论文结果作为本实验结果。
- [Issue #2](https://github.com/haoz19/world-tracing/issues/2) 在本次读取时未见作者答复。完整几何配准、距离定义、采样、阈值单位、选 seed 规则和原始评测清单仍不能据此确定。**GSO 是本项目另建的评测协议，不能称为 Table 1 数值复现，也不能保证与训练集无重叠。**
- `examples/test_images/object` 当前有 30 张 PNG；含多物体布局、透明物体和风格化内容，全部保留并打标签，不事后排除难例。没有配套 GT mesh，几何真值指标记 N/A。
- 资产全集以用户提供的 [GSO ZIP](https://www.paris.inria.fr/archive_ylabbeprojectsdata/megapose/tars/google_scanned_objects.zip) 内 valid/invalid 两份原始清单的并集（944+86=1030）为准。原站无法稳定续传时，可使用 [Google 原始资产镜像](https://huggingface.co/datasets/suvadityamuk/google-scanned-objects-raw/tree/6139aa33f6163a9f1c7352dd386760f40691ce0d)，固定 revision、逐 ZIP SHA-256，并排除镜像中不属于原全集的 16 个条目；与可完整读取的原 ZIP 网格/纹理比对。原始 ZIP 解压内容不修改，不将预渲染图镜像替代完整 GT。
- [MegaPose GSO loader](https://raw.githubusercontent.com/megapose6d/megapose6d/master/src/megapose/datasets/gso_dataset.py) 区分 `models_orig` 与 normalized/pointcloud，并使用不同缩放因子；还读取 `invalid_meshes.json`。实施时优先核验 orig 资产，不混用不同版本，不将顶点单位直接猜成米。
- 外部源码固定于 [dependencies.lock](../dependencies.lock)，TRELLIS.2 为 `75fbf0183001ed9876c8dbb35de6b68552ee08bd`；运行同时保存本地代码快照、权重 descriptor 与依赖版本。完整原生 TRELLIS Stage 1→2→GLB 必须独立预检，hybrid 成功不能替代此项。
- 网页入口为 [viewer.py](../viewer.py)，已使用 Viser，支持单样本及 `--experiment` 批量选择器；没有自动指标评测或 GT 配准功能。

代码调用和坐标细节见 [代码结构解析](20261013_CODE-STRUCTURE.md)。批量入口和文件契约见附录 D；执行状态见 RUNBOOK、PROGRESS。

用户给出的全集规模为 1,030 个资产，下载后核对实际清单。抽样单位是 **asset ID**，不是渲染视图，也不是 orig/normalized 等同一资产的不同文件版本。采用固定种子的简单随机无放回划分，具体如下：

1. 入库时保存 ZIP 的 SHA-256、完整资产 ID、mesh/纹理哈希及可读取性。先完成输入完整性检查，再抽样；缺少必需文件、mesh 为空或非有限等问题逐项记录。透明、细结构、多部件或模型生成困难不构成排除理由；不自动沿用用途不明的上游 invalid 列表。
2. 对有效且唯一的 asset ID 按字符串升序排序。固定 `numpy.random.Generator(numpy.random.PCG64(20261013))`，只生成一次全部 ID 的随机排列；记录 NumPy 版本和最终清单，不依赖未来重新生成随机数恢复划分。
3. 排列前 10 个作为 `pilot`；接着 100 个作为 `eval100`；其余作为 `reserve`。三组互斥。若 1,030 个均有效，对应 **10 / 100 / 920**。模型推理 seed=42 与这里的数据划分 seed 是两个独立参数。
4. 模型运行前冻结 `inventory.jsonl`、`split.json` 及其哈希。三种方法共用同一份 eval100 和同一输入视图；视图种子按 asset ID 单独固定，不因换模型或任务顺序而变化。
5. 仅 pilot 用于修复实现、确定渲染/配准参数和做纵向扫描。eval100 不参与调参；运行失败按失败计数，不从 reserve 补一个容易物体。若冻结后发现原始资产损坏，保留审计记录并统一修订协议/清单版本，禁止只对某方法换样本。有效资产不足 110 个时先报告并调整规模，不有放回补足。

此方案不是按类别均分；目前尚未核验统一可靠的类别标签。若标签可用，记录三组的类别、尺度/长宽比、面数等分布用于检查，但不因初次结果不理想而反复换 seed。100 个随机资产用于首轮探索性评测，不能保证涵盖所有长尾类型，也不等于论文的 held-out split。后续可对 reserve 扩展评测，仍保留 pilot 独立及 eval100 原始成绩；训练集是否包含这些资产目前未知。

后续增加视图须以资产为统计单位，先汇总每资产再做全局平均；同一资产的任何视图都保持原来的 split。

## 附录 B：模型、渲染及扫描细节

TRELLIS 的 sampler 参数来自本地 `weights/local-pipelines/TRELLIS.2/pipeline.json`，每次运行保存解析后的完整值：

| sampler | guidance_strength | guidance_rescale | guidance_interval | rescale_t |
| --- | --- | --- | --- | --- |
| sparse structure | 7.5 | 0.7 | [0.6, 1.0] | 5.0 |
| shape | 7.5 | 0.5 | [0.6, 1.0] | 3.0 |
| texture | 1.0 | 0.0 | [0.6, 0.9] | 3.0 |

两种 mesh 导出都固定 `remesh=True, remesh_band=1, remesh_project=0`，调用同一个导出函数，避免导出差异混入方法差异。主几何指标使用导出前 decoder mesh；另存导出后 mesh 指标作诊断，防止重网格化/简化改变结论。若选择只评最终 GLB，应切换协议 ID，不能混报。

固定扫描图像：`obj014_leather_briefcase`、`obj015_wooden_train`、`obj062_bengal_tiger`、`obj141_brass_telescope_orrery`、`obj147_crystal_palace_glass`、`multi001_chess_set_marble`（均为 `.png`）。分别覆盖普通物体、组合结构、动物、细结构、透明/反光、多物体，不按生成结果选择。

本节是本项目设计，不是作者提供的协议。优先用已有 nvdiffrast 做固定纹理/深度/alpha 渲染；预检 OBJ/MTL 纹理兼容性，若改用 Blender 必须记录版本和新的渲染配置。

- 保存原始单位、顶点和轴约定。派生副本以完整 GT mesh 的资产空间 AABB 中心居中、对角线等比归一为 1 个实验单位；记录 `T_asset_to_eval`，不把归一单位称为米。缺少源资产坐标/单位资料时保留 unknown，检查后才冻结转换。
- 源资产按预检确认的 Z-up 保留竖直轴；输入相机为 RDF，显式保存 `K`、`T_world_to_camera`、近远裁面。纹理网格双面渲染，禁止负行列式缩放静默镜像。
- 建议输入 1024²、水平 FoV=40°、俯仰=20°；每资产方位角由数据 seed 决定并写入清单。相机距离从包围球与 FoV 确定，保证整物体入框并留约 20% 边界；记录最终距离，不依据预测结果调整。
- 固定单位环境光，原纹理 sRGB 数值直接输出，无色调映射；透明背景，像素中心单次采样、不做抗锯齿。depth 为线性相机 Z 而非沿射线距离或硬件 NDC depth。深度和 mask 禁止跨背景做普通双线性插值；GT 的 504² 深度按裁剪后的 K 直接重新光栅化。
- 每样本保存原始 RGBA、depth、mask、相机 JSON、完整 GT mesh 引用及其哈希；另生成与 WT 504² 裁剪严格对应的 GT 深度/alpha/K。裁剪偏移和像素中心 `+0.5` 必须进入 K 变换。
- 定性对比保存输入方向和 8 个环绕方向（45° 步长）的固定视图，另存 depth/normal/中性几何图。不同方法必须共用同一组评测相机和灯光；可附各方法自动居中展示，但注明 display-only。

GT 表面优先使用完整 mesh，不将仅相机可见面或前六次深度剥离当成 full geometry。六层 GT 如后续用于诊断，应建立另一组指标列，不能替代全物体主表。

## 附录 C：指标公式与统计

### C.1 完整几何

主协议暂命名 `gso-shape-sim3-v1`：使用 GT 辅助 Sim(3) 对齐比较形状，**不衡量输入姿态恢复能力**。统一允许正尺度、平移、det=+1 旋转，禁止反射。建议使用固定 24 个右手立方体旋转初始化、质心/尺度初始化与最近邻迭代 Sim(3) 优化；迭代上限 100，收敛阈值 1e-6（GT 对角线单位），按对称平方距离选最优。该配准方案仍需在 pilot 验证局部最优/对称物体问题后冻结；不得逐方法人工旋转或改参数。

为减小配准点对最终分数的过拟合，GT 配准用独立 10,000 个面积均匀采样点；最终 GT 使用另一固定 seed 的 100,000 个点。mesh 预测同样面积均匀采样 100,000 点。WT 使用全部层有效且有限 XYZ，移除完全重复坐标后，超过 100,000 点则固定 RNG 无放回采样，不足则全部使用；不重建 Poisson mesh，不使用 ray-fill 的内部填充点，不按误差清除离群点。保留点数/重复率，承认 WT 像素采样和 mesh 面积采样的分布差异。

设对齐后的预测点集 P、GT 点集 Q；两者使用同一 GT 资产空间 AABB 对角线 D 对应的单位（归一后 D=1），不按旋转后的包围盒重新缩放。`d(p,Q)=min_q ||p-q||₂`，则项目定义为：

```text
CD-L1 = 0.5 * (mean_p d(p,Q) + mean_q d(q,P))
CD-L2 = 0.5 * (mean_p d(p,Q)^2 + mean_q d(q,P)^2)
precision(t) = mean_p [d(p,Q) < t]
recall(t)    = mean_q [d(q,P) < t]
F(t)        = 2 * precision * recall / (precision + recall)
```

分母为 0 时 F=0。阈值 t=0.01/0.05 表示 GT 对角线的 1%/5%；L1 在此是欧氏距离均值，不是逐坐标曼哈顿距离，L2 是平方距离。输出列写明 `cd_euclidean_mean`、`cd_squared_mean`，展示时再映射 Table 1 的 L1/L2 名称。全部报告双向均值，不暗乘 100/1000。

另设 `gso-camera-native-v1`：WT 直接使用相机 XYZ；hybrid 的 decoder mesh 直接用 `canon_inverse` 恢复其 WT 预测框架，只有读取 GLB 时才先撤销 GLB 轴旋转，避免对 decoder mesh 重复旋转；两者与已知 GT 相机点比较，不做 GT 配准，仅用 GT D 统一指标单位。TRELLIS 原生没有这项相机变换，记 N/A。禁止把 hybrid 的 `canonical_transform` 套到原生 TRELLIS。

保存每次配准矩阵及损失；`shape-sim3` 和 `camera-native` 使用不同表行/协议 ID，不能混成一个排名。若后续增加图像姿态估计作为 TRELLIS 后处理，单独命名方法并计算其成本。

### C.2 可见深度

采用 `gso-depth-ssi-v1`：WT 使用第 0 层 Z；hybrid 在恢复后的相机框架中渲染 z-buffer；TRELLIS 无相机姿态时为 N/A，GT 配准后的深度只能列为 `oracle-pose` 辅助结果。

在一致的 504² 裁剪和 K 下，前景有效交集上最小二乘拟合 `z_aligned=a*z_pred+b`，约束 a>0；记录 a/b 及原始深度结果，不能把该一维深度对齐直接用于三维全形状指标。报告：

评价 K 从 GSO 渲染 K 按同一裁剪变换获得；不能将 WT 默认的假定内参（NPZ 的 `intrinsics`）当成 GSO 相机标定，也不能改用从预测拟合的 K 规避相机误差。默认推理保留入口的内参行为，GT 标定仅供评价；若另做已知 K 条件输入须单列配置。预测深度常量导致拟合秩不足、拟合 a≤0，均记失败，不用极小正数掩盖失败。

```text
MAE    = mean |z_aligned - z_gt|
RMSE   = sqrt(mean (z_aligned - z_gt)^2)
AbsRel = mean |z_aligned - z_gt| / z_gt
delta_k = mean [max(z_aligned/z_gt, z_gt/z_aligned) < 1.25^k], k=1,2
```

GT 正深度、mask、有限性规则固定；交集外不能静默消失，另外报告 `depth_coverage` 与 silhouette IoU。拟合失败、有效深度不足或出现非正对齐深度时标记该深度评测失败并记录比例，不只保留“容易像素”。本轮不把孔洞插值补全设为默认。建议有效覆盖低于 95% 时标记不可比，不进入成功样本深度均值，并同时报告总失败率及共同有效样本均值。

### C.3 聚合、随机性与其他记录

- 首批以固定 seed=42 报告，不能标 best-of-8；后续 42–49 扩展时保存所有结果和 mean/std。若报 best-of-8，建议每个样本按 `shape-sim3 CD-L1` 选唯一 seed，其他几何列使用该 seed，不逐指标挑不同结果。深度选 seed 如另用 AbsRel，必须另列 selection rule。
- hybrid 记录 `wt_seed` 与 `trellis_seed`；首轮按相同值配对，不做 8×8。相同整数 seed 在不同流程中不代表相同 latent 噪声，不能据此声称配对噪声消融。
- 每方法报告成功数/总数、失败原因、成功样本均值与三方法共同成功样本均值；空输出不能得 F=1，失败不能写成 0 距离。统计置信区间时按资产 bootstrap，不按点或同物体多视图当独立样本。
- 记录推理/后处理/导出耗时、冷启动加载耗时、峰值显存、有效点/体素/顶点/面数、文件大小。hybrid 总时间包含 WT，即使受控实验复用了缓存，也同时报告完整推理成本与本次实际增量成本。
- 不将 WT 输入 RGB 着色与生成 PBR 纹理视为同一种预测能力；跨三方法主评测是几何。PSNR/SSIM/LPIPS 如后续需要，须另定材质、灯光、配准及无纹理 WT 的适用范围，不塞入本轮 Table 1 指标。

## 附录 D：批量文件契约与命令

代码存于仓库，方案遵循 `docs/AGENTS.md` 仅在本地保留；数据、权重、实验日志和产物都在 `/data1` 的项目目录。用户已明确授权将 GSO 下载解压至 `data/world_tracing/raw/gso/`；完整校验后原始内容只读，派生副本另存。

```text
/data1/LiuShuqi/data/world_tracing/raw/gso/  # ~/Workspace/data/world_tracing/raw/gso/
├── archives/                             # 1030 个固定版本原始 ZIP、SHA-256 清单
├── objects/<asset_id>/                   # 原样解压的网格、材质、纹理、元数据、缩略图
├── integrity/                            # 逐资产及逐文件校验
└── COMPLETE.json                         # 全部验证成功后才生成；实验启动前必须检查
/data1/LiuShuqi/output/world_tracing/
├── datasets/gso/source/                   # 原站未完整 ZIP、清单与镜像比对证据
├── datasets/gso/assets/                   # 兼容材质路径的派生副本，不修改 raw 内容
└── experiments/
    ├── datasets/gso-v1/                   # 派生渲染、GT、相机和 split manifest
    ├── 20261013-R1-object-qual-v1/
    │   ├── experiment.json               # schema_version=1、实验 ID
    │   ├── .writer.lock                  # 单 writer 文件锁
    │   ├── last_batch.json               # 最近一次调用的完成/失败计数
    │   ├── _cache/wt/<cache_key>/         # 跨样本/配置复用，哈希包含输入、WT 参数、seed 和来源
    │   │   ├── prediction.npz            # 不含展示平移的原始 XYZ/mask/RGB/K
    │   │   ├── rgba.png                  # WT 实际读入/抠图后的 RGBA，供 hybrid 条件使用
    │   │   ├── complete.json             # 完成标记、产物哈希和 WT 推理时长
    │   │   └── run.log
    │   ├── samples/<sample_id>/
    │   │   ├── input.json                # 原图/预处理/GT 引用和坐标信息
    │   │   └── <method>/<config_id>/seed-0042/
    │   │       ├── run.json              # 唯一状态：planned/running/complete/failed；产物清单
    │   │       ├── config.json           # 解析后的实际参数，不能只保存 CLI
    │   │       ├── prediction.npz        # WT: xyz[L,H,W,3], mask[L,H,W], rgb[H,W,3]
    │   │       ├── wt_parent.json        # hybrid 上游 WT 文件引用与哈希
    │   │       ├── decoded_mesh.ply      # TRELLIS/hybrid 导出前 mesh，明确 frame
    │   │       ├── mesh.glb              # 最终 PBR；WT 为 N/A
    │   │       ├── mesh.json             # 轴、尺度、变换、实际分辨率等
    │   │       ├── metrics.json          # protocol、数值、单位、N/A 原因
    │   │       ├── runtime.json          # 推理/mesh 总时长；细分计时与峰值字段按实际测量补充
    │   │       ├── renders/              # 固定相机渲染与独立 display-only 预览
    │   │       └── run.log
    │   └── summary/                      # 后续评测阶段：对比图、CSV、聚合 JSON
    └── 20261013-R2-gso-quant-v1/          # 同构目录
/data1/LiuShuqi/code/world_tracing/experiments.xlsx  # 跨两轮汇总，不存原始张量
```

不要求每方法生成所有文件。当前入口生成 input/config/run、WT NPZ、mesh/decoded mesh、mesh 元数据、runtime 和日志；`metrics.json`、renders、summary 由后续评测生成，缺失不伪造为空成绩。所有 hybrid 通过 `wt_parent.json` 引用 `_cache/wt` 内的实际 NPZ 与哈希；shared-WT 通过相同背景/腐蚀/步数/seed 命中原生 WT 的同一缓存，不复制上游大张量。不同内容输入、不同预处理不能复用，字节完全相同的输入可跨 sample ID 复用。

`config.json` 保存解析后的参数和来源指纹（WT 模型定义、Python 源码摘要、依赖锁、TRELLIS descriptor、WT checkpoint 路径/大小/mtime）；checkpoint 内容校验仍依据已有权重下载清单，运行时不反复计算大权重哈希。`run.json` 使用原子替换；同路径参数/来源变化直接报错，不覆盖旧实验。已 complete 且产物存在的任务跳过；失败/缺失产物重跑。WT 缓存另外核对 NPZ/RGBA 内容哈希。关闭进程留下的 planned/running 任务下次可恢复；源码改动需新实验/配置 ID。

输入清单为 JSONL，每行至少包含 `sample_id` 和 `image`；CLI 解析路径相对于清单文件。可加 `ground_truth={"path":"gt.glb","kind":"mesh","frame":"gltf_yup"}`，GT 已存在时供 viewer 并排查看；实际推理输入和 GT 均只读。自动扫描图片目录只扫描一层，以文件 stem 为 sample ID，重名或非法 ID 直接报错。

每个 run 的产物使用统一描述，路径相对于 run 目录；例如：

```json
{
  "schema_version": 1,
  "status": "complete",
  "artifacts": {
    "mesh": {"path": "mesh.glb", "kind": "mesh", "frame": "gltf_yup", "metadata": "mesh.json"},
    "decoded_mesh": {"path": "decoded_mesh.ply", "kind": "mesh", "frame": "canonical_zup", "metadata": "mesh.json"}
  }
}
```

WT 的 key 为 `points`，kind=`points`、frame=`camera_rdf`、path=`prediction.npz`。支持的 frame 仅为 camera_rdf、canonical_zup、gltf_yup；未知坐标报错，不猜测。`mesh.json` 中 hybrid 必须保存 `canonical_transform`，才能恢复 WT 框架；原生 TRELLIS 永不套用该逆变换。

批量命令（专用 screen，激活 Conda 并 `source scripts/env.sh` 后）：

```bash
object_ckpt="$(python scripts/download_object.py)"
python examples/infer_batch.py --input-dir examples/test_images/object \
  --ckpt "$object_ckpt" --seeds 42 \
  --out "$WT_OUTPUT_ROOT/experiments/20261013-R1-object-qual-v1"
python viewer.py --experiment "$WT_OUTPUT_ROOT/experiments/20261013-R1-object-qual-v1"
```

默认包含三方法 defaults-v1。`--methods wt` 可只跑 WT；`--configs /path/configs.json` 用 JSON 列表覆盖方法与配置，例如以下三个任务共享一次 WT 模型加载，最后一个也复用原生 WT 的点图缓存：

```json
[
  {"method":"wt","config_id":"defaults-v1"},
  {"method":"wt","config_id":"steps10","wt_steps":10},
  {"method":"wt_trellis2","config_id":"shared-wt-v1","bg_color":[128,128,128],"alpha_erode":0}
]
```

其他可覆盖项为 `pipeline_type/ray_steps/shape_steps/tex_steps/max_num_tokens/texture_size/decimation_target`。所有配置在加载模型前校验。扫描时使用固定 6 张图/10 个 pilot 的 JSONL 配合 `--inputs`，不能直接将扫描配置应用于正式 100 个 GSO。

当前 viewer 使用 `--experiment` 扫描小型 JSON 索引，只按需加载选中的几何，不将全部输出放入内存。支持 Sample、Method、Config、Seed，前后样本、Refresh results、GT 开关、GLB/decoder mesh 切换；Method=All 用于横向比较，单方法+Config=All 用于纵向比较，最多显示 12 个匹配 run，超出时提示缩小筛选。多浏览器共享选择状态。尚未完成、失败或损坏的结果显示状态，不保留上一样本场景冒充当前输出。

Restore WT frame 默认开启，依据 hybrid 自己的元数据恢复尺度与相机坐标；所有展示转换为 Y-up，面板仍分别居中并排，不是坐标配准。WT 默认与 hybrid 默认上游不同，不将它们当成同一预测；TRELLIS 保持原生姿态和尺度并标注。关闭恢复开关可看 hybrid 归一化产物。源文件不改写。

GSO 的 GT-aligned 预览留待评测器产出配准矩阵后接入，当前 viewer 不自动计算 GT 配准。单样本旧 CLI 仍按 RDF 解释 `--points`、Y-up 解释 mesh；批量模式严格按 artifact frame 转换，避免重复旋转。`.rrd` 仅为可选展示，不能作为指标输入，因为可能已有抽样/多 seed 平移。

## 附录 E：工作簿字段

工作簿路径为 `/data1/LiuShuqi/code/world_tracing/experiments.xlsx`；已加入当前仓库 `.gitignore`。随执行进度更新，尚未完成的指标保留空值并写明原因。

| Sheet | 内容与粒度 |
| --- | --- |
| `Experiments` | 每轮一行：ID、名称、状态、计划/实际日期、数据协议、目的、输出根目录 |
| `Configs` | 每配置一行：方法、父配置、变化项、全部关键参数、config_hash、源码/权重版本 |
| `Samples` | 每输入一行：资产/视图 ID、split、输入/GT/相机哈希、类别、排除原因 |
| `Runs` | 每次推理一行：run_id、方法/配置/输入/seed、状态、资源、产物超链接 |
| `Metrics` | 长表：run_id、protocol_id、metric、value、unit、status、N/A 原因 |
| `Summary` | 轮次×方法×配置×协议×seed 聚合规则；均值、方差、有效数/总数、失败率 |
| `MetricSummary` | 实际逐资产指标均值/std、成功/失败/待处理/N/A 数、默认基线共同成功集合均值；不存在的值留空 |
| `Protocol` | 公式、采样、对齐、单位、seed 选择、来源与实现核验状态 |

`run_id` 唯一，参数变更生成新 config_hash；真实缺失用空值和原因列，不用 0 或字符串混入数值列。时间注明 Asia/Shanghai；表头冻结、筛选、合理列宽和数字格式，失败/未完成状态有明确标识。汇总由 JSON/CSV 重建，Excel 是分析入口，不是唯一真值；不得手工修改均值后丢失逐样本依据。更新时保留既有工作表/实验记录，并以临时文件完成后原子替换，避免半写入。
