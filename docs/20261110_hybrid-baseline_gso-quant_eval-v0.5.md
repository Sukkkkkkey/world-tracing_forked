# R2 baseline v0.5 结果分析

2026-11-11。评测范围为 R2 固定 100 个 GSO 资产、四种方法、seed 42，共 400 个推理候选和 700 个方法阶段结果。本轮按用户最新要求完成单 seed 评测，八 seed 评测暂停。

## 可确认的结论

- 在本批资产的配准后完整几何和输入可见几何上，CD-L1 均值顺序均为 **TRELLIS.2、Pixal3D、WT、Hybrid**，decoded 与 exported GLB 两组结论一致。
- **WT 的输入可见几何弱于 TRELLIS.2。** 相对 decoded，WT 可见 CD-L1 高 0.005842D，85/100 个资产更差。输入视角深度、法线及轮廓指标也支持这一结论。
- **当前 Hybrid 流程的几何收益仍未出现。** 相对实际 WT parent，decoded 完整 CD-L1 平均增加 0.004742D，76/100 个资产退化。
- **WT 原生输出存在尺度及相机坐标不匹配。** 相机原点 scale-only 校正能降低误差，加入平移后 L0 对应点误差进一步下降。拟合内参显著降低重投影误差，说明原生误差同时含有相机模型差异。
- **GLB 导出有方法和指标依赖。** TRELLIS.2、Pixal3D 的完整 CD-L1 均值小幅改善，Hybrid 均值升高。三个 mesh 方法的输入视角及 multi-view 法线角误差均值均升高。

## 评测范围与口径

Seed 42 复用新服务器上的 `20261013-R2-gso-quant-v1` 输出。WT 使用六层有效点云，TRELLIS.2、Hybrid、Pixal3D 分别评价 decoded mesh 与 exported GLB。全部阶段完成，失败数为 0。两个已知高面数 Hybrid 样本保留在主结果中。

GT 包围盒对角线 D=1。GT 使用 10,000 个配准点、100,000 个评价点，预测点数采用相同上限，WT 有 2 个资产使用全部 72,894 和 74,286 个有效去重点，其余资产达到 100,000 点上限。在主轴坐标下采用 24 个右手旋转初始化的正 Sim(3) ICP。各阶段独立配准，可见区域和渲染复用完整几何变换。输入相机由生成输入图的 GT 内外参及既有裁剪变换确定，四方法共用该相机。

可见区域按输入相机的 GT 首交点、1e-4D 容差划分，预测点继承最近 GT 评价点标签。区域内重新计算双向 CD 和 F-score。GT 可见点每资产为 19,723–49,704 个，遮挡区域结果保存在汇总中。本批 GT 评价点均在视锥内，out-of-view 区域为空。

表中按资产等权平均。CD-L1 单位为 D，CD-L2 为 D²。F-score 阈值为 0.01D 和 0.05D。95% 区间采用资产级配对 bootstrap，5,000 次重抽样，统计 RNG seed 为 20261110。各组全部指标读取推理 seed 42。[协议](evaluation_protocol_v0.5.md)

## 配准后的几何主结果

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

Hybrid 的实际 WT parent 完整 CD-L1 均值为 0.012983。Hybrid−parent 的 decoded 差值为 +0.004742 [+0.003332, +0.006295]D，GLB 差值为 +0.005044 [+0.003529, +0.006698]D。这项对照固定了实际输入点云，退化归因仍涵盖结构构造、生成、解码及后处理整个后续流程。[逐资产指标与配对统计](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/summary_seed42.json)

## 输入视角与 multi-view

四方法使用共同 surfel 表示与 GT 原生 mesh 渲染比较。输入视角为 504²，multi-view 为 30 个固定球面 Hammersley 方向、512²。每组输入视角指标有效数为 100/100，multi-view 为 3,000/3,000，所有资产均有 30 个有效视角。Mesh 原生三角面结果也达到相同有效数量，并保存在 JSON 中。

深度 MAE 在深度有效交集计算，法线角误差在法线有效交集计算。覆盖率分母为 GT 前景像素，LPIPS 使用中性背景整图。各方法有效像素集合由各自渲染决定，误差需与覆盖率共同解释。

### 输入视角

| 方法 / 阶段 | 深度 MAE ↓ | IoU ↑ | 法线角误差 ↓ | 法线 LPIPS ↓ | 深度覆盖 ↑ | 法线覆盖 ↑ |
| --- | --- | --- | --- | --- | --- | --- |
| WT points | 0.038284 | 0.8743 | 24.47° | 0.1693 | 95.05% | 81.73% |
| TRELLIS.2 decoded | 0.020613 | 0.9167 | 19.03° | 0.0986 | 96.43% | 96.42% |
| TRELLIS.2 glb | 0.020939 | 0.9152 | 19.85° | 0.1108 | 96.77% | 96.77% |
| Hybrid decoded | 0.038486 | 0.8264 | 25.49° | 0.1983 | 96.55% | 96.22% |
| Hybrid glb | 0.040334 | 0.8136 | 26.91° | 0.2247 | 96.81% | 96.68% |
| Pixal3D decoded | 0.028196 | 0.8935 | 22.01° | 0.1294 | 95.03% | 94.98% |
| Pixal3D glb | 0.028409 | 0.8904 | 22.71° | 0.1417 | 95.34% | 95.33% |

### 30 视角的资产级均值

| 方法 / 阶段 | 深度 MAE ↓ | IoU ↑ | 法线角误差 ↓ | 法线 LPIPS ↓ | 深度覆盖 ↑ | 法线覆盖 ↑ |
| --- | --- | --- | --- | --- | --- | --- |
| WT points | 0.041517 | 0.8455 | 27.47° | 0.1534 | 92.27% | 76.67% |
| TRELLIS.2 decoded | 0.021198 | 0.8953 | 19.78° | 0.0902 | 95.10% | 95.10% |
| TRELLIS.2 glb | 0.021259 | 0.8942 | 20.52° | 0.0991 | 95.45% | 95.45% |
| Hybrid decoded | 0.042322 | 0.8062 | 26.98° | 0.1666 | 94.98% | 94.60% |
| Hybrid glb | 0.044688 | 0.7951 | 27.96° | 0.1875 | 95.36% | 95.25% |
| Pixal3D decoded | 0.026981 | 0.8654 | 22.28° | 0.1119 | 93.20% | 93.18% |
| Pixal3D glb | 0.027085 | 0.8638 | 23.04° | 0.1214 | 93.54% | 93.54% |

WT−TRELLIS.2 decoded 的输入深度 MAE 差值为 +0.017672 [+0.011945, +0.023412]D。WT−Hybrid decoded 的对应差值为 -0.000202 [-0.003876, +0.003469]D，区间跨零。完整几何的排序需要结合每项渲染指标单独解读。[全部渲染指标、覆盖率和有效像素数](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/summary_seed42.json)

## Decoded 与 GLB 导出对照

阶段主表采用各自配准结果。下表另将同 seed 的 GLB 固定在 decoded 配准变换下计分，控制配准变化。Δ 为 GLB−decoded，所有比较 n=100。

| 方法 | 同变换完整 CD-L1 Δ [95% CI] | 同变换可见 CD-L1 Δ [95% CI] | 改善资产数，完整/可见 | 各自配准完整 CD-L1 Δ |
| --- | --- | --- | --- | --- |
| TRELLIS.2 | -0.000116 [-0.000144, -0.000085] | -0.000151 [-0.000193, -0.000109] | 80/81 | -0.000104 |
| Hybrid | +0.000246 [+0.000063, +0.000457] | +0.000162 [-0.000015, +0.000369] | 54/57 | +0.000302 |
| Pixal3D | -0.000132 [-0.000167, -0.000096] | -0.000218 [-0.000278, -0.000162] | 79/83 | -0.000106 |

TRELLIS.2 和 Pixal3D 的同变换完整、可见 CD-L1 平均改善。Hybrid 完整 CD-L1 的平均退化区间为正，可见 CD-L1 差值区间跨零。按各自配准结果，TRELLIS.2、Hybrid、Pixal3D 的输入法线角误差分别增加 0.82°、1.42°、0.70°，30 视角平均分别增加 0.74°、0.98°、0.76°。

当前 decoded PLY 对应解码并首次补洞后的网格，GLB 包含后续补洞、重网格化、简化与材质导出。两组结果分别用于检查解码阶段与最终导出资产。导出的 CD 改善幅度和法线变化共同纳入阶段比较。[解码产物保存位置](../wt/batch.py) · [导出流程](../wt/textured_mesh/pipeline.py)

面数与配准后累计三角形面积的统计如下。面积/GT 对全部三角面求和。

| 方法 | 面数中位数，百万，decoded→GLB | 面积/GT 均值 | 面积/GT 中位数 |
| --- | --- | --- | --- |
| TRELLIS.2 | 5.986 → 0.972 | 1.469 → 2.463 | 1.143 → 2.143 |
| Hybrid | 11.371 → 0.960 | 4.245 → 5.994 | 2.841 → 4.661 |
| Pixal3D | 5.752 → 0.977 | 1.293 → 2.166 | 1.204 → 2.078 |

## WT 原生坐标与尺度诊断

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

## 两个高面数 Hybrid 样本

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

## 复现变化与评测限制

本轮复用 A100 恢复输出。旧评测与 v0.5 的 400 组配准点、评价点逐数组完全一致，完整几何的变化来自配准初始化更新。v0.5 在主轴坐标下搜索 24 个旋转，旧版从原始坐标的 24 个旋转初始化。

| 方法，WT points / mesh decoded | 旧 A100 CD-L1 | v0.5 CD-L1 | 均值变化 | 单资产最大绝对变化 |
| --- | --- | --- | --- | --- |
| WT | 0.013285 | 0.013291 | +0.000006 | 0.002218 |
| TRELLIS.2 | 0.009297 | 0.009324 | +0.000027 | 0.001639 |
| Hybrid | 0.017753 | 0.017725 | -0.000028 | 0.001103 |
| Pixal3D | 0.011796 | 0.011770 | -0.000026 | 0.001455 |

PEEKABOO_ROLLER 的 WT、TRELLIS.2 CD-L1 分别增加 0.002218D、0.001639D，对应配准损失也升高，体现有限初始化 ICP 的局部最优影响。同一个冻结流程提供统一比较条件，输入语义面的对应关系仍受对称性和几何畸变影响。

### 校准

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

## 代码与产物

- 实现提交为 `57d0f1afa0c31a0c2334cbc00ebd61ce1191e82c`，提交说明为 `evaluation_protocol_v0.5`。评测 revision 为 `d99fa356cec4eb52fb27`。提交临时沿用仓库上一提交的作者身份。配准采用 8 个工作线程，在 P0 单资产对照中，4/8 线程的变换矩阵最大差值为 0。
- 完整回归测试 224/224 通过。700/700 阶段完成并校验，每项均保存输入视角和 30 个 multi-view 的数值数组。几何双向距离复算 CD-L1/L2、Precision、Recall、F-score，渲染深度、法线基础指标及像素数从 NPZ 复核。LPIPS 保留评测输出及文件摘要。
- 默认 PNG 仅保存 input-view，共 15,300 张，逐图校验通过。`--save-multiview-renders` 可额外保存 30 个 multi-view 的 PNG。GT 产物共享，同资产同视角统一色标。
- 本轮单 seed 汇总为 `summary_seed42.json`，700 项预算全部完成。原始八 seed 计划及其汇总继续保留，记录其余 4,900 项待运行。队列在 seed 42 完成后停止，运行状态与范围调整记录保存在任务日志中。
- 上一版协议内容 SHA-256 经复核为 `ad1570c68a2bcc85db03bfbf8e730ef46eda9b6903624b084a3927ac2474f1e1`，文件位于 `docs/archived/evaluation_protocol_v0.md`。

[单 seed 汇总](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/summary_seed42.json) · [渲染产物索引](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/baseline-v2/d99fa356cec4eb52fb27/20261110-R2-gso-quant-eval-v0.5/render_index.md) · [完整性校验](/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/baseline-v05-r2-20261110/seed42-audit.json)
