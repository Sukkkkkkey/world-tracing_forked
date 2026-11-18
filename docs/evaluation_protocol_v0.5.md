# 评测协议 v0.5

2026-11-12 精简。实现配置为 `gso-baseline-v2`。**当前报告采用 R2 固定 100 个 GSO v1 资产、seed 42，已完成 700/700 方法阶段。** P0 的 10 个资产用于校准，seed 42–49 的八候选队列暂停。

## 评测范围

| 方法 | 配置 | 评测对象 |
| --- | --- | --- |
| WT | defaults-v1 | 六层有效点云 points |
| TRELLIS.2 | defaults-v1 | decoded mesh、exported GLB |
| Hybrid | defaults-v1 | decoded mesh、exported GLB，保存实际 WT parent |
| Pixal3D | resolution1024-v1 | decoded mesh、exported GLB |

固定资产、输入图、GT、相机、checkpoint、预处理、推理与导出参数。WT tensor batch=1。Seed 42 复用既有输出，技术性重试沿用原 seed。GLB 应用场景变换并恢复方法坐标，GT 按原资产 AABB 对角线归一化为 D=1。

**主评测中，各方法阶段独立做完整形状正 Sim(3) ICP，拟合 s、R、t。区域几何和渲染均复用该变换。** 四方法渲染比较共用 surfel，mesh 另报原生三角面结果。

## 1. Geometry（whole & visible）

主表的 whole 与 input-visible 几何均计算下表全部指标。Mesh 按面积采样，WT 汇集六层有限有效点并精确去重。配准/评价使用独立用途 seed，上限分别为 10,000/100,000 点，不足时使用全部点。ICP 采用主轴坐标下 24 个右手旋转初始化，以双向最近邻平方距离选择解。

| 指标 | 定义 |
| --- | --- |
| CD-L1 ↓、CD-L2 ↓ | 分别对两方向的最近邻欧氏距离（L1）或距离平方（L2）求均值，再取平均，单位 D、D² |
| Pred→GT、GT→Pred ↓ | 分别保存单向距离均值，单位 D |
| Precision、Recall ↑ | 阈值取 0.01D、0.05D，分别统计预测→GT、GT→预测距离严格小于阈值的比例 |
| F@0.01、F@0.05 ↑ | 2PR/(P+R)，分母为零时取 0 |

GT 可见标签由固定输入裁剪相机的首交点确定，容差 1e-4D。预测点继承最近 GT 评价点标签，**各区域内重新计算双向距离**。Occluded、out-of-view 使用同组指标。

GT 区域非空而预测为空时 Recall/F=0，CD/Precision 无有效比较。GT 区域为空记 N/A，可见性异常则区域指标无效。保存预测/GT 点数、双向距离数组、标签及有效/空集/失败状态。

## 2. Visible depth

| 角色 | 深度来源与对齐 |
| --- | --- |
| **四方法主评测** | Sim(3) 后在固定 GT 输入裁剪相机下重渲染 |
| WT 补充行 | 原像素 L0 Z，逐资产最小二乘拟合 z′=az+b（SSI），衡量相对深度结构 |

同表注明深度来源、对齐方式和有效资产数，四方法排序使用主评测各行。深度统一采用相机轴向 Z，主评测的预测/GT 重渲染共用 K、外参、分辨率和像素中心约定，同一像素比较同一射线的两个首交点深度。

令 M_pred、M_GT 为各自前景 mask 内有限正深度的像素集合，C_depth=M_pred∩M_GT。两类路径均在非空 C_depth 上计算下表五项指标。d 为主评测重渲染深度或 WT 的 SSI 后 L0 深度，g 为 GT 深度，e=abs(d−g)，q=max(d/g,g/d)。

| 指标 | 定义 |
| --- | --- |
| MAE ↓、RMSE ↓ | mean(e)、sqrt(mean(e²))，单位 D |
| AbsRel ↓ | mean(e/g) |
| δ1 ↑、δ2 ↑ | q 严格小于 1.25、1.25² 的比例 |

WT 补充读取 `prediction.npz` 的 `xyz[0, ..., 2]`、`mask[0]` 与 `gt_depth.npz` 的 `depth`、`mask`，匹配同一输入视角、裁剪/缩放像素网格及像素中心约定。SSI 逐资产最小化 Σ(az+b−g)²，在同一 C_depth 上拟合与评价，要求像素数≥3、[z,1] 秩为 2、a>0、对齐后深度全部为正、覆盖率≥95%。保存拟合前 MAE、a、b、轮廓 IoU、像素数、覆盖率、状态及失败原因。K 误差与 XYZ 一致性见三维及重投影诊断。

## 3. Input view & multi-view

Input view 使用固定 GT 裁剪相机、504×504。Multi-view 使用同一几何、30 个固定球面视角、512×512。物理深度沿用第 2 节定义，以下图像与覆盖指标分别报告输入视角和 30-view 结果。

| 指标 | 计算范围与定义 |
| --- | --- |
| Silhouette IoU ↑ | count(M_pred∩M_GT) / count(M_pred∪M_GT) |
| 深度图/法线图 RMSE ↓、PSNR ↑、LPIPS ↓ | 各自 mask 成图后的整幅 H×W×3 图像，包含背景 |
| 深度覆盖率 ↑ | count(C_depth) / count(M_GT) |
| 法线平均角误差 ↓ | 双方有效法线交集上的夹角均值，单位度 |
| 法线覆盖率 ↑ | 双方有效法线交集像素数 / count(M_GT) |
| GLB RGB PSNR ↑、LPIPS ↓ | 仅输入视角，unlit base-color 渲染与输入图比较，中性灰背景 |

有效法线集合为 N=M∩normal_valid。覆盖率使用重渲染 mask，WT L0＋SSI 补充另注明原像素来源及有效资产范围。

**图像编码与评分**

- 深度图共用同资产、同视角的 GT 范围。GT 有效深度极值为 z_min、z_max，令 p=max(0.1(z_max−z_min),0.01D)，范围为 [max(0,z_min−p),z_max+p]。线性映射并截断到 [0,1]，复制为三通道，记录范围、预测有效像素中的截断数量及其占预测有效像素数的比例。
- 法线图使用单位相机法线，I=(n+1)/2。深度图和法线图的无效位置均填 0.5。
- 从浮点 NPZ 数组计算整图 MSE=mean((I_pred−I_GT)²)，RMSE=sqrt(MSE)，PSNR=−10log10(max(MSE,1e-12))，峰值 1、单位 dB。LPIPS 使用 AlexNet v0.1，输入为 2I−1。[LPIPS 接口](https://github.com/richzhang/PerceptualSimilarity#python-code)

## 候选选择与汇总

**逐资产计算，再对有效资产等权平均。** Multi-view 先逐视角计算，再对每资产 30 视角等权平均，完整资产均值要求该指标全部视角有效。记录每项指标的有效/总资产与视角数、失败率、状态及预测/GT 前景、深度交集、法线有效/交集像素数。

| 汇总对象 | 规则 |
| --- | --- |
| 固定 seed、best-of-8、八次有效候选均值 | 有效资产数、均值、中位数、样本标准差、95% bootstrap 区间 |
| 资产内候选变化 | 有效/预期 seed 数、样本标准差 |
| 方法/阶段配对 | 共同有效资产数及差值均值、中位数、标准差、95% 区间，方法配对另报前者更低/更高数量 |
| 完成度 | 预期/已评测/完成/失败/待完成候选数、失败率、全部失败资产数 |

Bootstrap 按资产重抽样 5,000 次，RNG seed=20261110。当前单 seed 报告采用实际预算和有效数量。

每资产、方法、阶段以完整几何 CD-L1 最小者为 best-of-8，平分取较小 seed，组内全部指标读取同一候选。Decoded 与 GLB 独立选优，WT 为共同参照，另存 decoded winner 对应的 GLB。八候选全部达到终态后汇总 best-of-8，失败计入预算，全部失败的资产计入失败数。

## 复现与诊断

<details>
<summary>相机、可见性与 surfel 参数</summary>

- 输入相机沿用 GT 外参。裁剪左上角 (x₀,y₀)、边长 l，s=504/l，焦距乘 s，主点为 s(cx−x₀)、s(cy−y₀)。
- 30-view 采用球面 Hammersley，u=(i+0.5)/30，仰角 asin(2u−1)，方位为输入方位+360°×radical_inverse₂(i)。上下半球各 15 视角，FoV 40°、距离约 1.754D，半步偏移避免极点退化。[参考渲染](https://github.com/microsoft/TRELLIS.2/blob/main/trellis2/utils/render_utils.py)
- 可见性使用 Trimesh 双精度求交、rtree==1.4.1，批量 256、近切线阈值 1e-12。射线端点表面校正≤1e-6D，逐点保存位移，完整几何沿用冻结 GT 评价点。[实现](../evaluation/visibility.py)
- Mesh 按面积采样 2,000,000 点，体素 0.002D、surfel 半径 0.003D、PCA 邻域半径 0.006D，邻域 6–32 点，切向特征值比例阈值 0.01。法线转入相机坐标并朝向相机。[完整配置](../configs/multiview_baseline_v2.json)

</details>

<details>
<summary>当前采用的决策与校准项目</summary>

下表为当前评测保留的补充对照与校准。主指标按第 1–3 节报告，WT 原像素 L0＋SSI 按第 2 节作为补充行。

| 项目 | 保存内容 |
| --- | --- |
| WT/Hybrid 原生相机几何 | 转到各自约定的输入相机坐标，计算 CD-L1/L2、F@0.01/0.05。WT 另用 L0 对应点拟合相机原点 scale-only，应用于完整点云并计算同组指标 |
| WT L0 与内参 | GT 深度反投影对应 XYZ 的原生、scale-only、scale+translation RMSE，两种拟合尺度、三维平移、对应像素数。GT K_crop、默认 K、XYZ 拟合 K 及重投影均值/P95 |
| Decoded→GLB | 同 seed 下，GLB 复用 decoded 变换，保存两端完整/区域的全部几何指标、原生/配准后面积、面积/GT 及差值。另报各阶段独立 Sim(3) 后共有数值指标的逐资产差值与汇总 |
| Hybrid 实际 WT parent | 父点云独立 Sim(3) 的全部完整几何指标，Hybrid−parent 的完整 CD-L1 差值 |
| Mesh 规模与面积 | decoded/GLB 各阶段的顶点/面/字节数，原生面积、Sim(3) 尺度、配准后面积及面积/GT |
| Surfel 转换 | 配准后的预测/GT 分别保存输入/保留点数、有效法线点数与比例、邻域点数分位数 |
| 配准过程 | 变换矩阵、尺度、对称平方损失、各初始化损失/迭代数、预测/GT 主轴特征值 |
| GT 可见性 | visible/occluded/out-of-view 点数，异常/未命中/超出目标射线数、离表面点数、校正位移最大值/P95。容差 5e-5D、1e-4D、2e-4D 下可见点数及相对默认值的标签变化数 |
| GT 标签与渲染校准 | 独立 GT 点直接/继承标签的不一致数/比例、混淆矩阵、最近邻均距，GT 区域自一致性的全部几何指标。裁剪 K/外参误差、mask 一致性、深度 MAE，GT surfel 对原生 mesh 的输入/30-view 深度、轮廓与法线指标 |

原生面积单位为方法坐标单位²，配准后为 D²。解释结果时考虑采样权重、surfel 转换误差和 ICP 局部最优。已有 `normal_mse` 字段用于过程复核。

</details>

<details>
<summary>已弃用的设计及历史记录</summary>

| 已弃用的设计 | 当前采用的替代方案 | 历史记录用途 |
| --- | --- | --- |
| 以 Sim(3) 重渲染后再做 SSI 作为主深度口径 | 第 2 节采用 Sim(3) 后直接重渲染的五项深度指标 | 保留 `input_ssi` 的五项指标、拟合参数、有效数及失败原因，以及 GT 重渲染 SSI 校准和同像素控制结果，用于追溯额外深度拟合的影响 |
| 深度图/法线图在有效像素交集上计算 RMSE、PSNR | 第 3 节采用含背景的整幅 H×W×3 图像 | 旧交集口径复核记录用于追溯统计区域变化，当前整图结果见 `render_image_fullframe_review.json` |
| 原始坐标下的 24 旋转 ICP 初始化 | 第 1 节采用主轴坐标下的 24 个右手旋转初始化 | 旧 A100 与 v0.5 的同采样对照用于追溯初始化变化和 ICP 局部最优影响 |

历史深度对齐、旧配准对照和图像口径切换的数值与复核记录见实验报告。[R2 结果分析](20261110_hybrid-baseline_gso-quant_eval-v0.5.md)

</details>

保存相机、变换、采样 seed、阶段、文件摘要及源码/config revision。GT 标签缓存签名包含 mesh、评价点、相机、容差、后端与依赖版本。全部视角保存指标和浮点 NPZ，GT 共享，同资产同视角固定色标。默认保存输入视角的 GT/预测深度、法线、mask、有效性、误差图和对照 PNG，`--save-multiview-renders` 追加 30-view PNG。产物支持原子写入、摘要校验及从有效 NPZ 补建 PNG。

| 结果入口 | 内容 |
| --- | --- |
| `result.json` | 完整字段，几何与配准见 `shape`、`registration`、`regions.visible`，输入渲染见 `comparisons.{surfel,native}.input` |
| `summary_seed42.json` / `render_index.md` | 当前单 seed 汇总 / 产物索引 |
| `visible_depth_direct_review.json` | 冻结 NPZ 的输入/30-view MAE、RMSE 复核及 AbsRel、δ1、δ2 补算，源码摘要与独立 review revision |
| `visible_depth_review.json` | WT 原像素 L0＋SSI（`records[].l0_ssi`）与历史同像素控制，原输出为 `depth_fit.json` |
| `render_image_fullframe_review.json` | 整图图像误差、覆盖率、逐视角诊断及复用 LPIPS 的来源摘要与一致性依据 |
| `silhouette_review.json` | 输入/30-view IoU，逐帧交集、预测/GT 前景数量及额外/遗漏前景分析 |

WT SSI 诊断字段依次为 `raw_mae`、`scale`、`shift`、`silhouette_iou`、`valid_pixels`、`depth_coverage`、`status`、`reason`，对应第 2 节的八项诊断量。

P0 已校验 70/70 阶段、47,430 张 PNG，revision `f99c2f63a273b21b0d2e`。R2 已校验 700/700 阶段、15,300 张输入 PNG，revision `d99fa356cec4eb52fb27`。直接深度复核入口为 `examples/review_cached_depth.py`，数值与产物路径见实验记录。[R2 结果分析](20261110_hybrid-baseline_gso-quant_eval-v0.5.md)
