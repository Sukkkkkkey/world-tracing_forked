# R2 baseline v0.5 结果分析

2026-11-11。评测范围为 R2 固定 100 个 GSO 资产、四种方法、seed 42，共 400 个推理候选和 700 个方法阶段结果。本轮按用户最新要求完成单 seed 评测，八 seed 评测暂停。

## 评测范围与口径

Seed 42 复用新服务器上的 `20261013-R2-gso-quant-v1` 输出。WT 使用六层有效点云，TRELLIS.2、Hybrid、Pixal3D 分别评价 decoded mesh 与 exported GLB。全部阶段完成，失败数为 0。两个已知高面数 Hybrid 样本保留在主结果中。

GT 包围盒对角线 D=1。GT 使用 10,000 个配准点、100,000 个评价点，预测点数采用相同上限，WT 有 2 个资产使用全部 72,894 和 74,286 个有效去重点，其余资产达到 100,000 点上限。在主轴坐标下采用 24 个右手旋转初始化的正 Sim(3) ICP。各阶段独立配准，可见区域和渲染复用完整几何变换。输入相机由生成输入图的 GT 内外参及既有裁剪变换确定，四方法共用该相机。

可见区域按输入相机的 GT 首交点、1e-4D 容差划分，预测点继承最近 GT 评价点标签。区域内重新计算双向 CD 和 F-score。GT 可见点每资产为 19,723–49,704 个，遮挡区域结果保存在汇总中。本批 GT 评价点均在视锥内，out-of-view 区域为空。

表中按资产等权平均。CD-L1 单位为 D，CD-L2 为 D²。F-score 阈值为 0.01D 和 0.05D。95% 区间采用资产级配对 bootstrap，5,000 次重抽样，统计 RNG seed 为 20261110。各组全部指标读取推理 seed 42。[协议](evaluation_protocol_v0.5.md)

## 1. Geometry（whole & visible）

| 对象 | 当前配准 | 全部计算指标 |
| --- | --- | --- |
| Whole geometry | 各方法阶段完整形状正 Sim(3) | CD-L1/L2；Pred→GT、GT→Pred 均值；Precision、Recall、F-score，各取 0.01D/0.05D |
| Input-visible geometry | 复用完整形状变换，GT 可见标签分区后重算距离 | 同上，另存预测/GT 区域点数、距离数组及状态 |

- 在本批资产的配准后完整几何和输入可见几何上，CD-L1 均值顺序均为 **TRELLIS.2、Pixal3D、WT、Hybrid**，decoded 与 exported GLB 两组结论一致。
- **WT 的输入可见几何弱于 TRELLIS.2。** 相对 decoded，WT 可见 CD-L1 高 0.005842D，85/100 个资产更差。输入视角深度、法线及轮廓指标也支持这一结论。

### 完整几何

各行有效资产数均为 100/100。

| 方法 | 阶段 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ |
| --- | --- | --- | --- | --- | --- |
| WT | points | 0.013291 | 0.000408329 | 56.93% | 96.27% |
| TRELLIS.2 | decoded | 0.009324 | 0.000206671 | 70.60% | 98.52% |
| TRELLIS.2 | glb | 0.009220 | 0.000204301 | 71.26% | 98.57% |
| Hybrid | decoded | 0.017725 | 0.000799147 | 44.41% | 91.41% |
| Hybrid | glb | 0.018028 | 0.000832398 | 43.45% | 90.86% |
| Pixal3D | decoded | 0.011770 | 0.000364561 | 64.31% | 97.16% |
| Pixal3D | glb | 0.011665 | 0.000362470 | 64.78% | 97.21% |

#### 双向距离与 Precision / Recall

| 方法 / 阶段 | Pred→GT 均值 ↓ | GT→Pred 均值 ↓ | P@0.01 ↑ | R@0.01 ↑ | P@0.05 ↑ | R@0.05 ↑ |
| --- | --- | --- | --- | --- | --- | --- |
| WT points | 0.014008 | 0.012575 | 56.24% | 58.74% | 95.66% | 97.03% |
| TRELLIS.2 decoded | 0.009668 | 0.008980 | 68.73% | 73.50% | 98.52% | 98.58% |
| TRELLIS.2 glb | 0.009807 | 0.008632 | 68.34% | 75.41% | 98.47% | 98.73% |
| Hybrid decoded | 0.025474 | 0.009976 | 34.97% | 66.93% | 86.14% | 98.43% |
| Hybrid glb | 0.026453 | 0.009602 | 33.31% | 69.26% | 85.27% | 98.50% |
| Pixal3D decoded | 0.011728 | 0.011813 | 64.13% | 64.99% | 97.35% | 97.09% |
| Pixal3D glb | 0.011904 | 0.011425 | 63.32% | 66.81% | 97.35% | 97.19% |

### 输入可见几何

各行有效资产数均为 100/100。

| 方法 | 阶段 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ |
| --- | --- | --- | --- | --- | --- |
| WT | points | 0.014876 | 0.000560978 | 53.85% | 94.78% |
| TRELLIS.2 | decoded | 0.009035 | 0.000202477 | 71.76% | 98.67% |
| TRELLIS.2 | glb | 0.008967 | 0.000203560 | 72.54% | 98.62% |
| Hybrid | decoded | 0.018049 | 0.000850307 | 45.03% | 91.38% |
| Hybrid | glb | 0.018255 | 0.000860499 | 44.13% | 90.92% |
| Pixal3D | decoded | 0.011947 | 0.000427380 | 65.37% | 96.87% |
| Pixal3D | glb | 0.011831 | 0.000420102 | 65.56% | 97.02% |

#### 双向距离与 Precision / Recall

| 方法 / 阶段 | Pred→GT 均值 ↓ | GT→Pred 均值 ↓ | P@0.01 ↑ | R@0.01 ↑ | P@0.05 ↑ | R@0.05 ↑ |
| --- | --- | --- | --- | --- | --- | --- |
| WT points | 0.014586 | 0.015166 | 53.18% | 55.96% | 95.66% | 94.18% |
| TRELLIS.2 decoded | 0.009224 | 0.008845 | 70.04% | 74.58% | 98.73% | 98.72% |
| TRELLIS.2 glb | 0.009354 | 0.008581 | 69.77% | 76.53% | 98.70% | 98.61% |
| Hybrid decoded | 0.023625 | 0.012474 | 37.62% | 63.24% | 87.82% | 96.45% |
| Hybrid glb | 0.024737 | 0.011774 | 35.62% | 65.83% | 86.82% | 96.80% |
| Pixal3D decoded | 0.011140 | 0.012754 | 65.41% | 66.00% | 97.94% | 95.96% |
| Pixal3D glb | 0.011353 | 0.012309 | 64.26% | 67.56% | 97.97% | 96.23% |

### 资产级配对差异

差值按表中前者减后者计算，CD 差值为正表示前者误差更高。括号为 95% 区间。所有配对 n=100。

| Mesh 阶段 | 配对 | 完整 CD-L1 Δ [95% CI] | 可见 CD-L1 Δ [95% CI] | 前者 CD 更低数，完整/可见 |
| --- | --- | --- | --- | --- |
| decoded | WT − TRELLIS.2 | +0.003967 [+0.002693, +0.005265] | +0.005842 [+0.004208, +0.007485] | 15/15 |
| decoded | WT − Hybrid | -0.004434 [-0.006026, -0.002953] | -0.003173 [-0.004774, -0.001653] | 73/70 |
| decoded | WT − Pixal3D | +0.001521 [+0.000383, +0.002660] | +0.002929 [+0.001531, +0.004357] | 33/26 |
| glb | WT − TRELLIS.2 | +0.004072 [+0.002793, +0.005384] | +0.005909 [+0.004226, +0.007577] | 16/14 |
| glb | WT − Hybrid | -0.004736 [-0.006419, -0.003165] | -0.003379 [-0.005095, -0.001770] | 70/67 |
| glb | WT − Pixal3D | +0.001627 [+0.000485, +0.002771] | +0.003045 [+0.001669, +0.004457] | 30/25 |

Decoded 组完整 CD-L1 最优资产数为 TRELLIS.2 59、Pixal3D 30、WT 10、Hybrid 1。GLB 组为 59、31、9、1。WT 点云作为两组共同参照。

## 2. Visible depth

主评测使用完整形状 Sim(3) 后的几何，在固定 GT 输入裁剪相机下直接计算重渲染深度误差。四方法共同采用 surfel 表示。WT 原像素 L0＋SSI 在同表中列为补充行，评价原像素相对深度结构。表中的深度来源与对齐列用于区分两种评价条件，四方法排序采用主评测各行。

每项指标先在双方 mask 内有限正深度的像素交集上计算，再对有效资产等权平均。MAE、RMSE 单位为 D，AbsRel、δ1、δ2 为无量纲比例。δ1、δ2 使用严格阈值 1.25、1.25²。主评测的有效条件为深度交集非空，五项误差均在这一交集内计算。深度覆盖率见第 3 节。WT SSI 采用下述拟合有效性条件。

| 方法 / 阶段 | 深度来源与对齐 | n / 100 | MAE ↓ | RMSE ↓ | AbsRel ↓ | δ1 ↑ | δ2 ↑ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WT points | Sim(3) 重渲染 | 100 | 0.038284 | 0.060909 | 0.023493 | 0.990667 | 0.999991 |
| TRELLIS.2 decoded | Sim(3) 重渲染 | 100 | 0.020613 | 0.035658 | 0.012576 | 0.998090 | 1.000000 |
| TRELLIS.2 glb | Sim(3) 重渲染 | 100 | 0.020939 | 0.036014 | 0.012742 | 0.998050 | 1.000000 |
| Hybrid decoded | Sim(3) 重渲染 | 100 | 0.038486 | 0.054319 | 0.023501 | 0.996595 | 1.000000 |
| Hybrid glb | Sim(3) 重渲染 | 100 | 0.040334 | 0.057026 | 0.024646 | 0.995945 | 1.000000 |
| Pixal3D decoded | Sim(3) 重渲染 | 100 | 0.028196 | 0.045295 | 0.017222 | 0.995004 | 1.000000 |
| Pixal3D glb | Sim(3) 重渲染 | 100 | 0.028409 | 0.045109 | 0.017269 | 0.995237 | 1.000000 |
| WT L0（补充） | 原像素 SSI | 99 | 0.022520 | 0.031008 | 0.013624 | 0.999666 | 1.000000 |

R2 固定 seed 42，完整评测 revision 为 `d99fa356cec4eb52fb27`，深度补算 review revision 为 `4f0aec0c2324f6e8ae3a`。新增 AbsRel、δ1、δ2 与原有 MAE/RMSE 使用相同像素，逐视角复核旧指标和像素数。原生 mesh 结果、逐视角数值及来源摘要也保存在补算结果中。[直接深度补算](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/baseline-v05-r2-20261110/visible_depth_direct_review.json)

WT−TRELLIS.2 decoded 的输入深度 MAE 差值为 +0.017672 [+0.011945, +0.023412]D。WT−Hybrid decoded 的对应差值为 -0.000202 [-0.003876, +0.003469]D，区间跨零。完整几何的排序需要结合每项渲染指标单独解读。[全部渲染指标、覆盖率和有效像素数](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/summary_seed42.json)

### WT 原像素 L0＋SSI 补充说明

该项读取 WT `prediction.npz` 的 `xyz[0, ..., 2]`、`mask[0]`，与 `gt_depth.npz` 的 `depth`、`mask` 配对。GT 深度须匹配实际输入图的视角、裁剪、缩放与像素中心约定，双方采用相机轴向 Z。在双方 mask 内有限正深度的像素交集上，逐资产最小二乘拟合 z′=az+b。有效条件为至少 3 个像素、设计矩阵秩为 2、a>0、对齐后深度全部为正，以及交集覆盖 GT 有效像素至少 95%。模型估计 K 与 GT K 的差异由三维与重投影诊断量化，L0＋SSI 评价逐像素相对深度结构。

该补充行由 `visible_depth_review.json` 的 `all_valid_assets.l0_ssi` 汇总，99 个有效资产等权平均，失败率为 1/100（1%）。[WT 原像素深度复核](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/baseline-v05-r2-20261110/visible_depth_review.json)

同一 99 个有效资产的拟合诊断量如下，各列为资产等权均值。拟合前 MAE 使用与 SSI 相同的像素集合。a、b 为逐资产独立拟合参数的均值。

| 有效范围 | 拟合前 MAE（D）↓ | 有效像素数 | a | b（D） |
| --- | --- | --- | --- | --- |
| 99/100 | 0.203190 | 49,322.26 | 0.873783 | 0.317572 |

1 个无效资产为 `Razer_Taipan_White_Ambidextrous_Gaming_Mouse`，保存的拟合尺度 a=−0.146581，未满足 a>0。该项记录为失败，五项 SSI 指标汇总分母为 99。逐资产参数、像素数及失败原因保存在 `records[].l0_ssi`。对应论文 WT-O 的 MAE、RMSE、AbsRel、δ1、δ2 依次为 0.0149、0.0243、0.0079、0.9996、0.9999，单位沿用原表。

论文 Table 1 的 visible depth 使用逐样本尺度与偏移对齐。R2 的直接 L0 路径读取原像素位置的 WT Z，并沿用已有 SSI 实现。R2 的 MAE/RMSE 单位为 D，论文数值沿用原表。对象集合、视角、距离归一化、有效 mask 和聚合权重仍需进一步对齐。[World Tracing Table 1 与附录 C](https://arxiv.org/html/2606.13652v1#S4.T1)

## 3. Input view & multi-view

| 指标类别 | Input view | 30-view Multi-view |
| --- | --- | --- |
| 深度覆盖率 | 有效深度交集/GT 有效前景，见专表 | 同左 |
| 深度图 | RMSE、PSNR、LPIPS | 同左 |
| 法线图 | RMSE、PSNR、LPIPS、平均角误差、法线覆盖率 | 同左 |
| 轮廓 | Silhouette IoU，见专表与配对分析 | 同左 |
| 外观 | GLB RGB PSNR、RGB LPIPS | N/A |
| 支持量 | 有效像素数、有效资产数/总数 | 同类逐视角数量、有效视角数/总数 |

四方法采用共同 surfel，与 GT 原生 mesh 渲染比较。输入视角为 504²，multi-view 为 30 个固定球面 Hammersley 方向、512²。各阶段输入视角为 100/100 有效资产，multi-view 为 3,000/3,000 有效视角。原生 mesh 的对应结果也保存在复核 JSON 中。

深度图沿用同资产、同视角的 GT 可视化范围，线性映射到 [0,1] 并复制为三通道灰度。法线图使用 I=(n+1)/2。两类图像的 RMSE/PSNR 均对整幅 H×W×3 数组计算，包含背景和 mask 不重合区域。RMSE 使用归一化强度，PSNR 按峰值 1 和整图 MSE 计算。LPIPS 使用双方各自有效区域及 0.5 中性灰背景的整图，并将 RGB 转为 [-1,1] 输入 AlexNet v0.1。所有指标从浮点数组计算，先逐视角计算 RMSE/PSNR，再按视角、资产等权汇总。法线角误差在双方有效法线交集上计算。Visible depth 的有效深度交集口径见第 2 节。

### 深度覆盖率

覆盖率=count(M_pred∩M_GT)/count(M_GT)，M 表示各自前景 mask 内有限正深度的像素。下表使用配准后重渲染的 mask，各行 n=100。

| 方法 / 阶段 | Input-view 深度覆盖 ↑ | 30-view 深度覆盖 ↑ |
| --- | --- | --- |
| WT points | 95.05% | 92.27% |
| TRELLIS.2 decoded | 96.43% | 95.10% |
| TRELLIS.2 glb | 96.77% | 95.45% |
| Hybrid decoded | 96.55% | 94.98% |
| Hybrid glb | 96.81% | 95.36% |
| Pixal3D decoded | 95.03% | 93.20% |
| Pixal3D glb | 95.34% | 93.54% |

WT 原像素 L0＋SSI 补充的深度覆盖率为 99.39%，按 99 个 SSI 有效资产等权平均，采用原像素 mask 交集。其拟合有效条件见第 2 节。

### Silhouette IoU

下表为资产等权均值及 95% bootstrap 区间，各行 n=100。IoU=交集/并集，同时受到遗漏前景与额外前景的影响。

| 方法 / 阶段 | Input-view Silhouette IoU ↑ | 30-view Silhouette IoU ↑ |
| --- | --- | --- |
| WT points | 0.8743 [0.8541, 0.8920] | 0.8455 [0.8240, 0.8660] |
| TRELLIS.2 decoded | 0.9167 [0.9025, 0.9294] | 0.8953 [0.8789, 0.9107] |
| TRELLIS.2 glb | 0.9152 [0.9008, 0.9281] | 0.8942 [0.8778, 0.9095] |
| Hybrid decoded | 0.8264 [0.8076, 0.8440] | 0.8062 [0.7866, 0.8244] |
| Hybrid glb | 0.8136 [0.7940, 0.8318] | 0.7951 [0.7763, 0.8127] |
| Pixal3D decoded | 0.8935 [0.8741, 0.9104] | 0.8654 [0.8434, 0.8851] |
| Pixal3D glb | 0.8904 [0.8713, 0.9073] | 0.8638 [0.8418, 0.8832] |

共同 surfel 的资产均值在输入视角和 30-view 下均按 TRELLIS.2、Pixal3D、WT、Hybrid 排列。以下配对差值使用相同 100 个资产，正值表示 WT 的 Silhouette IoU 更高。

| 配对差值 | Input view | 30-view |
| --- | --- | --- |
| WT − TRELLIS.2 decoded | -0.042420 [-0.057839, -0.027095] | -0.049883 [-0.064067, -0.036446] |
| WT − Pixal3D decoded | -0.019223 [-0.030669, -0.007139] | -0.019935 [-0.030541, -0.008988] |
| WT − Hybrid decoded | +0.047919 [+0.036777, +0.060192] | +0.039297 [+0.028566, +0.051254] |

以各资产 GT 前景面积为分母，Hybrid decoded 的输入额外前景平均为 18.29%，WT 为 9.79%，TRELLIS.2 decoded 为 5.49%。对应遗漏前景分别为 3.45%、4.95%、3.57%。Hybrid 的轮廓误差以额外投影区域为主，其较高的深度覆盖率与较低的 IoU 可以同时出现。

在阶段各自 Sim(3) 配准的结果中，Hybrid GLB 相对 decoded 的输入 IoU 差值为 -0.012846 [-0.017665, -0.008393]。额外前景/GT 从 18.29% 增至 20.64%。这些数值描述固定相机下的投影轮廓。[轮廓像素复核与配对统计](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/baseline-v05-r2-20261110/silhouette_review.json)

### 输入视角图像指标

各行有效资产数为 100/100。图像 RMSE 使用 [0,1] 强度单位，PSNR 使用 dB。

| 方法 / 阶段 | 深度图 RMSE ↓ | 深度图 PSNR ↑，dB | 深度图 LPIPS ↓ | 法线图 RMSE ↓ | 法线图 PSNR ↑，dB | 法线图 LPIPS ↓ | 法线角误差 ↓ | 法线覆盖 ↑ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| WT points | 0.051855 | 26.84 | 0.1209 | 0.083151 | 22.01 | 0.1693 | 24.47° | 81.73% |
| TRELLIS.2 decoded | 0.036103 | 29.76 | 0.0556 | 0.062793 | 24.55 | 0.0986 | 19.03° | 96.42% |
| TRELLIS.2 glb | 0.036497 | 29.64 | 0.0556 | 0.064045 | 24.33 | 0.1108 | 19.85° | 96.77% |
| Hybrid decoded | 0.055646 | 25.87 | 0.1347 | 0.087878 | 21.53 | 0.1983 | 25.49° | 96.22% |
| Hybrid glb | 0.058829 | 25.37 | 0.1421 | 0.091722 | 21.15 | 0.2247 | 26.91° | 96.68% |
| Pixal3D decoded | 0.043501 | 28.50 | 0.0767 | 0.070496 | 23.67 | 0.1294 | 22.01° | 94.98% |
| Pixal3D glb | 0.043594 | 28.45 | 0.0751 | 0.071331 | 23.52 | 0.1417 | 22.71° | 95.33% |

WT 的输入法线覆盖为 81.73%，与同视角深度覆盖相差 13.32 个百分点，体现额外法线有效性筛选的影响。当前实现对法线无效的点保留深度渲染并将法线属性置零，覆盖率因此包含采样和法线估计的影响。

#### GLB 输入 RGB 外观

采用完整形状 Sim(3)、unlit base-color 与中性灰背景，各行 n=100。

| 方法，GLB | RGB PSNR ↑，dB | RGB LPIPS ↓ |
| --- | --- | --- |
| TRELLIS.2 | 21.55 | 0.1267 |
| Hybrid | 19.88 | 0.2067 |
| Pixal3D | 21.47 | 0.1318 |

### 30 视角的资产级均值

各方法阶段为 100 个资产、3,000 个有效视角。先对每资产 30 视角等权平均，再对资产等权平均。

深度图与法线图的相似性使用与输入视角相同的图像编码和误差定义。

| 方法 / 阶段 | 深度图 RMSE ↓ | 深度图 PSNR ↑，dB | 深度图 LPIPS ↓ | 法线图 RMSE ↓ | 法线图 PSNR ↑，dB | 法线图 LPIPS ↓ | 法线角误差 ↓ | 法线覆盖 ↑ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| WT points | 0.052936 | 26.30 | 0.1317 | 0.081650 | 22.04 | 0.1534 | 27.47° | 76.67% |
| TRELLIS.2 decoded | 0.034163 | 30.15 | 0.0502 | 0.058281 | 25.14 | 0.0902 | 19.78° | 95.10% |
| TRELLIS.2 glb | 0.034417 | 30.05 | 0.0503 | 0.059203 | 24.96 | 0.0991 | 20.52° | 95.45% |
| Hybrid decoded | 0.055814 | 25.72 | 0.1129 | 0.080837 | 22.13 | 0.1666 | 26.98° | 94.60% |
| Hybrid glb | 0.058926 | 25.26 | 0.1196 | 0.083626 | 21.83 | 0.1875 | 27.96° | 95.25% |
| Pixal3D decoded | 0.039857 | 28.92 | 0.0677 | 0.064470 | 24.26 | 0.1119 | 22.28° | 93.18% |
| Pixal3D glb | 0.040105 | 28.83 | 0.0673 | 0.065386 | 24.10 | 0.1214 | 23.04° | 93.54% |

同一 GT 范围之外的预测深度会截断到灰度端点。七个方法阶段的资产平均截断比例，输入视角为 0.02%–0.50%，30-view 为 0.10%–0.67%。整图平均同时受前景面积和背景填充值影响，结果结合深度覆盖率、Silhouette IoU 与 Visible depth 解释。逐视角范围、截断数量、完整分表示结果和源码/权重摘要均已保存。[图像指标复核](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/baseline-v05-r2-20261110/render_image_fullframe_review.json)

## 4. 其他补充

| 对象 | 已计算指标或诊断量 | 结果位置 |
| --- | --- | --- |
| Occluded / out-of-view | 第 1 节全部几何指标、点数与状态 | regions.occluded / regions.out_of_view |
| 原生与 scale-only 几何 | WT/Hybrid 原生 CD-L1/L2、F@0.01/0.05；WT scale-only 同四项 | camera_diagnostics / native_camera_shape |
| WT L0 与内参 | 三类 XYZ RMSE、两种尺度、平移、对应像素数；三组 K、投影误差均值/P95 | camera_diagnostics |
| Decoded / GLB | 同 decoded 变换的完整/区域几何指标和面积；独立配准阶段的共有指标差值 | export_pair / paired_stages |
| 实际 WT parent | 父点云完整几何全部指标；Hybrid−parent CD-L1 | wt_parent / hybrid_minus_parent.cd |
| Mesh 规模 | 顶点/面数、字节数、原生/配准后面积、面积/GT、Sim(3) 尺度 | geometry |
| 历史深度对齐 | Sim(3) 重渲染后 SSI 的五项指标、有效范围与拟合诊断；61 资产同像素控制 | input_ssi / visible_depth_review.json |
| Surfel、配准、可见性与校准 | 点数/法线有效率/邻域分位数；配准损失与迭代；射线异常与容差/标签误差；GT 相机、区域与表示自一致性 | surfel_diagnostics / registration / visibility / calibration JSON |

### 历史深度对齐诊断

#### Sim(3) 重渲染后 SSI

像素配对由固定 GT 相机与渲染建立，对应同一相机射线的两次首交点深度。此项记录既有实验中可进一步被深度尺度与偏移吸收的残余误差。

在各阶段完整几何 Sim(3) 重渲染后，逐资产对深度数值拟合正尺度与标量偏移，计算 MAE、RMSE、AbsRel、δ<1.25、δ<1.25²。本项目 SSI 要求深度覆盖率至少 95%，并检查拟合秩、尺度及对齐后深度的有效性。表中 n 为通过这些检查的资产数，δ 为比例。

| 方法 / 阶段 | n / 100 | MAE ↓ | RMSE ↓ | AbsRel ↓ | δ<1.25 ↑ | δ<1.25² ↑ |
| --- | --- | --- | --- | --- | --- | --- |
| WT points | 63 | 0.026336 | 0.041312 | 0.016105 | 0.997503 | 1.000000 |
| TRELLIS.2 decoded | 85 | 0.016476 | 0.029718 | 0.010109 | 0.998556 | 0.999993 |
| TRELLIS.2 glb | 86 | 0.016526 | 0.029640 | 0.010130 | 0.998535 | 0.999998 |
| Hybrid decoded | 70 | 0.027375 | 0.041596 | 0.016991 | 0.998567 | 1.000000 |
| Hybrid glb | 75 | 0.029090 | 0.043783 | 0.018040 | 0.998085 | 1.000000 |
| Pixal3D decoded | 63 | 0.018236 | 0.031492 | 0.011128 | 0.997650 | 1.000000 |
| Pixal3D glb | 64 | 0.017666 | 0.030294 | 0.010735 | 0.997897 | 1.000000 |

WT 重渲染 SSI 的 37 项无效结果均由覆盖率低于 95% 引起。各方法的有效集合存在差异，配对结论使用共同资产集合。原有五项 SSI 指标保存在结果 JSON 的 input_ssi 字段。

#### 同像素控制比较

完整几何 ICP 的目标为双向三维最近邻平方距离，包含遮挡区域，并允许重新匹配点对应。深度 SSI 则在固定像素上拟合 z′=az+b。在固定相机射线上，深度偏移对应的三维操作为 p′=(a+b/z)p，其倍率随深度变化。重渲染还会改变首交点和有效像素集合。这几种优化的目标及对应关系不同。

以下同像素控制比较使用独立筛选出的 61 个共同有效资产。三条路径固定相同 GT 像素，交集覆盖率至少 95%，两条 SSI 路径均通过拟合有效性检查。各行按这 61 个资产等权平均，MAE、RMSE 单位为 D。

| WT 评测路径，相同 61 资产及像素 | MAE ↓ | RMSE ↓ |
| --- | --- | --- |
| 原像素 L0＋SSI | 0.018110 | 0.025382 |
| 完整 Sim(3) 后重渲染 | 0.026221 | 0.045367 |
| 完整 Sim(3) 后重渲染，再做 SSI | 0.025704 | 0.040735 |

SSI 的最小二乘目标直接约束 RMSE。对原有 63 个重渲染 SSI 有效资产，逐资产 RMSE 均未升高，MAE 有 21 个资产升高，反映平方误差拟合对残差分布的取舍。上述 61 资产子集用于控制像素的比较，全体 L0 统计采用第 2 节的 99 个有效资产。[逐资产深度复核与有效集合](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/baseline-v05-r2-20261110/visible_depth_review.json)

### Hybrid 与实际 WT parent

- **当前 Hybrid 流程的几何收益仍未出现。** 相对实际 WT parent，decoded 完整 CD-L1 平均增加 0.004742D，76/100 个资产退化。

Hybrid 的实际 WT parent 完整 CD-L1 均值为 0.012983。Hybrid−parent 的 decoded 差值为 +0.004742 [+0.003332, +0.006295]D，GLB 差值为 +0.005044 [+0.003529, +0.006698]D。这项对照固定了实际输入点云，退化归因仍涵盖结构构造、生成、解码及后处理整个后续流程。[逐资产指标与配对统计](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/summary_seed42.json)

### Decoded 与 GLB 导出对照

阶段主表采用各自配准结果。下表另将同 seed 的 GLB 固定在 decoded 配准变换下计分，控制配准变化。Δ 为 GLB−decoded，所有比较 n=100。

| 方法 | 同变换完整 CD-L1 Δ [95% CI] | 同变换可见 CD-L1 Δ [95% CI] | 改善资产数，完整/可见 | 各自配准完整 CD-L1 Δ |
| --- | --- | --- | --- | --- |
| TRELLIS.2 | -0.000116 [-0.000144, -0.000085] | -0.000151 [-0.000193, -0.000109] | 80/81 | -0.000104 |
| Hybrid | +0.000246 [+0.000063, +0.000457] | +0.000162 [-0.000015, +0.000369] | 54/57 | +0.000302 |
| Pixal3D | -0.000132 [-0.000167, -0.000096] | -0.000218 [-0.000278, -0.000162] | 79/83 | -0.000106 |

TRELLIS.2 和 Pixal3D 的同变换完整、可见 CD-L1 平均改善。Hybrid 完整 CD-L1 的平均退化区间为正，可见 CD-L1 差值区间跨零。按各自配准结果，TRELLIS.2、Hybrid、Pixal3D 的输入法线角误差分别增加 0.82°、1.42°、0.70°，30 视角平均分别增加 0.74°、0.98°、0.76°。

当前 decoded PLY 对应解码并首次补洞后的网格，GLB 包含后续补洞、重网格化、简化与材质导出。两组结果分别用于检查解码阶段与最终导出资产。导出的 CD 改善幅度和法线变化共同纳入阶段比较。[解码产物保存位置](../wt/batch.py) · [导出流程](../wt/textured_mesh/pipeline.py)

下表记录面数与配准后累计三角形面积。面积/GT 对全部三角面求和。

| 方法 | 面数中位数，百万，decoded→GLB | 面积/GT 均值 | 面积/GT 中位数 |
| --- | --- | --- | --- |
| TRELLIS.2 | 5.986 → 0.972 | 1.469 → 2.463 | 1.143 → 2.143 |
| Hybrid | 11.371 → 0.960 | 4.245 → 5.994 | 2.841 → 4.661 |
| Pixal3D | 5.752 → 0.977 | 1.293 → 2.166 | 1.204 → 2.078 |

当前导出使用 remesh_band=1、remesh_project=0，CuMesh 提取 UDF=ε 的等值面，可形成原表面两侧的壳层，再进行简化。累计面积会计入内侧壳面，面积变化与外表面偏移、占据体积需要分别解释。[锁定版本的重网格化实现](https://github.com/JeffreyXiang/CuMesh/blob/12289e1062f0603f2f0d0771b02e1395d247f26f/cumesh/remeshing.py#L98)

### WT 原生坐标与尺度诊断

以下均为相同 100 个资产。Scale-only 使用 L0 像素对应点估计绕相机原点的等比缩放，再用于完整点云。L0 的尺度加平移拟合是另一项对应点诊断。

| 诊断 | 资产均值 |
| --- | --- |
| 完整点云 CD-L1，原生相机坐标 | 0.110963D |
| 完整点云 CD-L1，相机原点 scale-only | 0.065244D |
| 完整点云 CD-L1，完整 Sim(3) | 0.013291D |
| L0 对应点 XYZ RMSE，原生 → scale-only → scale+translation | 0.230799 → 0.116758 → 0.040223D |
| 拟合尺度均值，相机原点 / 同时拟合平移 | 1.0750 / 0.7703 |
| L0 重投影误差，GT K_crop / 保存内参 / 从 XYZ 拟合内参 | 48.41 / 13.03 / 0.216 px |

原生误差包含尺度、平移及内参不匹配，这些拟合展示了不同校正自由度下的残余误差。原生指标可用于判断相机坐标输出能否直接使用，配准后主指标用于当前目标下的形状比较。旧评测中 WT 的 alpha mask 与按像素索引读取的深度受到输入 mask 约束，本轮 Sim(3) 后以共同 surfel 重新投影几何，输入 IoU 为 0.8743。尺度、深度和像素投影之间的关系需要由这些独立诊断共同支持。

### 两个高面数 Hybrid 样本

| 资产 | 阶段 | 三角面数 | 面积/GT | 完整 CD-L1 | 可见 CD-L1 |
| --- | --- | --- | --- | --- | --- |
| 3M 防滑卷 | decoded | 189,504,322 | 67.691 | 0.015303 | 0.015904 |
| 3M 防滑卷 | glb | 983,293 | 4.511 | 0.013533 | 0.013100 |
| Pokémon 双包装盒 | decoded | 145,358,310 | 33.352 | 0.020459 | 0.020176 |
| Pokémon 双包装盒 | glb | 965,784 | 23.324 | 0.019866 | 0.019921 |

两个样本可确认存在网格规模与累计面积异常。输入视角原生 mesh 对照中，3M 卷的法线噪声、内孔错误结构在导出后仍可见，Pokémon 包装盒的前表面深度偏移与局部起伏也继续存在。几何体积膨胀程度、重复或内部表面占比，以及神经解码和补洞各自的贡献仍待专门诊断。

[3M decoded](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/samples/3M_Antislip_Surfacing_Light_Duty_White/wt_trellis2/defaults-v1/seed-0042/decoded/f46abba7953d157c50fc/renders/native/input/000/comparison.png) · [3M glb](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/samples/3M_Antislip_Surfacing_Light_Duty_White/wt_trellis2/defaults-v1/seed-0042/glb/e340653bdd0d06010de6/renders/native/input/000/comparison.png)

[Pokémon decoded](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/samples/Pokémon_Omega_Ruby_Alpha_Sapphire_Dual_Pack_Nintendo_3DS/wt_trellis2/defaults-v1/seed-0042/decoded/2368ff1f5d8954f8d3cd/renders/native/input/000/comparison.png) · [Pokémon glb](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/samples/Pokémon_Omega_Ruby_Alpha_Sapphire_Dual_Pack_Nintendo_3DS/wt_trellis2/defaults-v1/seed-0042/glb/370771c7a9efb952f63c/renders/native/input/000/comparison.png)

剔除这两个在评测前已标记的高内存样本后，剩余 98 资产的 decoded 完整 CD-L1 均值仍按 TRELLIS.2 0.009383、Pixal3D 0.011807、WT 0.013129、Hybrid 0.017722 排列。可见几何与 GLB 组也保持这一排序。主结果使用全部 100 资产。

### 复现变化与评测限制

本轮复用 A100 恢复输出。旧评测与 v0.5 的 400 组配准点、评价点逐数组完全一致，完整几何的变化来自配准初始化更新。v0.5 在主轴坐标下搜索 24 个旋转，旧版从原始坐标的 24 个旋转初始化。

| 方法，WT points / mesh decoded | 旧 A100 CD-L1 | v0.5 CD-L1 | 均值变化 | 单资产最大绝对变化 |
| --- | --- | --- | --- | --- |
| WT | 0.013285 | 0.013291 | +0.000006 | 0.002218 |
| TRELLIS.2 | 0.009297 | 0.009324 | +0.000027 | 0.001639 |
| Hybrid | 0.017753 | 0.017725 | -0.000028 | 0.001103 |
| Pixal3D | 0.011796 | 0.011770 | -0.000026 | 0.001455 |

PEEKABOO_ROLLER 的 WT、TRELLIS.2 CD-L1 分别增加 0.002218D、0.001639D，对应配准损失也升高，体现有限初始化 ICP 的局部最优影响。同一个冻结流程提供统一比较条件，输入语义面的对应关系仍受对称性和几何畸变影响。

#### 校准

| 校准项 | 结果 |
| --- | --- |
| GT 区域自一致性 | 100/100 资产 CD-L1/L2=0，非空区域 F@0.01=1 |
| GT 首交点异常射线 | 0 |
| 裁剪内参矩阵最大误差 | 5.684e-14 |
| GT 输入 mask / 深度重渲染 | 100/100 mask 完全一致，资产深度 MAE 最大 2.502e-07D |
| 射线端点表面校正最大位移 | 1.871e-08D |
| 容差 5e-5D 相对 1e-4D | 每 100,000 点平均变化 11.17 点，最大 36 点（0.036%） |
| 容差 2e-4D 相对 1e-4D | 每 100,000 点平均变化 23.34 点，最大 78 点（0.078%） |
| 独立 10,000 点的最近 GT 标签继承误差 | 均值 0.8467%，资产范围 0.20%–2.92% |
| GT surfel→原生 mesh 输入深度 MAE | 0.000604D |
| GT surfel→原生 mesh 输入法线角误差 | 均值 6.29°，范围 1.09°–20.82° |
| GT surfel→原生 mesh 30 视角法线角误差 | 资产均值 6.31° |

- 配准后主结果使用 GT 辅助旋转、平移和正等比缩放，结论范围为该条件下的形状质量。
- WT 按像素对应点采样，mesh 按三角形面积采样，两类表示的区域权重存在差异。Surfel 转换和 PCA 法线估计引入额外误差，WT 的法线覆盖率尤其需要随法线分数一起报告。
- 最近 GT 点传递可见标签在边界处存在上述误差。容差敏感性衡量的是标签变化数量，区域 CD 的解释同时受边界归属和采样密度影响。
- CD/F-score 对拓扑、重复表面和小尺度起伏的约束有限，面积统计、法线和深度图为这些现象提供附加证据。
- 跨硬件稳定性、随机 seed 方差、best-of-8 收益及与论文完整协议的对齐仍待后续实验。本报告的 bootstrap 区间描述这 100 个资产的重抽样变化。

[GT 相机与自一致性校准](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/gt_calibration.json) · [可见标签校准](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/visibility_calibration.json) · [复现、导出和敏感性统计](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/analysis_seed42.json)

### 代码与产物

- 整图 RMSE/PSNR 补算通过 76 项相关回归测试，覆盖 700 个方法阶段、1,300 个表示和 40,300 帧。整图 review revision 为 `83590750d61a36cd7be9`，LPIPS 来源为编码相同的图像复核结果，来源摘要与验证依据随结果保存。
- 此前交集口径的图像指标补充通过 71 项相关回归测试，复核 700 个方法阶段、1,300 个 GT 对照表示及 40,300 帧。图像 review revision 为 `e1ae0a5d34a805421e7b`。LPIPS 批量/单张一致性核对 26 项，最大绝对差为 2.46e-07。
- 本次直接深度指标补充通过项目 `tests/` 的 231/231 项测试。独立公式复核覆盖 403 帧，全部 40,300 帧的旧深度指标和像素数复核通过。
- 本次直接深度补算覆盖 700 个方法阶段、1,300 个 GT 对照表示，共 1,300 个输入视角和 39,000 个 multi-view 帧。补算入口为 `examples/review_cached_depth.py`，输入 NPZ、GT、配准矩阵、相机和源码摘要记录在独立 review 结果中。
- 实现提交为 `57d0f1afa0c31a0c2334cbc00ebd61ce1191e82c`，提交说明为 `evaluation_protocol_v0.5`。评测 revision 为 `d99fa356cec4eb52fb27`。提交临时沿用仓库上一提交的作者身份。配准采用 8 个工作线程，在 P0 单资产对照中，4/8 线程的变换矩阵最大差值为 0。
- 初次 v0.5 完整回归测试 224/224 通过。深度展示修复通过 48 项相关回归测试，并从缓存复算了 100 个 WT 资产的 L0 与重渲染深度。700/700 阶段完成并校验，每项均保存输入视角和 30 个 multi-view 的数值数组。几何双向距离复算 CD-L1/L2、Precision、Recall、F-score，渲染深度、法线基础指标及像素数从 NPZ 复核。LPIPS 保留评测输出及文件摘要。
- 默认 PNG 仅保存 input-view，共 15,300 张，逐图校验通过。`--save-multiview-renders` 可额外保存 30 个 multi-view 的 PNG。GT 产物共享，同资产同视角统一色标。
- 本轮单 seed 汇总为 `summary_seed42.json`，700 项预算全部完成。原始八 seed 计划及其汇总继续保留，记录其余 4,900 项待运行。队列在 seed 42 完成后停止，运行状态与范围调整记录保存在任务日志中。
- 上一版协议内容 SHA-256 经复核为 `ad1570c68a2bcc85db03bfbf8e730ef46eda9b6903624b084a3927ac2474f1e1`，文件位于 `docs/archived/evaluation_protocol_v0.md`。

[单 seed 汇总](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/summary_seed42.json) · [渲染产物索引](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/render_index.md) · [完整性校验](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/baseline-v05-r2-20261110/seed42-audit.json)
