# Hybrid 体素化消融方案

2026-11-18；状态：已确认 20 资产预实验口径；仅更新方案与预算，未选定具体样本、未实现对照、未启动实验。核对基于远程工作区（HEAD `908457206d908c9d6ab52ff3f10e3ce1b1d89d4b`，含已有未提交改动）。

## 目的与固定条件

先进行 20 资产预实验，交叉比较体素化、WT parent 预处理与输入相机，再依据结果决定正式 100 资产配置。体素化包括“官方填充 / 原始表面量化 / 局部窄带”；不增加几何优化或训练。预处理和相机固定后，两个新体素化对照仅改变传入 TRELLIS.2 的支撑坐标。

固定 seed 42、每次单资产、`1024_cascade`、初始 `ss_res=32`（不是 64）、shape/texture 各 12 steps、纹理 4096、GLB 简化目标 1,000,000 面。沿用对应官方 Hybrid 的 checkpoint、精度和内存修复策略。同一资产 × 预处理 × 相机下，三种体素化共用确切 WT parent、`rgba.png` 和 canonical transform；不根据体素化结果重新拟合归一化。不同预处理/相机使用各自对应的 parent 与 transform，不混用。

## 20 资产预实验（用户已确认）

### 样本与组合

GSO、OOD 分别从当前 camera_ablation 的固定 50 资产清单中选 20 个；候选池以 `configs/camera_ablation_modelwise50_v2.json` 和 `.runtime/logs/camera-ablation-20261112/modelwise50-v2/` 的冻结名单为准。所有组合共用同一批 20 个资产，不按组重新抽样。

按资产类别及几何多样性选样，覆盖紧凑/细长/扁薄形状、细杆薄片、孔洞凹腔、分离部件与遮挡复杂度等；不按 WT/Hybrid 的误差或退化幅度挑样本。选样依据来自源几何与输入，优先使用已有描述统计/预览；名单冻结时记录资产 ID、来源 50 清单摘要、几何特征及入选理由。本次仅确认选样规则，尚未生成具体名单。

| 因素 | 条件与定义 |
| --- | --- |
| 体素化 | H-fill 官方填充、H-surface 原始表面量化、H-band 局部窄带。 |
| WT parent 预处理 | default：现有 `defaults-v1`，黑背景、alpha_erode=2；WT 原始：现有 `shared-wt-v1`，灰背景 [128,128,128]、alpha_erode=0，复用独立 WT 的确切预测。 |
| 相机 | A0（B0 引用同一输出）、A1、B1；遵循现有 camera_ablation 定义。A1 联合改变内参与构图；B1 固定外参与 B0/A0 确定的裁剪，改变内参。 |

预处理对照仅采用已有 default/shared-WT 的区别，TRELLIS 图像条件继续使用对应相机条件的现有处理；不额外同步改变 TRELLIS 的背景/腐蚀规则。B1 保留既有冻结裁剪逻辑。B0 是 A0 别名，不新增推理、不重复计入样本量。

### 配置选择与正式集

三种体素化均覆盖 2 种预处理 × 3 种相机，先报告各数据集、各组合的结果与交互表现。正式阶段采用统一预处理/相机，还是各体素化组分别选取配置，**待预实验结果后与用户确定**；本次不预设胜出配置或自动选优规则。若最终比较各组不同配置，解释为整体方案性能，不能将全部差异归因于体素化。

每数据集正式 100 资产仍采用原冻结 eval100，包含预实验的 20 个。配置冻结后，分别报告这 20 个配置选择样本、其余 80 个未参与本轮选配的样本和全部 100 个；不把含选配样本的全量汇总称为完全独立验证。当前 camera_ablation 范围保持 50，不因本方案扩大或重排其队列。

## 两个对照的代码逻辑（仅设计）

共同入口保持 `wt/batch.py::generate_mesh` 的数据读取与后续采样/导出流程，仅替换 `v4_ray_fill` 生成 coords 的部分：

| 组别 | 坐标生成逻辑 |
| --- | --- |
| H-fill：官方，复用 | 相邻层每对插 4 个点 → 固定 canonical transform → 32³ 量化 → 1 次 binary closing → binary_fill_holes。 |
| H-surface：原始表面量化 | 取六层 mask 有效且 XYZ 有限的原始表面点；应用同一 transform；沿用官方边界筛选 `abs(p) <= 0.5-1e-6`；按 `floor((p+0.5)*32)` 量化并去重。无跨层插值、闭运算或内部填充。 |
| H-band：局部窄带 | 从 H-surface 的网格出发，对每个活跃 cell 加入自身和 ±x/±y/±z 六个轴向邻居，即一次 6 邻域膨胀、网格半径 1；丢弃越界坐标、去重。无跨层插值、闭运算或内部填充。 |

两组均按 `argwhere` 的字典序输出唯一 int32 coords，保持批次索引 0；空集记失败，不悄悄退回官方方案。不增加随机采样或 voxel/token 截断。半径 1 在 canonical 坐标中对应一个 1/32 网格步长；不按资产调参。局部膨胀仍可能连接相隔很近的表面，需作为限制报告。

注意：只设置 `ray_steps=0, close_iters=0` 仍会执行现有函数末尾的 `binary_fill_holes`，不能实现 H-surface。新逻辑将来须显式绕过该步骤。

H-fill 对 H-surface 检验整个填充组合，不能单独归因于 ray interpolation；H-band 对 H-surface 检验局部加厚的作用。支撑数量变化会改变随机张量形状，同 seed 不意味着逐 voxel 噪声一一相同。

## 复用范围、预算与评测

输出根目录记为 `O=/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing`。

H-fill 复用 `O/experiments/20261112-camera-v1-{GSO,OOD}-{A0,A1,B1}` 中 `wt_trellis2/{defaults-v1,shared-wt-v1}/seed-0042` 的对应产物与兼容指标；GSO A0 default 也可追溯至已完成的 `20261013-R2-gso-quant-v1`。原 OOD `20261112-OOD-omni-v2-eval100` 只有 WT 与 TRELLIS.2，不能作为 Hybrid 结果。运行前核对输入、parent SHA-256、transform、配置、模型/源码差异、评测 revision，建立逐项复用表；缺失项等待当前相机队列完成，不在本轮另跑官方组或 WT。

| 预实验预算（两数据集合计） | 数量 |
| --- | ---: |
| 唯一资产 | 2 × 20 = 40 |
| 全部 mesh 输出 | 40 × 3 体素化 × 2 预处理 × 3 相机 = 720 |
| H-fill 对应输出，优先复用 | 40 × 1 × 2 × 3 = 240 |
| 两个新体素化方案的 mesh 推理 | 40 × 2 × 2 × 3 = 480 |
| 全部 decoded/GLB 评价阶段 | 720 × 2 = 1,440；其中新体素化 960、官方 480 |
| 对应 WT parent 条目 | 40 × 2 × 3 = 240；引用相机实验缓存，不为每种体素化重算 |

以上是逻辑预算，已有指标通过兼容性核验后复用，实际新增评测量待名单及复用盘点后冻结；当前不执行。预实验不新增 WT/官方组推理的前提是所选 50 范围内的相机队列产物齐备。

正式 100 阶段预算待选配决定。若每个新体素化组在每数据集最终保留一个预处理/相机组合，预实验中对应 20 个可复用，剩余 80 个共需 2 数据集 × 80 × 2 体素化 = 320 次新增 mesh 推理，连同预实验为 800 次；官方组、输入与 WT parent 在原 50 以外的缺口另行盘点，不默认已有 100 个完整缓存。

主指标为 decoded 的完整/可见 CD-L1，辅以 Precision/Recall/F-score、输入 Silhouette IoU 和额外前景比例；GLB 单列以区分导出影响。沿用 v0.5 配准、采样、相机与有效性口径；不混合不同 revision 的图像指标。固定相机/预处理比较体素化；相机之间的可见几何沿用现有相机消融的共同可见区域配对定义，避免将可见范围变化误认为形状改善。

按数据集报告逐资产配对差值、胜负数、失败数及 95% bootstrap 区间；20 样本是有意覆盖几何差异的配置探索集，区间不代表对完整数据分布的无偏估计。记录注入 voxel 数、cascade 后 token 数、解码面数、耗时与峰值显存；小 voxel 数不作为几何更优的证据。

## 显存预算与 camera_ablation 隔离

以下为 2026-11-18 10:52 北京时间的历史资源快照，保留作预算依据，并非当前队列状态。单卡 NVIDIA A100-SXM4-80GB，nvidia-smi 总量 81,920 MiB；Ubuntu 22.04、Python 3.11.11、PyTorch 2.6.0+cu124。当时 camera_ablation 为 `running / OOD / B0 / batch03 / evaluate`，主 pipeline PID 3544884，显存约 1,927 MiB。该瞬时低占用不代表后续推理有空余预算。

| 证据 | 数值与含义 |
| --- | --- |
| 历史单进程 mesh 小试（4 个方法输出） | 整卡采样峰值 23,482 MiB = 22.93 GiB；不能外推为所有样本上限。 |
| camera 正式队列 31 份 baseline 资源日志 | 除已知 OOM 批次外，日志最大采样值 42,686 MiB = 41.69 GiB；属于混合方法批次，非两个新对照的实测。 |
| 已知 OOM 批次 | 最大采样值 78,196 MiB = 76.36 GiB；默认/shared-WT 失败时进程占用分别 71.26/76.37 GiB，且包含大量 reserved-but-unallocated 内存。 |
| OOM 点的活跃张量预算 | 默认：45.24 + 待分配 10.48 = 55.72 GiB；shared-WT：46.97 + 9.94 = 56.91 GiB。再加假设 1 GiB 非 PyTorch 开销、8 GiB 余量，为 64.72/65.91 GiB。仅作该失败位置的规划参照，非完整流程或新对照的峰值上界。 |

两个对照的体素化均在 CPU 完成，额外 GPU 预算为 0；32³ bool 网格仅 32 KiB，最大 batch+XYZ int32 坐标上传为 32³×4×4 bytes = 0.5 MiB。真正显存由模型、cascade 激活、解码及导出决定。H-band 初始点数满足 N_band <= min(7 N_surface, 32³)，但不能据此线性估算解码峰值，也不能保证其少于官方填充。

已有 GSO 官方注入数为 291–9,236，中位数 2,973；仅 2,979 个注入 voxel 的 3M 样本却解码出约 1.90 亿面。当时 OOD 的 31 个官方结果中，gloves_015 用 3,376 个注入 voxel 解码出约 1.38 亿面。因此不以“表面点更少”承诺低显存。现有 `max_num_tokens=49152` 在 1024 cascade 终点并非硬上限。

**调度预算：H-surface 与 H-band 各按独占一张 80GB 卡、单进程/单资产估算，两组串行共用同一张卡；尚无新对照峰值实测，不承诺 80GB 可覆盖所有资产。** 沿用已有分块/缓存释放策略与 `expandable_segments:True`，但不修改正在运行的 camera 进程或环境。

并发余量按历史峰值计算：80 − 76.36 = 3.64 GiB；再预留 8 GiB 安全余量后为 −4.36 GiB，无法给新 Hybrid 提供可靠预算。即使某时段显存够用，同卡计算、CPU 和存储竞争仍可能拖慢 camera。故本轮只读日志与编写文档；GPU 小试及全量运行均等 camera 队列终态且进程退出后再安排，若必须重叠则需独立资源。

后续实现后的显存小试优先从冻结的 20 资产中覆盖普通与复杂几何样本，分别记录 PyTorch allocated/reserved 和整卡峰值，再确定实际运行上限；如需额外资源压力样本，单列且不加入选配指标。超预算不临时降分辨率、减步数或改 seed，以免改变消融定义。

## 核对来源

- 代码：`wt/textured_mesh/voxelise.py`、`wt/textured_mesh/pipeline.py`、`wt/batch.py`；级联行为见 `dependencies/TRELLIS.2/trellis2/pipelines/trellis2_image_to_3d.py`。
- 50 资产候选池与相机别名：`configs/camera_ablation_modelwise50_v2.json`、`.runtime/logs/camera-ablation-20261112/modelwise50-v2/`。
- 基线与口径：[GSO](20261110_hybrid-baseline_gso-quant_eval-v0.5.md)、[OOD](20261111_ood-evaluation.md)、[相机消融](20261112_hybrid-baseline_camera-ablation.md)、[v0.5](evaluation_protocol_v0.5.md)。
- 小试资源：`O/validation/single-gpu-batch-20261105/20261105T164410Z/report.json`。
- camera 资源：`.runtime/logs/camera-ablation-20261112/formal-v2/*/*/*/baseline/resources.jsonl`；最大值来自 `GSO/A1/batch02`。日志可能包含重试，统计采用全部记录，未只读最新 exit.json。
- OOM 证据：`.runtime/logs/camera-ablation-20261112/recovery-20261116/original-failures/{defaults-v1,shared-wt-v1}/run.json`；重试成功记录见同 recovery 目录下 `retry-{0,1}.status.json`。
