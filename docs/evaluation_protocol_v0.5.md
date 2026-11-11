# 评测协议 v0.5

2026-11-11 整理。实现配置为 `gso-baseline-v2`。配准列对应当前已完成的 v0.5 评测。

GSO v1 使用 R2 固定 100 个资产、输入图、GT 和相机，P0 10 个资产用于校准。协议候选预算为 seed 42–49，当前 R2 已完成 seed 42，八 seed 队列暂停。固定 checkpoint、预处理、推理与导出参数，WT tensor batch=1。Seed 42 复用既有输出，技术性重试沿用原 seed。

| 方法 | 配置 | 评测对象 |
| --- | --- | --- |
| WT | defaults-v1 | 六层有效点云 points |
| TRELLIS.2 | defaults-v1 | decoded mesh、exported GLB |
| Hybrid | defaults-v1 | decoded mesh、exported GLB，另保存实际 WT parent |
| Pixal3D | resolution1024-v1 | decoded mesh、exported GLB |

GLB 应用场景变换并恢复方法坐标。GT 按原资产 AABB 对角线归一化为 D=1。

## 1. Geometry（whole & visible）

| 评测对象 | 当前配准与区域定义 | 结果字段 |
| --- | --- | --- |
| Whole geometry | 每个方法阶段独立进行完整形状正 Sim(3) ICP，拟合 s、R、t | `shape`、`registration` |
| Input-visible geometry | 复用完整形状变换，按固定输入相机的 GT 可见标签取区域，区域内重算双向距离 | `regions.visible` |

两类对象均计算下表全部指标。Mesh 按表面积采样，WT 汇集六层有限有效点并去除精确重复点。配准点和评价点分别使用独立用途 seed，数量上限为 10,000 和 100,000，点数不足时使用全部点并记录数量。ICP 在主轴坐标下使用 24 个右手旋转初始化，以双向最近邻平方距离选择解。

| 指标 | 定义与单位 | 方向 |
| --- | --- | --- |
| CD-L1 | 双向最近邻欧氏距离均值的平均，D | ↓ |
| CD-L2 | 双向最近邻平方距离均值的平均，D² | ↓ |
| Pred→GT、GT→Pred 距离均值 | 两个方向分别保存，D | ↓ |
| Precision@0.01、Precision@0.05 | 预测点到 GT 的距离严格小于 0.01D、0.05D 的比例 | ↑ |
| Recall@0.01、Recall@0.05 | GT 点到预测的距离严格小于上述阈值的比例 | ↑ |
| F@0.01、F@0.05 | 2PR/(P+R)，分母为零时取 0 | ↑ |
| 支持量与状态 | 预测/GT 点数、双向距离数组、区域标签、有效/空集/失败状态 | 记录 |

\[
CD_{Lk}=\tfrac12\left[\operatorname{mean}_{p\in P}d(p,G)^k+
\operatorname{mean}_{g\in G}d(g,P)^k\right],\qquad k\in\{1,2\}.
\]

GT 可见性使用输入裁剪相机的首交点，容差为 1e-4D。后端为 Trimesh 双精度求交与 rtree==1.4.1，批量 256，近切线阈值 1e-12。射线端点校正到 GT 表面的位移上限为 1e-6D，位移逐点保存，完整几何使用冻结的 GT 评价点。

预测点按最近 GT 评价点继承标签。GT 区域非空而预测为空时 Recall/F-score=0，CD 与 Precision 标记无有效比较。GT 区域为空时标记 N/A。异常 GT 可见性使区域指标标记无效。Occluded 与 out-of-view 的同类指标见第 4 节。

## 2. Visible depth

| 评测对象 | 当前对齐流程 | 当前计算的深度指标 | 结果位置 |
| --- | --- | --- | --- |
| WT 原像素 L0 深度 | 读取对应像素的预测 Z，逐资产拟合 z′=az+b | SSI 后 MAE、RMSE、AbsRel、δ1、δ2，拟合前 MAE | 原输出 `depth_fit.json`；R2 `visible_depth_review.json` |
| 输入相机重渲染深度，全部方法阶段 | 完整形状 Sim(3) 后使用固定 GT 输入相机渲染 | MAE、RMSE | `comparisons.{surfel,native}.input.metrics` |
| 输入相机重渲染深度＋SSI，全部方法阶段 | 在上述深度图的固定像素交集上再拟合 z′=az+b | SSI 后 MAE、RMSE、AbsRel、δ1、δ2，拟合前 MAE | `comparisons.{surfel,native}.input_ssi` |

WT 使用 surfel，mesh 同时计算 surfel 与原生三角面表示。深度采用相机 Z。设有效交集上的评价深度为 d、GT 为 g，e=|d−g|，q=max(d/g,g/d)。

| 指标 | 定义与单位 | 方向 |
| --- | --- | --- |
| MAE | mean(e)，D | ↓ |
| RMSE | sqrt(mean(e²))，D | ↓ |
| AbsRel | mean(e/g) | ↓ |
| δ1、δ2 | q 严格小于 1.25、1.25² 的比例 | ↑ |
| SSI 拟合诊断 | a、b、拟合前 MAE、有效像素数、深度覆盖率、轮廓 IoU、状态与失败原因 | 记录 |

SSI 使用有效像素上的最小二乘拟合，要求至少 3 个有效像素、拟合满秩、a>0、对齐后深度为正、深度覆盖率至少 95%。重渲染的直接 MAE/RMSE 使用其有效交集。汇总分别记录各路径的有效资产数，配对比较使用共同有效资产。相同像素的控制比较另记录共同像素集合与覆盖率。

## 3. Input view & multi-view

| 评测对象 | 当前几何与相机 | 适用表示 |
| --- | --- | --- |
| Input view | 完整形状 Sim(3) 后的几何，固定 GT 裁剪相机，504×504 | 四方法共同 surfel；mesh 另算原生三角面 |
| Multi-view | 同一配准几何，30 个固定球面视角，512×512 | 同上 |

两类视角逐视角计算以下全部指标。输入视角的深度结果同时构成第 2 节的重渲染深度路径。

| 指标 | 定义与单位 | 方向 |
| --- | --- | --- |
| 深度 MAE、RMSE | 有效深度交集上的误差，D | ↓ |
| Silhouette IoU | 预测与 GT 前景交集/并集 | ↑ |
| 法线平均角误差 | 有效法线交集上的夹角均值，度 | ↓ |
| 法线 MSE | mean(((n_pred−n_gt)/2)²)，按有效像素与三通道平均 | ↓ |
| 法线 PSNR | −10 log10(max(MSE,1e-12))，dB | ↑ |
| 法线 LPIPS | AlexNet LPIPS v0.1，法线图使用中性背景整图 | ↓ |
| 深度覆盖率 | 有效深度交集像素数/GT 有效前景像素数 | ↑ |
| 法线覆盖率 | 有效深度交集且双方有有效法线的像素数/GT 有效前景像素数 | ↑ |
| 支持量与状态 | 预测/GT 前景像素数、深度交集数、法线交集数、预测有效法线像素数；各指标有效视角数、总视角数与状态 | 记录 |

输入相机沿用生成输入图的 GT 外参。裁剪左上角为 (x₀,y₀)、边长为 l，缩放到 504 后 s=504/l，焦距乘 s，主点变为 s(cx−x₀)、s(cy−y₀)。

30 个方向采用球面 Hammersley 采样，u=(i+0.5)/30、仰角 asin(2u−1)、输入方位加 360°×radical_inverse₂(i)，上下半球各 15 个方向，FoV 40°、距离约 1.754D。半步偏移用于避免极点退化。[参考渲染实现](https://github.com/microsoft/TRELLIS.2/blob/main/trellis2/utils/render_utils.py)

Mesh 面积采样 2,000,000 点，体素尺寸 0.002D、surfel 半径 0.003D、PCA 法线邻域半径 0.006D，邻域最多 32 点、至少 6 点，切向特征值比例阈值 0.01。法线转到相机坐标并朝向相机。完整参数见 [渲染配置](../configs/multiview_baseline_v2.json)。

## 4. 其他补充

### 4.1 几何、相机与外观诊断

| 评测对象 | 当前处理 | 全部计算指标或诊断量 |
| --- | --- | --- |
| Occluded、out-of-view 区域 | 复用完整形状 Sim(3) 和 GT 标签 | 第 1 节全部几何指标、点数与区域状态 |
| WT、Hybrid 原生相机坐标几何 | 转到各自约定的输入相机坐标 | CD-L1/L2、F@0.01/0.05 |
| WT 相机原点 scale-only 几何 | 用 L0 对应点拟合尺度，应用于完整点云 | CD-L1/L2、F@0.01/0.05 |
| WT L0 对应点 | GT 深度反投影得到对应 XYZ | 原生、scale-only、scale+translation 的 XYZ RMSE；两种拟合尺度、三维平移、对应像素数 |
| WT 相机内参 | GT K_crop、保存默认 K、从预测 XYZ 拟合 K | 三组 K、重投影误差均值与 P95 |
| Decoded→GLB 同变换对照 | 同 seed，GLB 使用 decoded 配准矩阵 | 完整及各区域的第 1 节全部几何指标；原生面积、配准后面积、面积/GT；保存两端数值及差值 |
| Decoded→GLB 阶段对照 | 同 seed，各阶段独立 Sim(3) | 两阶段共有数值指标的逐资产差值及汇总 |
| Hybrid 的实际 WT parent | 父点云独立完整形状 Sim(3) | 父点云完整几何的第 1 节全部指标，Hybrid−parent 的完整 CD-L1 差值 |
| Mesh 规模与面积 | decoded、GLB 各阶段 | 顶点数、面数、文件字节数、原生面积、Sim(3) 尺度、配准后面积、面积/GT |
| GLB 输入 RGB 外观 | 完整形状 Sim(3)，unlit base-color，中性灰背景 | RGB PSNR、RGB LPIPS |
| Surfel 转换 | 对配准后的预测点云和 GT 分别处理 | 输入/保留点数、有效法线点数与比例、邻域点数分位数 |
| 配准过程 | 主轴坐标下 24 个初始化 | 变换矩阵、尺度、对称平方损失、各初始化损失与迭代数、预测/GT 主轴特征值 |

原生面积采用方法原坐标单位²，配准后面积采用 D²。点云与 mesh 的采样权重、surfel 转换误差及 ICP 局部最优纳入结果解释。

### 4.2 可见性与 GT 校准

| 校准对象 | 全部计算指标或诊断量 |
| --- | --- |
| GT 可见标签 | visible/occluded/out-of-view 点数，异常/未命中/超出目标的射线数，离表面点数，表面校正位移最大值与 P95 |
| 容差敏感性 | 5e-5D、1e-4D、2e-4D 下的可见点数及相对默认值的标签变化数 |
| 最近 GT 标签继承 | 独立 GT 点的直接标签与继承标签不一致数量/比例、混淆矩阵、最近邻距离均值 |
| GT 区域自一致性 | 第 1 节对应区域的全部几何指标 |
| GT 裁剪相机与输入重渲染 | 裁剪内参矩阵误差、外参误差、mask 一致性、深度 MAE |
| GT surfel 与原生 mesh | 输入视角和 30 视角的第 3 节全部渲染指标，输入深度 SSI 的第 2 节指标 |

### 4.3 候选选择与统计汇总

每个资产、方法、输出阶段以完整几何 CD-L1 最小的 seed 为 best-of-8，平分取较小 seed，该组全部指标读取同一候选。Decoded 与 GLB 分组独立选择，WT 点云作为两组共同参照。另保存 decoded winner 对应的 GLB 结果。八个候选均达到终态后汇总 best-of-8，失败计入候选预算，全部失败的资产计入失败数。

| 汇总对象 | 统计量 |
| --- | --- |
| 固定 seed、best-of-8、八次有效候选均值 | 各指标有效资产数、资产均值、中位数、样本标准差、95% bootstrap 区间 |
| 八次候选的资产内变化 | 有效 seed 数、预期 seed 数、样本标准差 |
| 完成度与失败 | 预期/已评测/完成/失败/待完成候选数、失败率、全部失败资产数 |
| 方法或阶段配对 | 共同有效资产数、差值均值/中位数/标准差/95% 区间；方法配对另记录前者更低/更高的资产数 |
| Multi-view | 每资产先对 30 视角等权平均，再对资产等权；完整均值要求相应指标在全部视角有效 |

Bootstrap 按资产重抽样 5,000 次，统计 RNG seed 为 20261110。当前单 seed 报告使用本轮实际预算与有效数量。

### 4.4 产物与实现记录

默认保存 input-view 的 GT/预测深度、法线、mask、有效性、误差图和对照 PNG。`--save-multiview-renders` 可追加保存 30 个 multi-view 的 PNG。全部视角均保存指标与浮点 NPZ，GT 共享，同资产同视角固定色标。产物支持原子写入、摘要校验和从有效 NPZ 补建缺失 PNG。

保存相机、变换、采样 seed、输出阶段、文件摘要、源码/config revision。GT 标签缓存签名包含 mesh、评价点、相机、容差、后端与依赖版本。各项 `result.json` 保存完整字段，`summary_seed42.json` 保存当前单 seed 汇总，`render_index.md` 链接到产物清单。

P0 完成 10 资产、70/70 阶段及 47,430 张 PNG 校验，revision 为 `f99c2f63a273b21b0d2e`。R2 seed 42 完成 100 资产、700/700 阶段及 15,300 张 input-view PNG 校验，revision 为 `d99fa356cec4eb52fb27`。WT 原像素 L0 深度与同像素控制比较存于 `visible_depth_review.json`。
