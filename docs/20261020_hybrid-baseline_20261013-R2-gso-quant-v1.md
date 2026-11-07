# R2：GSO 正式集定量与逐样本分析

> 2026-11-07 历史记录说明  
> 本文保留旧服务器实验的数值、分析和当时路径。新服务器已完成重跑并更新 experiments.xlsx，最新数值、差异和验收记录见 [恢复结果报告](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_recovery-results.md)。

分析日期：2026-10-20。范围仅为 **`20261013-R2-gso-quant-v1`：100 个固定 GSO 物体 × WT、TRELLIS.2、WT + TRELLIS.2 hybrid、Pixal3D，共 400 项**。每物体一个固定视图，推理 seed=42；P0、R1、参数扫描和其他 seed 不并入。沿用 [P0 分析](20261020_hybrid-baseline_20261013-P0-gso-pilot-v1.md) 的“汇总 → 关键现象 → 逐样本”结构。

**主要结论：**

- **完整形状均值：TRELLIS.2 > Pixal3D > WT > hybrid。** TRELLIS.2 在 57/100 个样本上取得最低 CD-L1，且中位数也最好。Pixal3D 对部分包装、掌机、布料的完整形状有明显收益，但存在几何破损、额外部件和图案浮雕；其均值优于 WT，不能据此认为二者差距在不同抽样下稳定。
- **当前 hybrid 没有稳定的形状增益。** 相对 TRELLIS.2，CD-L1 在 91/100 个物体上变差；相对 WT 在 72/100 个物体上变差。空腔、规则容器、分离部件和复杂纹理均有退化；也保留 OXO 开罐器、Jawbone 腕带等相对胜例。
- **输入方向、可见深度与完整形状应分开看。** WT/hybrid/Pixal3D 的原生展示方向在若干案例中更贴近输入；共同有效 81 个物体上，WT 的 SSI AbsRel 在 78 个上更好。Hybrid 的未配准相机 CD 却在 87/100 个上更低，说明这些指标衡量的对象不同，不能简化为单一“姿态优劣”。
- **文字/外观失败不能从几何成绩推导。** 高 F-score 的盒体和瓶体仍可能有错字、角色重绘、额外浮雕；WT layer-0 的颜色来自输入，不能把它作为生成纹理能力。本轮未计算 RGB/OCR 指标。

## 1. 定量汇总

### 1.1 完整形状：GT 辅助正 Sim(3)

四方法共同有效集合为全部 **100 个物体**，逐物体等权平均。距离单位为 GT 原资产包围盒对角线及其平方；F-score 以百分比显示。配准允许旋转、平移和正等比缩放，不允许镜像，**成绩不包含原生姿态/尺度误差**。计算定义见 [评估协议](evaluation_protocol.md)。

| 方法 | 有效 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | CD-L1 中位数 | CD-L1 标准差 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WT | 100/100 | 0.012963 | 0.000397708 | 59.27% | 96.40% | 0.010374 | 0.007851 |
| TRELLIS.2 | 100/100 | 0.009319 | 0.000205870 | 70.76% | 98.56% | 0.008642 | 0.004947 |
| Hybrid | 100/100 | 0.017255 | 0.000759948 | 45.36% | 91.97% | 0.016027 | 0.006348 |
| Pixal3D | 100/100 | 0.011763 | 0.000361585 | 64.27% | 97.18% | 0.010635 | 0.007682 |

CD-L1 逐样本最优数为 WT **15**、TRELLIS.2 **57**、hybrid **1**、Pixal3D **27**；F@0.01 的最优数为 **14 / 56 / 2 / 28**。同一物体的最低 CD 不一定对应最高 F-score。

| 配对比较 | 前者 CD-L1 更好的物体数 / 100 | 含义 |
| --- | ---: | --- |
| TRELLIS.2 vs WT | 77 | 原生网格在配准后完整形状上多数更好 |
| TRELLIS.2 vs hybrid | 91 | 当前结构注入未形成稳定收益 |
| TRELLIS.2 vs Pixal3D | 66 | Pixal3D 的收益集中在部分案例 |
| Pixal3D vs WT | 64 | 均值与多数胜例支持局部优势，仍有较重尾部错误 |
| WT vs hybrid | 72 | 上游点云经过完整 hybrid 流程后常退化 |

对 100 个物体做配对 bootstrap（10,000 次，PCG64 seed=20261020），CD-L1 均值差 `hybrid−TRELLIS.2` 为 **0.007936**，95% 百分位区间 **[0.006451, 0.009446]**；`Pixal3D−TRELLIS.2` 为 **0.002443 [0.001273, 0.003671]**；`Pixal3D−WT` 为 **−0.001201 [−0.002574, 0.000194]**。后者区间跨零，不能把当前均值第二/第三的差异表述成稳定的总体优势。区间仅反映这批资产的重抽样变化，不覆盖随机 seed、视图或训练分布不确定性。

### 1.2 可见深度与相机坐标

以下是各方法有效物体的均值；SSI 深度失败保留为空，不换物体、不记零。

| 方法 | 有效 | MAE ↓ | RMSE ↓ | AbsRel ↓ | δ1 ↑ | δ2 ↑ |
| --- | --- | --- | --- | --- | --- | --- |
| WT | 99/100 | 0.022027 | 0.030467 | 0.013296 | 0.999782 | 1.000000 |
| TRELLIS.2 | N/A | N/A | N/A | N/A | N/A | N/A |
| Hybrid | 82/100 | 0.047041 | 0.064773 | 0.028772 | 0.998223 | 1.000000 |
| Pixal3D | N/A | N/A | N/A | N/A | N/A | N/A |

WT/hybrid **共同有效 81 个物体**：

| 方法 | 有效 | MAE ↓ | RMSE ↓ | AbsRel ↓ | δ1 ↑ | δ2 ↑ |
| --- | --- | --- | --- | --- | --- | --- |
| WT | 81/100 | 0.021264 | 0.029171 | 0.012897 | 0.999831 | 1.000000 |
| Hybrid | 81/100 | 0.046131 | 0.063811 | 0.028187 | 0.998201 | 1.000000 |

WT 的 MAE/AbsRel 在共同集合的 **78/81** 个上更低，RMSE 在 **79/81** 个上更低。WT 深度失败 **1/100**，hybrid **18/100**；TRELLIS.2 和 Pixal3D 的相机/深度为 **N/A**，后者虽有 MoGe FoV，尚未建立原视图的完整尺度与位姿对应。失败名单见附录。

| 方法 | 有效 | 相机 CD-L1 ↓ | 相机 CD-L2 ↓ | 相机 F@0.01 ↑ | 相机 F@0.05 ↑ | 覆盖率 ↑ | 轮廓 IoU ↑ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WT | 100/100 | 0.107746 | 0.019202 | 6.94% | 28.12% | 99.39% | 98.79% |
| TRELLIS.2 | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| Hybrid | 100/100 | 0.083974 | 0.013521 | 10.56% | 38.22% | 96.58% | 53.67% |
| Pixal3D | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

相机 CD 保留位置、朝向、尺度和形状误差，**不是单独的旋转角误差**。WT 的深度直接读取像素索引处 L0 的 Z，mask 来自输入 alpha；hybrid 则将 mesh 恢复到相机框架后光栅化。WT 的高 IoU 因而不能证明独立分割或 XYZ 重投影精确；hybrid 高覆盖率与较低 IoU 并存，说明“覆盖到 GT”不等于“没有多余投影”。SSI 消除了深度尺度/偏移，δ1/δ2 在本数据上接近饱和，应优先联看 AbsRel、覆盖率、失败率和未配准指标。

### 1.3 与原论文 Table 1 对照

下表并列原文与本项目数值，**只作参考，不是同协议达标表**。WT-O* 对应 WT + TRELLIS.2 Stage 2；Pixal3D 在 WT Table 1 中未报告。[World Tracing，Table 1](https://arxiv.org/html/2606.13652v1#S4)

| 方法 | 来源 / 口径 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ |
| --- | --- | --- | --- | --- | --- |
| WT-O | 论文 Table 1 | 0.0213 | 0.00194 | 54.9% | 89.8% |
| WT | R2 实测，n=100 | 0.012963 | 0.000397708 | 59.27% | 96.40% |
| TRELLIS.2 | 论文 Table 1 | 0.0566 | 0.00717 | 20.4% | 59.8% |
| TRELLIS.2 | R2 实测，n=100 | 0.009319 | 0.000205870 | 70.76% | 98.56% |
| WT-O* (hybrid) | 论文 Table 1 | 0.0326 | 0.00530 | 32.1% | 80.8% |
| Hybrid | R2 实测，n=100 | 0.017255 | 0.000759948 | 45.36% | 91.97% |
| Pixal3D | 论文 Table 1 | 未报告 | 未报告 | 未报告 | 未报告 |
| Pixal3D | R2 实测，n=100 | 0.011763 | 0.000361585 | 64.27% | 97.18% |

| 方法 / 来源 | MAE ↓ | RMSE ↓ | AbsRel ↓ | δ1 ↑ | δ2 ↑ |
| --- | --- | --- | --- | --- | --- |
| WT-O / 论文 Table 1 | 0.0149 | 0.0243 | 0.0079 | 0.9996 | 0.9999 |
| WT / R2 有效 n=99 | 0.022027 | 0.030467 | 0.013296 | 0.999782 | 1.000000 |

论文 Table 1 未列 hybrid/Pixal3D 的深度分数；不以其他方法或本文结果代填。

论文评估 100 个 held-out 物体的全部渲染视图，随机生成方法采用 best-of-8；R2 是另行划分的 GSO 100 物体、单视图、seed=42。论文训练来源含 GSO，本 split 不能保证训练不重叠。公开描述不足以确认其形状配准、距离归一化和采样与这里相同。[原文 §4.1 / 附录 C](https://arxiv.org/html/2606.13652v1#A3)

论文三方法形状次序为 **WT > hybrid > TRELLIS.2**，本项目为 **TRELLIS.2 > WT > hybrid**。本次 TRELLIS.2/hybrid 的距离数值更小、F-score 更高，WT 的深度误差数值却更大；这些跨协议差异不能解释为“超越论文”或“复现失败百分比”。尤其本项目主表主动消除了姿态/尺度差异；是否与论文主表同样处理仍未确认。现阶段可靠结论是：**在本项目冻结协议下，默认 hybrid 的形状收益没有出现**，原因尚不能在数据、预处理、结构构造、生成与评价之间单独归因。

## 2. 定性结果如何解释定量

已逐一查看全部 100 个样本的配准后正面纹理与背面灰模；对方向歧义与重点缺陷补查 native、侧面、底面及 decoder PLY。完整逐样本表见附录 B，以下案例按问题选取，**不当作人工标注的全组失败率**。

| 现象 | 代表样本及数值证据 | 解释 |
| --- | --- | --- |
| TRELLIS.2 的完整布局优势 | #89 TABLEWARE：T CD-L1 0.006128；WT 0.035283、H 0.030531、P 0.027607 | 分离餐具的相对高度、杯碗体积和布局比输入纹理更能解释差距 |
| WT 的相对胜例 | #23 Epson、#34 HyperX、#35 Jawbone、#51 Netgear | 可见约束能保持薄盒比例、腕带开口关系；隐藏面仍常较平滑 |
| Pixal3D 的明显收益 | #02 Refrigerator：P 0.003099 vs T 0.017050；#61 Maraca：0.007051 vs 0.016630；#96 Wilton：0.002199 vs 0.009707 | 有些物体外形与纹理同时改善；不应只选失败例否定其条件信息 |
| 形状高分仍有虚假细节 | #15 CoQ10：P F@0.01 接近 100%，瓶壁却出现标签形浮雕 | 表面位移小于阈值时 F-score 几乎不受影响；不衡量文字是否准确 |
| Hybrid 空腔退化 | #17 Flower Pot、#78 Fabric Cube | 顶部近封口面/浅化内腔在 decoder PLY 已存在；不是只由查看器材质造成 |
| Pixal3D 复杂包装失真 | #29 Fresca：CD-L1 0.052063；#51 Netgear：0.014868 | 前者盒体压短并破损，后者出现印刷路由器对应的三维框架/细杆；两者在 decoder PLY 已存在 |
| 原生 TRELLIS 也会错误补全 | #41 Letter Holder：T CD-L1 0.010624 | GT 空槽被补成块状/书本状结构，即使它仍是本例 CD 最优 |
| Hybrid 的例外 | #54 OXO：H 0.015965 vs T 0.017442 | 全组唯一 hybrid CD 第一；旋钮/手柄局部仍不正确，不能等同于无误重建 |
| 几何与封面外观分离 | #67 Pokémon Dual Pack | T 距离最好，P 封面更可辨但有局部几何伪影，H 封面严重涂抹；WT 正面像输入，完整形状却是其最差案例 |

上表 W/T/H/P 分别表示 WT、TRELLIS.2、hybrid、Pixal3D。具体数值以附录逐样本表为准。

![Hybrid 布筐内腔：GT、decoder PLY、导出 GLB](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/stages/078-Hybrid.png)

图：#78 在导出前已存在近封口面和异常底部结构。此检查只把缺陷定位到 GLB 导出之前；decoder PLY 已含解码流程首次补洞，**不能据此断定一定由神经生成或某个体素操作造成**。

![Pixal3D 包装盒：GT、decoder PLY、导出 GLB](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/stages/051-Pixal3D.png)

图：#51 GT 是印刷包装盒，预测含外伸细杆和框架状结构；几何错误在 PLY 和 GLB 均可见。它与图案条件的关联是观察，未通过关闭条件的消融证明因果。

### 朝向和展示的核对

[原生朝向汇总 1](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/native-01.png) · [汇总 2](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/native-02.png) · [汇总 3](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/native-03.png)

`appearance.png` 第一行只居中、等比缩放，**不使用 GT 旋转**；后两行才使用保存的 Sim(3)。WT/hybrid 使用恢复的 RDF 方向；原生 TRELLIS.2 用标准 GLB 展示方向；Pixal3D 用上游投影相机方向。这里不是相同标定相机下的重投影误差。

Pixal3D 的 `decoded_to_glb=diag(-1,1,-1)` 会改变默认展示正面。本次最初采用通用 GLB 正视，复核后按上游 `proj_camera_to_render_params` 的 source +Z / up +Y 修正了 **100 张分析预览**，并撤销导出旋转；未改变实验 GLB、配准或指标。不能从旧的背面/底部预览得出 Pixal3D 姿态失败。盒体/瓶体的纯几何 Sim(3) 仍可能选到其他语义面，如 #31、#50、#56、#85、#88。

#25 F5、#27 FYW_ALTERNATION、#81 SPEED_BOAT 的 WT/hybrid/Pixal3D 原生展示方向接近输入，其中 WT/hybrid 在保存几何配准后可能呈鞋底/上下错置，说明 ICP 与几何畸变、对称性之间存在交互。形状分数是冻结配准流程的输出，不能宣称绝对最优语义配准；此次没有为个别案例手调配准或替换分数。

### 可以归因到哪里

- 默认 WT 是灰底 128、不腐蚀；hybrid 的 WT 上游为黑底 0、腐蚀 2 px。R2 没有 shared-WT，不能把差异全归于 Stage 2。P0 的 shared-WT 是另一批数据的补充证据，不并入 R2。
- 邻层插值、32³ 量化和 closing 可能损伤空腔/细结构，但本轮没有逐操作消融。形状/纹理 latent、解码补洞和导出也可能贡献错误。
- Pixal3D 使用独立训练权重、MoGe2 和投影特征条件，T vs P 并非只改变一个 conditioning 模块。不能把每个改善或浮雕缺陷直接归因于 pixel-aligned conditioning。
- WT 隐藏面“更平滑/细节弱”是渲染观察；一像素点绘制也会造成稀疏孔隙。本轮没有把屏幕孔隙计为表面拓扑孔洞，也未计算占据体积错误率。

后续优先在已有 P0 或独立诊断样本上做受控消融：先固定同一 WT 预测和图像条件，再分离插值/closing、首次补洞与导出；对包装图案→几何的案例做条件消融。正式 R2 保留现有冻结基线，参数选择不以这 100 个物体逐项调优。

## 附录 A：配置、协议与复现

| 方法 | 本轮实际配置 |
| --- | --- |
| WT / `defaults-v1` | object 6-layer，504²，20 步；灰底 [128,128,128]，alpha_erode=0；`predict_color=false` |
| TRELLIS.2 / `defaults-v1` | 独立 Stage 1；1024_cascade，shape/texture 各 12 步，max_num_tokens=49152，4096² 纹理、目标面数 1,000,000 |
| Hybrid / `defaults-v1` | 独立 WT 20 步、黑底 [0,0,0]、alpha_erode=2，ray_steps=4；其余 TRELLIS Stage 2 配置同上 |
| Pixal3D / `resolution1024-v1` | main TRELLIS 版本；1024_cascade、low_vram=true；SS/shape/texture 各 12 步，guidance 7.5/7.5/1，rescale 0.7/0.5/0，rescale_t 5/3/3，interval [0.6,1]/[0.6,1]/[0.6,0.9]；max_num_tokens=49152、4096²、目标面数 1,000,000；remesh=true/band=1/project=0；MoGe2 512，mesh_scale=1，extend_pixel=0 |

每项推理 seed=42、batch=1；Python/NumPy/Torch/CUDA 在 pipeline 入口重置，相同整数不代表跨模型相同 latent。数据划分 PCG64(20261013)，1030 个资产固定打乱为 10/100/920；视图、配准采样与评价采样按用途和资产 ID 派生独立 seed。未取 best-of-N。通用配置中的 `wt_steps`、`alpha_erode`、`ray_steps` 不参与原生 TRELLIS 执行，不把这些占位字段当有效参数。

四方法各自 100 项的 `parameters` 完全一致；因 GPU、来源/运行恢复信息等不同，配置摘要可不同。Pixal3D 本轮保存的源码提交为 **`f7cf38429b0bd264f1995f0f8743a88b1c728b94`**；每项 `config.json` 保存权重 manifest、adapter 源码与环境摘要。WT/TRELLIS/hybrid 使用 `world_tracing`，Pixal3D 推理使用独立 `world_tracing_pixal3d`；均为 PyTorch 2.6.0+cu124 / NumPy 1.26.4。2 项曾触发 OOM 的 hybrid 通过分块与显存管理恢复完成，原参数/seed 不变；实际额外源码与策略保存在各自配置中，不另计样本或新 seed。

**形状协议简述。** GT 原资产 AABB 对角线=1；24 个 proper rotation 初始化、最多 100 次 Sim(3) ICP；配准 10,000 点、评价 100,000 点。CD-L1 是双向最近邻欧氏距离均值的平均，CD-L2 为平方距离均值的平均，均含 1/2；F 阈值 0.01/0.05。WT 全层有效点去重抽样，mesh 按面积抽样，采样密度的表示差异保留。最终评价读取 `decoded_mesh.ply`，不是 GLB。完整公式、深度质量门槛与 N/A 规则见 [评估协议](evaluation_protocol.md)。

**图像协议。** GT 使用原资产纹理，预测 mesh 使用各自生成的纹理，均以单位环境光显示底色；mesh 灰模去掉材质后按法线照明，WT 无色点图按深度着色。使用全部 GLB 面、全部 WT 有效点；WT 纹理视图只给 L0 输入 RGB，其余层灰色。默认诊断 640²，GT 正视另按原 1024² 精确复渲染，100/100 与冻结 input 像素一致。正面、侧面（方位+90°）、背面（+180°）及下视（俯仰−60°）均不改变源产物。

**本次核验。** 400 项 run/评价状态完成；在保存的评价点与配准矩阵上重算全部 1,600 个形状值，绝对误差均 ≤1e−10。旧三方法与 Pixal3D 的 evaluator 摘要不同，是新增方法路由/N/A 的扩展；形状公式文件与 R2 冻结源码 SHA-256 一致。未重新优化 ICP，未声称已对所有像素深度数值重复计算。标准差使用样本标准差 ddof=1，与工作簿批注的总体标准差 ddof=0 区分。

**SSI 深度失败（形状仍有效）：**

| 方法 | 资产 | 保存的失败原因 | 覆盖率 |
| --- | --- | --- | --- |
| WT | #074 `Razer_Taipan_White_Ambidextrous_Gaming_Mouse` | 拟合秩不足或尺度非正 | 99.13% |
| Hybrid | #010 `BALANCING_CACTUS` | 覆盖率 <95% | 70.34% |
| Hybrid | #018 `Craftsman_Grip_Screwdriver_Phillips_Cushion` | 覆盖率 <95% | 35.70% |
| Hybrid | #020 `DOLL_FAMILY` | 覆盖率 <95% | 92.79% |
| Hybrid | #021 `Ecoforms_Plant_Container_Urn_55_Mocha` | 拟合秩不足或尺度非正 | 100.00% |
| Hybrid | #022 `Ecoforms_Planter_Pot_GP12AAvocado` | 拟合秩不足或尺度非正 | 100.00% |
| Hybrid | #035 `Jawbone_UP24_Wireless_Activity_Tracker_Pink_Coral_L` | 覆盖率 <95% | 85.04% |
| Hybrid | #038 `MOVING_MOUSE_PW_6PCSSET` | 覆盖率 <95% | 84.42% |
| Hybrid | #039 `MY_MOOD_MEMO` | 覆盖率 <95% | 80.33% |
| Hybrid | #065 `Playmates_nickelodeon_teenage_mutant_ninja_turtles_shredder` | 覆盖率 <95% | 87.51% |
| Hybrid | #071 `ROAD_CONSTRUCTION_SET` | 覆盖率 <95% | 85.68% |
| Hybrid | #072 `Razer_BlackWidow_Stealth_2014_Keyboard_07VFzIVabgh` | 覆盖率 <95% | 83.52% |
| Hybrid | #073 `Razer_BlackWidow_Ultimate_2014_Mechanical_Gaming_Keyboard` | 覆盖率 <95% | 93.72% |
| Hybrid | #084 `Simon_Swipe_Game` | 覆盖率 <95% | 87.49% |
| Hybrid | #086 `SpiderMan_Titan_Hero_12Inch_Action_Figure_oo1qph4wwiW` | 覆盖率 <95% | 91.34% |
| Hybrid | #089 `TABLEWARE_SET_5CHkPjjxVpp` | 覆盖率 <95% | 65.80% |
| Hybrid | #090 `TABLEWARE_SET_5ww1UFLuCJG` | 覆盖率 <95% | 78.63% |
| Hybrid | #093 `Thomas_Friends_Wooden_Railway_Deluxe_Track_Accessory_Pack` | 覆盖率 <95% | 83.34% |
| Hybrid | #096 `Wilton_PreCut_Parchment_Sheets_10_x_15_24_sheets` | 覆盖率 <95% | 93.73% |

Hybrid 的 18 项中，16 项因覆盖率不足、2 项因尺度拟合无效；WT 的 1 项因尺度拟合无效。覆盖率与 IoU 仍保留有效值。

**文件位置：**

- [R2 正式输出](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R2-gso-quant-v1)：`samples/<asset>/<method>/<config>/seed-0042/` 中保存 `run/config/metrics/registration.json`、采样点及模型产物。
- [完整审计](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/audit.json)、[逐样本 TSV](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/per_sample.tsv)、[bootstrap](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/bootstrap.json)、[GT 渲染核验](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/render_validation.json)、[最终核验](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/validation.json)。
- [分析证据目录](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020)：每样本 `appearance.png` / `geometry.png`；`review-01.jpg` 至 `review-25.jpg` 为全量审阅页；`stages/` 为六项导出前后比较。
- [复现脚本与人工观察](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/reproduction)：在专用 screen、`world_tracing` 环境并 source `scripts/env.sh` 后运行。`r2_analysis_20261020.py audit` 复算指标；`render --shard <0到3>` 生成四个分片。各分片完成后运行 `r2_pixal_view_20261020.py --shard <0到3>` 修正投影方向；`r2_stats_20261020.py` 重建统计，`r2_review_cards_20261020.py` 重建审阅页，`r2_details_20261020.py` 生成六例阶段对照及 native 汇总。后者应在方向修正后执行；`r2_finish_inspect_20261020.py` 可单独刷新 native 汇总。最后 `r2_finalize_20261020.py` 从人工观察和数值生成本文，`r2_validate_20261020.py` 核验来源、链接与工作簿。原 P0 helper 只复用读取/渲染函数。
- [experiments.xlsx](/data1/LiuShuqi/code/world_tracing/experiments.xlsx) 已有 R2 四方法定量记录。本次逐项核对工作簿 R2 记录与原始指标一致，不改成绩、不覆盖人工工作簿内容；论文数值单列于本文，不混入本项目实测统计。

## 附录 B：全部 100 个样本

按资产 ID 排序编号，非质量排序。各表形状有效数均为每方法 1/1；CD 越低、F 越高越好，AbsRel 为该样本 SSI 值。`失败` 与 `N/A` 分开；逐样本排序按未舍入 CD-L1。数值展示舍入可能掩盖极小差异。每项提供原图/原生朝向/配准纹理和多视角灰模链接；观察只描述已检查视角，未断言所有隐藏表面或拓扑均已验收。

### 001. 2_of_Jenga_Classic_Game

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.012160 | 0.000344102 | 60.71% | 96.34% | 0.004977 |
| TRELLIS.2 | 0.007331 | 0.000096126 | 77.50% | 99.72% | N/A |
| Hybrid | 0.015760 | 0.000579283 | 47.63% | 91.47% | 0.020945 |
| Pixal3D | 0.013811 | 0.000477040 | 58.22% | 93.58% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

GT 的积木层缝与缺口明确；TRELLIS.2 保留较连续的层间结构。Hybrid 把部分层缝与凹凸抹平，Pixal3D 虽呈现更多块状纹理，但块形和突出位置仍偏离 GT；WT 隐藏面的分层细节较弱。配准后部分 WT 可见面呈灰色，不能据此判为纹理丢失。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/2_of_Jenga_Classic_Game/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/2_of_Jenga_Classic_Game/geometry.png)

### 002. 3D_Dollhouse_Refrigerator

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.007652 | 0.000102659 | 78.43% | 100.00% | 0.003813 |
| TRELLIS.2 | 0.017050 | 0.000778425 | 55.07% | 90.71% | N/A |
| Hybrid | 0.014200 | 0.000448380 | 51.89% | 97.02% | 0.021658 |
| Pixal3D | 0.003099 | 0.000019033 | 98.15% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < WT < Hybrid < TRELLIS.2**；F@0.01 最高：**Pixal3D**。

这是 Pixal3D 优势很明显的反例：其整体长方体比例最接近 GT。TRELLIS.2 将平整一侧生成了开放式多层架；背面灰模显示 GT 的门板/把手起伏在各预测中均有不同程度简化。WT 保住大体体积，Hybrid 边缘更圆、局部比例有偏差；Pixal3D 高分也不代表门板细节完全恢复。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/3D_Dollhouse_Refrigerator/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/3D_Dollhouse_Refrigerator/geometry.png)

### 003. 3M_Antislip_Surfacing_Light_Duty_White

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.006176 | 0.000066655 | 88.73% | 99.87% | 0.005637 |
| TRELLIS.2 | 0.003977 | 0.000020440 | 98.61% | 100.00% | N/A |
| Hybrid | 0.015163 | 0.000422541 | 42.68% | 96.21% | 0.040287 |
| Pixal3D | 0.008216 | 0.000210996 | 75.31% | 97.91% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 的圆环、孔径及厚度最接近 GT。Hybrid 环体更厚、表面较粗糙；Pixal3D 多出外伸片状结构，WT 保留环形但内部点分布较散。此例显示细小附加结构也可能拉低形状分数。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/3M_Antislip_Surfacing_Light_Duty_White/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/3M_Antislip_Surfacing_Light_Duty_White/geometry.png)

### 004. 60_CONSTRUCTION_SET

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.029380 | 0.001639560 | 29.11% | 79.35% | 0.059405 |
| TRELLIS.2 | 0.014882 | 0.000403449 | 47.06% | 97.31% | N/A |
| Hybrid | 0.028276 | 0.001588451 | 30.05% | 78.77% | 0.091240 |
| Pixal3D | 0.023044 | 0.000960691 | 31.89% | 89.32% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

复杂拼装件的孔洞、支杆和前后层次很难同时恢复。TRELLIS.2 最接近整体布局；WT 背侧集中成较模糊的点块，Hybrid 的组件方向和连接明显改变，Pixal3D 保留彩色部件但背侧连接及层次仍有偏差。四方法均未达到简单盒状物体的质量。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/60_CONSTRUCTION_SET/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/60_CONSTRUCTION_SET/geometry.png)

### 005. ASICS_GEL1140V_WhiteBlackSilver

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.012082 | 0.000258236 | 53.11% | 98.97% | 0.018270 |
| TRELLIS.2 | 0.009409 | 0.000194934 | 68.84% | 98.58% | N/A |
| Hybrid | 0.013645 | 0.000363487 | 47.19% | 96.77% | 0.026599 |
| Pixal3D | 0.010192 | 0.000191243 | 60.59% | 99.01% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

四者均保留运动鞋的大轮廓。TRELLIS.2 的鞋头、后跟和鞋面结构较稳定；Hybrid 鞋头更宽钝、局部花纹与鞋带简化，Pixal3D 接近但后跟细节不同。WT 的背面鞋面和鞋底纹理起伏较平滑；其输入颜色不代表新视角纹理预测。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/ASICS_GEL1140V_WhiteBlackSilver/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/ASICS_GEL1140V_WhiteBlackSilver/geometry.png)

### 006. ASICS_GELAce_Pro_Pearl_WhitePink

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.012864 | 0.000275976 | 48.49% | 98.67% | 0.017326 |
| TRELLIS.2 | 0.011451 | 0.000251757 | 57.93% | 98.08% | N/A |
| Hybrid | 0.011461 | 0.000218853 | 53.17% | 99.45% | 0.028629 |
| Pixal3D | 0.010961 | 0.000220101 | 57.57% | 98.75% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

三个网格方法都形成合理鞋形，Pixal3D 的 CD-L1 小幅占优，TRELLIS.2 的 F@0.01 略高，不能概括成 Pixal3D 全面胜出。三者后跟/鞋底的块状结构均与 GT 有差异；WT 背部细节更平滑。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/ASICS_GELAce_Pro_Pearl_WhitePink/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/ASICS_GELAce_Pro_Pearl_WhitePink/geometry.png)

### 007. ASICS_GELTour_Lyte_WhiteOrchidSilver

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.018902 | 0.000607555 | 36.67% | 94.42% | 0.016100 |
| TRELLIS.2 | 0.010566 | 0.000210244 | 61.96% | 98.90% | N/A |
| Hybrid | 0.016088 | 0.000518067 | 42.47% | 94.32% | 0.038018 |
| Pixal3D | 0.014715 | 0.000345753 | 42.86% | 98.72% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

正面颜色和鞋带看似接近，但背侧灰模揭示 WT 的后跟/鞋帮简化，Hybrid 后跟偏宽，Pixal3D 后跟轮廓也发生改变。TRELLIS.2 整体形状更稳定；正面可辨认并不等于完整鞋体准确。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/ASICS_GELTour_Lyte_WhiteOrchidSilver/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/ASICS_GELTour_Lyte_WhiteOrchidSilver/geometry.png)

### 008. Android_Figure_Panda

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.010611 | 0.000371794 | 68.76% | 97.03% | 0.005984 |
| TRELLIS.2 | 0.006942 | 0.000280938 | 92.29% | 97.65% | N/A |
| Hybrid | 0.025350 | 0.001650014 | 26.81% | 82.35% | 0.022791 |
| Pixal3D | 0.004336 | 0.000050891 | 95.59% | 99.69% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 的熊猫脸、身高及肢体比例最接近 GT。TRELLIS.2 大形状好，但脸部及腹部图案出现涂抹；Hybrid 头部/躯干比例和连接更明显失真。WT 保留输入图案，背部为较平滑的点云表面。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Android_Figure_Panda/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Android_Figure_Panda/geometry.png)

### 009. BAGEL_WITH_CHEESE

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.017889 | 0.000536165 | 35.95% | 96.60% | 0.012760 |
| TRELLIS.2 | 0.009626 | 0.000175613 | 68.19% | 99.52% | N/A |
| Hybrid | 0.014589 | 0.000375714 | 43.73% | 97.89% | 0.034454 |
| Pixal3D | 0.011971 | 0.000278264 | 57.91% | 98.56% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

食物玩具组合的颜色仍可辨认，但各部件空间层次不同。TRELLIS.2 最接近盘子与食物的整体关系；Hybrid 局部堆叠被简化，Pixal3D 背侧出现部件位置/伸出方向偏差，WT 背部层次不够清楚。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/BAGEL_WITH_CHEESE/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/BAGEL_WITH_CHEESE/geometry.png)

### 010. BALANCING_CACTUS

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.016480 | 0.000575440 | 45.90% | 93.81% | 0.016867 |
| TRELLIS.2 | 0.009335 | 0.000168180 | 67.20% | 99.36% | N/A |
| Hybrid | 0.016799 | 0.000567734 | 45.04% | 94.18% | 失败 |
| Pixal3D | 0.018945 | 0.000795928 | 43.00% | 94.42% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Hybrid < Pixal3D**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好保持仙人掌分枝数量与布局。Hybrid 若干枝端变为不规则团块，Pixal3D 在右侧细枝处出现碎片/不连续外观；WT 分枝较薄、背侧缺乏体积细节。这里不能用彩色正面接近掩盖背侧结构错误。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/BALANCING_CACTUS/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/BALANCING_CACTUS/geometry.png)

### 011. BlueBlack_Nintendo_3DSXL

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.010018 | 0.000171154 | 60.08% | 99.18% | 0.004488 |
| TRELLIS.2 | 0.006983 | 0.000070487 | 77.91% | 100.00% | N/A |
| Hybrid | 0.010340 | 0.000171509 | 56.68% | 99.80% | 0.011012 |
| Pixal3D | 0.005900 | 0.000043309 | 91.61% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 较好保留双屏折角、外壳比例和整体轮廓；TRELLIS.2 也较完整。Hybrid 的按键/屏幕位置和外壳局部结构出现变化，背面有额外起伏；WT 背板更平。屏幕色块不等于屏幕内容已准确恢复。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/BlueBlack_Nintendo_3DSXL/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/BlueBlack_Nintendo_3DSXL/geometry.png)

### 012. CLIMACOOL_BOAT_BREEZE_IE6CyqSaDwN

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009633 | 0.000165560 | 64.76% | 99.65% | 0.010230 |
| TRELLIS.2 | 0.009597 | 0.000167789 | 66.77% | 99.55% | N/A |
| Hybrid | 0.014036 | 0.000387266 | 50.10% | 96.04% | 0.022457 |
| Pixal3D | 0.008429 | 0.000123850 | 69.72% | 99.84% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 的鞋身比例与后侧结构较接近 GT；WT 与 TRELLIS.2 的 CD-L1 很接近。Hybrid 鞋口及后跟变形、黑色区域扩大。网格方法恢复了更多鞋面起伏，但这些起伏仍须以 GT 为准，不能仅按细节数量判断质量。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/CLIMACOOL_BOAT_BREEZE_IE6CyqSaDwN/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/CLIMACOOL_BOAT_BREEZE_IE6CyqSaDwN/geometry.png)

### 013. Canon_Ink_Cartridge_Green_6

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.005424 | 0.000040135 | 90.82% | 100.00% | 0.004539 |
| TRELLIS.2 | 0.007065 | 0.000059355 | 79.84% | 100.00% | N/A |
| Hybrid | 0.015663 | 0.000665141 | 53.67% | 90.37% | 0.005189 |
| Pixal3D | 0.003948 | 0.000021058 | 98.25% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < WT < TRELLIS.2 < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 与 WT 保留包装盒和高背卡的比例较好，TRELLIS.2 也形成完整盒体。Hybrid 在盒顶到背卡间增加了斜面过渡，标签大面积涂抹；其余生成结果的品牌文字同样不能视为准确 OCR 复现。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Canon_Ink_Cartridge_Green_6/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Canon_Ink_Cartridge_Green_6/geometry.png)

### 014. Circo_Fish_Toothbrush_Holder_14995988

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.013222 | 0.000309758 | 48.91% | 98.06% | 0.010055 |
| TRELLIS.2 | 0.011055 | 0.000213363 | 58.49% | 98.86% | N/A |
| Hybrid | 0.018953 | 0.000843107 | 40.41% | 90.54% | 0.043383 |
| Pixal3D | 0.012307 | 0.000278334 | 53.19% | 98.30% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

实际呈龟形容器：TRELLIS.2 和 Pixal3D 保留开口、壳上分区及足部较好。Hybrid 壳体凹凸、足部比例和开口边界失真；WT 隐藏面更平滑、壳纹较少。这里只按实际 GT 外观分析，不从资产名称推断形状。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Circo_Fish_Toothbrush_Holder_14995988/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Circo_Fish_Toothbrush_Holder_14995988/geometry.png)

### 015. CoQ10

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.005205 | 0.000038325 | 89.56% | 100.00% | 0.002994 |
| TRELLIS.2 | 0.003763 | 0.000018597 | 97.89% | 100.00% | N/A |
| Hybrid | 0.029805 | 0.002088055 | 20.79% | 73.60% | 0.017584 |
| Pixal3D | 0.002925 | 0.000010731 | 99.99% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

TRELLIS.2 / Pixal3D 的瓶体接近 GT，但灰模可见标签附近的额外浅浮雕；Pixal3D 的这一缺陷在 decoder PLY 中已存在。其 F@0.01=99.993% 不能证明表面或文字完全正确。修正观察方向后的 native 图中，Pixal3D 标签比 TRELLIS.2 / Hybrid 更接近输入；Hybrid 瓶身明显变粗/变形并产生密集凹凸。瓶体纯几何配准后的标签转向不等于原生姿态失败。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/CoQ10/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/CoQ10/geometry.png) · [decoder PLY / GLB 对照](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/stages/015-Pixal3D.png)

### 016. Cole_Hardware_Dishtowel_Stripe

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.007155 | 0.000083432 | 74.20% | 100.00% | 0.018239 |
| TRELLIS.2 | 0.006691 | 0.000070892 | 80.45% | 100.00% | N/A |
| Hybrid | 0.008589 | 0.000105717 | 63.89% | 100.00% | 0.014416 |
| Pixal3D | 0.006030 | 0.000055119 | 86.45% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 较好保留折叠外形和条纹质感。TRELLIS.2 形成较规则的折面；Hybrid 的褶皱更大、条带变宽，WT 背侧更像薄片，折叠层次减少。布面细小起伏是否忠实仍不能由条纹清晰度单独判断。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Cole_Hardware_Dishtowel_Stripe/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Cole_Hardware_Dishtowel_Stripe/geometry.png)

### 017. Cole_Hardware_Flower_Pot_1025

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009262 | 0.000121941 | 62.23% | 100.00% | 0.004860 |
| TRELLIS.2 | 0.003149 | 0.000012892 | 99.15% | 100.00% | N/A |
| Hybrid | 0.023909 | 0.001527980 | 36.50% | 86.45% | 0.075383 |
| Pixal3D | 0.005758 | 0.000048570 | 88.78% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 的花盆外壁和开口最接近 GT，Pixal3D 也保留内凹外观。Hybrid 盆口附近出现近封口的粗糙表面，底部未恢复 GT 排水孔；两点在 decoder PLY 与 GLB 中均可见。WT 内壁和背部细节较弱。此检查支持开口/内腔失真，未计算内部占据体积，也不能分离神经生成与首次补洞的贡献。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Cole_Hardware_Flower_Pot_1025/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Cole_Hardware_Flower_Pot_1025/geometry.png) · [decoder PLY / GLB 对照](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/stages/017-Hybrid.png)

### 018. Craftsman_Grip_Screwdriver_Phillips_Cushion

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.012932 | 0.000308072 | 51.93% | 98.77% | 0.014827 |
| TRELLIS.2 | 0.008646 | 0.000125136 | 69.99% | 99.36% | N/A |
| Hybrid | 0.015131 | 0.000406899 | 44.46% | 98.83% | 失败 |
| Pixal3D | 0.020125 | 0.000629475 | 31.02% | 98.24% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Hybrid < Pixal3D**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 的螺丝刀杆身和握柄比例较接近 GT。WT 握柄更圆，Hybrid 握柄与末端形状偏离；Pixal3D 握柄膨大、可见杆身偏短且有不规则折变，不能因为工具类别正确就认为几何正确。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Craftsman_Grip_Screwdriver_Phillips_Cushion/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Craftsman_Grip_Screwdriver_Phillips_Cushion/geometry.png)

### 019. DIM_CDG

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.005653 | 0.000056561 | 87.39% | 99.88% | 0.002999 |
| TRELLIS.2 | 0.002754 | 0.000009546 | 99.97% | 100.00% | N/A |
| Hybrid | 0.028460 | 0.001876897 | 19.57% | 82.08% | 0.016235 |
| Pixal3D | 0.003064 | 0.000012711 | 98.66% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 / Pixal3D 的瓶体轮廓明显优于 Hybrid；后者在瓶侧产生碎屑状边缘和不规则表面。两种较好网格仍把部分印刷内容变成灰模起伏。WT 保持基本体积；对称瓶体上的标签转向须与几何配准歧义区分。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/DIM_CDG/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/DIM_CDG/geometry.png)

### 020. DOLL_FAMILY

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.011896 | 0.000279023 | 56.37% | 98.42% | 0.018212 |
| TRELLIS.2 | 0.013852 | 0.000302354 | 43.36% | 99.27% | N/A |
| Hybrid | 0.013309 | 0.000330160 | 52.01% | 97.95% | 失败 |
| Pixal3D | 0.013200 | 0.000290862 | 49.11% | 99.15% | N/A |

CD-L1 从低到高：**WT < Pixal3D < Hybrid < TRELLIS.2**；F@0.01 最高：**WT**。

WT 在四人偶组合的整体位置关系上得到本例最低 CD-L1，但背侧点云缺乏面部和服装细节。三个生成网格补出连续人偶，手臂关系、头部和衣着细节均有不同程度变化；更完整的脸部不等于忠实恢复。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/DOLL_FAMILY/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/DOLL_FAMILY/geometry.png)

### 021. Ecoforms_Plant_Container_Urn_55_Mocha

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.008022 | 0.000122410 | 71.37% | 99.54% | 0.006541 |
| TRELLIS.2 | 0.003180 | 0.000012591 | 99.58% | 100.00% | N/A |
| Hybrid | 0.019728 | 0.001455220 | 52.09% | 91.02% | 失败 |
| Pixal3D | 0.004387 | 0.000023951 | 98.89% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 和 Pixal3D 都接近 GT 的杯状外形与开口；Hybrid 杯身比例及内口附近几何较不规则。WT 保持轮廓但隐藏面平滑。深色内腔的颜色差异不能直接换算为几何深度差。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Ecoforms_Plant_Container_Urn_55_Mocha/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Ecoforms_Plant_Container_Urn_55_Mocha/geometry.png)

### 022. Ecoforms_Planter_Pot_GP12AAvocado

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.007724 | 0.000097289 | 74.65% | 99.92% | 0.004635 |
| TRELLIS.2 | 0.004017 | 0.000023062 | 97.33% | 100.00% | N/A |
| Hybrid | 0.020932 | 0.001167380 | 39.08% | 87.29% | 失败 |
| Pixal3D | 0.005368 | 0.000042700 | 87.87% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好保持盆沿、锥度及底部凹口；Pixal3D 也较接近，但底部细节简化。Hybrid 内口出现不规则突起，外壁/底部形状改变；WT 内外表面较平滑。此例与花盆 #17 共同提示 hybrid 对空腔结构仍不稳定。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Ecoforms_Planter_Pot_GP12AAvocado/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Ecoforms_Planter_Pot_GP12AAvocado/geometry.png)

### 023. Epson_Ink_Cartridge_126_Yellow

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.008233 | 0.000116831 | 71.64% | 99.99% | 0.005017 |
| TRELLIS.2 | 0.029284 | 0.001220187 | 20.21% | 80.42% | N/A |
| Hybrid | 0.018102 | 0.000552657 | 30.09% | 93.30% | 0.005183 |
| Pixal3D | 0.029278 | 0.001566103 | 27.81% | 82.25% | N/A |

CD-L1 从低到高：**WT < Hybrid < Pixal3D < TRELLIS.2**；F@0.01 最高：**WT**。

WT 最好保持薄包装及其背侧凸出盒体。TRELLIS.2 把背部明显压平，Pixal3D 背侧出现不应有的折皱/凹面；Hybrid 相对保留厚度，但边界和标签仍失真。生成标签虽可辨认品牌样式，却均有错字和涂抹。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Epson_Ink_Cartridge_126_Yellow/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Epson_Ink_Cartridge_126_Yellow/geometry.png)

### 024. F10_TRX_TF_rH7tmKCdUJq

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009187 | 0.000151021 | 66.75% | 99.72% | 0.013759 |
| TRELLIS.2 | 0.010529 | 0.000207628 | 61.13% | 99.13% | N/A |
| Hybrid | 0.013463 | 0.000371326 | 52.72% | 96.13% | 0.017220 |
| Pixal3D | 0.010611 | 0.000208869 | 59.72% | 98.54% | N/A |

CD-L1 从低到高：**WT < TRELLIS.2 < Pixal3D < Hybrid**；F@0.01 最高：**WT**。

WT 的整体鞋形误差最低，是原生 TRELLIS.2 并非逐例占优的反例。三个生成结果均形成完整鞋体，但鞋头、鞋底比例和侧面条纹位置有所改变。WT 隐藏面的细节仍弱于连续网格。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/F10_TRX_TF_rH7tmKCdUJq/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/F10_TRX_TF_rH7tmKCdUJq/geometry.png)

### 025. F5_TRX_FG

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.029219 | 0.001524377 | 24.35% | 81.02% | 0.031141 |
| TRELLIS.2 | 0.016561 | 0.000497175 | 41.96% | 95.43% | N/A |
| Hybrid | 0.023190 | 0.001090230 | 31.55% | 85.75% | 0.041569 |
| Pixal3D | 0.019344 | 0.000561744 | 29.99% | 97.70% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 的形状成绩相对最好，但四者严格 F-score 都不高。WT 后侧轮廓与鞋帮偏离；Hybrid 保存配准后呈鞋底朝向，纯几何匹配未恢复语义方向。native 复查中 WT、Hybrid、Pixal3D 均保持输入的鞋头朝前方向，TRELLIS.2 则展示侧面。Pixal3D 有鞋带和鞋口，但后跟形状仍错；该显示比较不等于标定相机下的姿态角评价。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/F5_TRX_FG/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/F5_TRX_FG/geometry.png)

### 026. FIRE_TRUCK

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009885 | 0.000146261 | 59.72% | 99.77% | 0.004836 |
| TRELLIS.2 | 0.009065 | 0.000127415 | 64.83% | 100.00% | N/A |
| Hybrid | 0.010889 | 0.000206087 | 55.54% | 99.67% | 0.021641 |
| Pixal3D | 0.011073 | 0.000180700 | 52.68% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Hybrid < Pixal3D**；F@0.01 最高：**TRELLIS.2**。

各方法保留消防车玩具的大结构，TRELLIS.2 略占优。生成结果的驾驶员五官及车身文字均发生变化；Hybrid 灰模车身出现多余粗糙起伏，Pixal3D 的轮子和角色比例有偏差，WT 后侧细节简化。几何接近与文字忠实是两件事。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/FIRE_TRUCK/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/FIRE_TRUCK/geometry.png)

### 027. FYW_ALTERNATION

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.025408 | 0.001104759 | 28.89% | 85.82% | 0.016287 |
| TRELLIS.2 | 0.009864 | 0.000190045 | 66.57% | 99.30% | N/A |
| Hybrid | 0.021799 | 0.000899508 | 31.93% | 87.31% | 0.031617 |
| Pixal3D | 0.011914 | 0.000261310 | 58.10% | 98.95% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 / Pixal3D 较好保持高帮鞋、鞋舌和鞋口；WT 背侧体积严重简化。Hybrid 配准后足底/鞋面方向错置、灰模后侧呈圆钝端面；native 中 WT、Hybrid、Pixal3D 均接近输入正面，而 TRELLIS.2 展示鞋侧。几何匹配失败与原生朝向须分开判断。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/FYW_ALTERNATION/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/FYW_ALTERNATION/geometry.png)

### 028. FYW_DIVISION

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.025727 | 0.001181233 | 23.71% | 89.50% | 0.016914 |
| TRELLIS.2 | 0.009936 | 0.000171023 | 63.45% | 99.59% | N/A |
| Hybrid | 0.017978 | 0.000622988 | 36.92% | 93.48% | 0.057561 |
| Pixal3D | 0.014811 | 0.000413111 | 46.35% | 96.23% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

GT 输入主要看到后跟；新视角揭示 TRELLIS.2 更合理地补出鞋头与鞋带。Pixal3D 也保留细节，Hybrid 更宽厚且鞋面变化明显；WT 不可见鞋面更平、细节缺失。可见后跟接近不能保证隐藏前掌正确。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/FYW_DIVISION/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/FYW_DIVISION/geometry.png)

### 029. Fresca_Peach_Citrus_Sparkling_Flavored_Soda_12_PK

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.034481 | 0.001651607 | 9.63% | 81.38% | 0.010079 |
| TRELLIS.2 | 0.020920 | 0.000569903 | 11.50% | 97.17% | N/A |
| Hybrid | 0.028208 | 0.001426664 | 18.15% | 79.27% | 0.017553 |
| Pixal3D | 0.052063 | 0.004662150 | 11.62% | 61.30% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Hybrid < WT < Pixal3D**；F@0.01 最高：**Hybrid**。

四方法都未恢复好长方包装比例，TRELLIS.2 的 CD-L1 最低但严格 F@0.01 仍很低。Pixal3D 是其全组最差 CD-L1 样本，盒体压短，背侧有破损/开口、斜穿面和凸起的 FRESCA 图案；这些在 decoder PLY 与 GLB 中均可见。Hybrid 背面粗糙变形，WT 厚度与长宽关系偏离。几何破损和文字失真是两类错误。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Fresca_Peach_Citrus_Sparkling_Flavored_Soda_12_PK/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Fresca_Peach_Citrus_Sparkling_Flavored_Soda_12_PK/geometry.png) · [decoder PLY / GLB 对照](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/stages/029-Pixal3D.png)

### 030. GRANDMOTHER

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009879 | 0.000158428 | 60.30% | 99.93% | 0.010211 |
| TRELLIS.2 | 0.008360 | 0.000120457 | 70.31% | 100.00% | N/A |
| Hybrid | 0.013201 | 0.000300700 | 49.87% | 98.85% | 0.013989 |
| Pixal3D | 0.010131 | 0.000182803 | 63.81% | 99.70% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 的人偶整体比例较接近。三个网格都补出头发和衣服结构，但脚、手臂和服饰细节不同；Hybrid 脚部/裤腿较不规则。WT 背部较平滑，不应把输入视角颜色较忠实等同于隐藏表面恢复好。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/GRANDMOTHER/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/GRANDMOTHER/geometry.png)

### 031. Gigabyte_GA970AUD3P_10_Motherboard_ATX_Socket_AM3

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.024699 | 0.000737677 | 10.20% | 97.22% | 0.004398 |
| TRELLIS.2 | 0.004521 | 0.000026131 | 96.43% | 100.00% | N/A |
| Hybrid | 0.015280 | 0.000533885 | 47.71% | 94.07% | 0.007611 |
| Pixal3D | 0.003680 | 0.000018287 | 98.15% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < Hybrid < WT**；F@0.01 最高：**Pixal3D**。

Pixal3D / TRELLIS.2 的薄盒形状远好于 WT。Pixal3D 配准后朝向暗色背面，native 复查却保留了大部分 970A-UD3P 型号排版，比 TRELLIS.2 / Hybrid 更接近输入；品牌小字仍有改写。灰模有额外图案起伏，Hybrid 厚度/平整度较差。盒体翻面是纯几何配准的语义歧义，不能据此认定 Pixal3D 纹理全丢。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Gigabyte_GA970AUD3P_10_Motherboard_ATX_Socket_AM3/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Gigabyte_GA970AUD3P_10_Motherboard_ATX_Socket_AM3/geometry.png)

### 032. Granimals_20_Wooden_ABC_Blocks_Wagon_85VdSftGsLi

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.006717 | 0.000087187 | 80.51% | 100.00% | 0.006313 |
| TRELLIS.2 | 0.005249 | 0.000037057 | 90.72% | 100.00% | N/A |
| Hybrid | 0.027931 | 0.002137321 | 31.12% | 81.69% | 0.027454 |
| Pixal3D | 0.026148 | 0.000954560 | 19.93% | 89.70% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

此资产实际是单个黄色字母块，与 P0 中相近名字的资产不同。TRELLIS.2 保持立方体外形较好；Hybrid 边角圆化、字母模糊。Pixal3D 比例有偏差，但 native 图保留输入正面 Q 及上表面字母的关系；配准后的其他面不能直接判成字母生成错误。GT 本身有字母浮雕，不能把所有字母起伏判为虚假几何。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Granimals_20_Wooden_ABC_Blocks_Wagon_85VdSftGsLi/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Granimals_20_Wooden_ABC_Blocks_Wagon_85VdSftGsLi/geometry.png)

### 033. Hefty_Waste_Basket_Decorative_Bronze_85_liter

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.013794 | 0.000457490 | 50.64% | 97.58% | 0.012936 |
| TRELLIS.2 | 0.013453 | 0.000424932 | 50.24% | 97.87% | N/A |
| Hybrid | 0.024253 | 0.001435075 | 29.95% | 86.87% | 0.060084 |
| Pixal3D | 0.013854 | 0.000458216 | 49.97% | 97.74% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**WT**。

WT、TRELLIS.2、Pixal3D 的形状分数接近，均保留杯状垃圾桶大轮廓；后两者底色比 GT 浅。Hybrid 桶壁明显粗糙、边缘呈破碎外观，严格 F-score 更差。该视图不能单独确定桶底或内腔深度是否正确。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Hefty_Waste_Basket_Decorative_Bronze_85_liter/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Hefty_Waste_Basket_Decorative_Bronze_85_liter/geometry.png)

### 034. HyperX_Cloud_II_Headset_Red

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.004383 | 0.000025977 | 96.66% | 100.00% | 0.004412 |
| TRELLIS.2 | 0.008486 | 0.000103915 | 63.50% | 100.00% | N/A |
| Hybrid | 0.017451 | 0.000986626 | 56.23% | 89.20% | 0.020212 |
| Pixal3D | 0.008090 | 0.000106442 | 74.61% | 100.00% | N/A |

CD-L1 从低到高：**WT < Pixal3D < TRELLIS.2 < Hybrid**；F@0.01 最高：**WT**。

WT 的包装盒比例最准确，F@0.01 达到很高水平。网格方法虽补出平整连续面，但盒宽/深度、悬挂片尺寸变化，Hybrid 最明显；三个生成标签的文字与耳机图案均不完全忠实。好看的盒面不能替代精确比例。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/HyperX_Cloud_II_Headset_Red/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/HyperX_Cloud_II_Headset_Red/geometry.png)

### 035. Jawbone_UP24_Wireless_Activity_Tracker_Pink_Coral_L

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.006042 | 0.000060852 | 85.94% | 100.00% | 0.006679 |
| TRELLIS.2 | 0.025407 | 0.000946056 | 21.16% | 88.37% | N/A |
| Hybrid | 0.009127 | 0.000160225 | 67.51% | 100.00% | 失败 |
| Pixal3D | 0.022948 | 0.000809173 | 28.37% | 90.57% | N/A |

CD-L1 从低到高：**WT < Hybrid < Pixal3D < TRELLIS.2**；F@0.01 最高：**WT**。

WT 最好保持腕带的扁椭圆与端部重叠关系；Hybrid 也较接近，是其相对优于原生 TRELLIS.2 的例外。TRELLIS.2 端部位置/开口关系改变，Pixal3D 虽像完整手环，但环体和扣合比例偏离；三者颜色也向红色偏移。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Jawbone_UP24_Wireless_Activity_Tracker_Pink_Coral_L/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Jawbone_UP24_Wireless_Activity_Tracker_Pink_Coral_L/geometry.png)

### 036. KITCHEN_SET_CLASSIC_40HwCHfeG0H

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.010076 | 0.000187793 | 69.81% | 99.51% | 0.004762 |
| TRELLIS.2 | 0.014333 | 0.000415308 | 50.07% | 97.27% | N/A |
| Hybrid | 0.011272 | 0.000254805 | 59.90% | 98.53% | 0.023138 |
| Pixal3D | 0.013298 | 0.000888096 | 53.84% | 99.21% | N/A |

CD-L1 从低到高：**WT < Hybrid < Pixal3D < TRELLIS.2**；F@0.01 最高：**WT**。

WT 保留转角厨房组合的相对体积，CD-L1 最低。生成网格补出的柜门、把手和台面局部结构并非都与 GT 一致；Pixal3D 背侧可见独立细长碎片，Hybrid 柜体局部比例改变。较丰富的门板细节不意味着完整形状更准确。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/KITCHEN_SET_CLASSIC_40HwCHfeG0H/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/KITCHEN_SET_CLASSIC_40HwCHfeG0H/geometry.png)

### 037. Kid_Icarus_Uprising_Nintendo_3DS_Game

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.010063 | 0.000136718 | 52.98% | 100.00% | 0.006289 |
| TRELLIS.2 | 0.005851 | 0.000044549 | 87.93% | 100.00% | N/A |
| Hybrid | 0.018295 | 0.000692309 | 41.77% | 90.66% | 0.019427 |
| Pixal3D | 0.006599 | 0.000072212 | 75.62% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 保持薄盒形状最好，Pixal3D 次之，但两者封面角色与文字均有重绘；Hybrid 盒体变厚/鼓起、图案涂抹明显。WT 的大体边界可辨，隐藏面不完整。形状分数不能衡量这类复杂游戏封面。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Kid_Icarus_Uprising_Nintendo_3DS_Game/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Kid_Icarus_Uprising_Nintendo_3DS_Game/geometry.png)

### 038. MOVING_MOUSE_PW_6PCSSET

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.014034 | 0.000412648 | 46.57% | 97.14% | 0.018033 |
| TRELLIS.2 | 0.014823 | 0.000460409 | 49.76% | 95.60% | N/A |
| Hybrid | 0.014135 | 0.000434784 | 53.89% | 96.54% | 失败 |
| Pixal3D | 0.010534 | 0.000223364 | 60.86% | 98.62% | N/A |

CD-L1 从低到高：**Pixal3D < WT < Hybrid < TRELLIS.2**；F@0.01 最高：**Pixal3D**。

Pixal3D 较好保持三只玩具鼠的位置、颜色和轮廓。TRELLIS.2 更换了部分颜色与局部部件，Hybrid 组件方向、尾部和连接更不稳定；WT 的隐藏侧较扁平。三物体整体布局与单体细节需同时检查。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/MOVING_MOUSE_PW_6PCSSET/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/MOVING_MOUSE_PW_6PCSSET/geometry.png)

### 039. MY_MOOD_MEMO

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.006379 | 0.000053186 | 87.80% | 100.00% | 0.009501 |
| TRELLIS.2 | 0.005513 | 0.000053850 | 80.93% | 100.00% | N/A |
| Hybrid | 0.005833 | 0.000046908 | 88.80% | 100.00% | 失败 |
| Pixal3D | 0.004626 | 0.000036585 | 90.24% | 99.92% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < Hybrid < WT**；F@0.01 最高：**Pixal3D**。

Pixal3D 整体最好，四者均保留环形排列的小圆片与中央卡片。TRELLIS.2 / Hybrid 的正面小表情和中央图案更模糊，Hybrid 的部分圆片厚薄、分隔边缘改变；WT 输入颜色较接近，背侧仍简化。本例也说明 CD-L1 与 F@0.01 的次序未必相同。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/MY_MOOD_MEMO/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/MY_MOOD_MEMO/geometry.png)

### 040. Marc_Anthony_Strictly_Curls_Curl_Envy_Perfect_Curl_Cream_6_fl_oz_bottle

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.004600 | 0.000030476 | 92.56% | 100.00% | 0.003976 |
| TRELLIS.2 | 0.002545 | 0.000007874 | 100.00% | 100.00% | N/A |
| Hybrid | 0.017685 | 0.000931156 | 55.88% | 86.84% | 0.006234 |
| Pixal3D | 0.003944 | 0.000019730 | 98.91% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 的长条盒体几何最好，Pixal3D 也接近且保留了更多人物/排版外观；Hybrid 盒壁不平、图案重绘较重。WT 保留输入内容但背侧缺少表面细节。规则盒体的高 F-score 不能保证照片和小字准确。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Marc_Anthony_Strictly_Curls_Curl_Envy_Perfect_Curl_Cream_6_fl_oz_bottle/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Marc_Anthony_Strictly_Curls_Curl_Envy_Perfect_Curl_Cream_6_fl_oz_bottle/geometry.png)

### 041. Markings_Letter_Holder

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.011988 | 0.000237015 | 52.03% | 98.66% | 0.002897 |
| TRELLIS.2 | 0.010624 | 0.000272950 | 70.31% | 96.49% | N/A |
| Hybrid | 0.015392 | 0.000508993 | 52.42% | 92.23% | 0.021947 |
| Pixal3D | 0.016707 | 0.000488836 | 40.16% | 95.56% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Hybrid < Pixal3D**；F@0.01 最高：**TRELLIS.2**。

输入可见的挡板在各结果中都较像，但背侧 GT 是分隔的空信件槽；TRELLIS.2 / Hybrid 补成带填充块/书本状的结构。TRELLIS.2 的填充在 decoder PLY 和 GLB 中均可见，即使它是本例 CD 最好也不代表空槽拓扑正确。Pixal3D 留出更多槽位，却增加外伸条状部件；WT 隐藏面细节较弱。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Markings_Letter_Holder/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Markings_Letter_Holder/geometry.png) · [decoder PLY / GLB 对照](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/stages/041-TRELLIS.2.png)

### 042. Mens_Bahama_in_Black_b4ADzYywRHl

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.010130 | 0.000181129 | 63.50% | 99.60% | 0.013694 |
| TRELLIS.2 | 0.009463 | 0.000197348 | 69.94% | 97.94% | N/A |
| Hybrid | 0.013280 | 0.000344636 | 48.80% | 97.28% | 0.051700 |
| Pixal3D | 0.012923 | 0.000329369 | 54.53% | 97.08% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 的鞋形总体最接近，WT 的整体误差次之但隐藏侧细节少。Hybrid / Pixal3D 的鞋头、后跟厚度和鞋带/缝线有偏差；表面颜色与 GT 有差异。四者均未出现本批最严重的结构崩坏。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Bahama_in_Black_b4ADzYywRHl/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Bahama_in_Black_b4ADzYywRHl/geometry.png)

### 043. Mens_Gold_Cup_ASV_Capetown_Penny_Loafer_in_Black_GkQBKqABeQN

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009358 | 0.000146370 | 64.83% | 99.83% | 0.013863 |
| TRELLIS.2 | 0.008638 | 0.000124973 | 69.22% | 99.72% | N/A |
| Hybrid | 0.012032 | 0.000291101 | 55.41% | 97.93% | 0.025358 |
| Pixal3D | 0.010933 | 0.000257236 | 62.22% | 97.49% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 保持皮鞋轮廓和侧面层次较好，WT 也接近整体体积。Hybrid 鞋头、后跟边缘较不规则，Pixal3D 缝线和侧面起伏改变；黑色底色遮住的局部问题在灰模中更明显。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Gold_Cup_ASV_Capetown_Penny_Loafer_in_Black_GkQBKqABeQN/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Gold_Cup_ASV_Capetown_Penny_Loafer_in_Black_GkQBKqABeQN/geometry.png)

### 044. Mens_Mako_Canoe_Moc_2Eye_Boat_Shoe_in_Coffee_9d05GG33QQQ

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.017421 | 0.000552954 | 41.73% | 94.59% | 0.019007 |
| TRELLIS.2 | 0.010147 | 0.000169601 | 58.73% | 99.78% | N/A |
| Hybrid | 0.016273 | 0.000524574 | 43.10% | 94.18% | 0.053312 |
| Pixal3D | 0.016258 | 0.000478097 | 43.12% | 96.31% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

输入后跟可辨不等于前掌正确。TRELLIS.2 的完整鞋形较好，WT 隐藏鞋面变平，Hybrid / Pixal3D 改变鞋头比例和缝线位置。Hybrid 与 Pixal3D 的显示分数接近，但局部错误分布不同。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Mako_Canoe_Moc_2Eye_Boat_Shoe_in_Coffee_9d05GG33QQQ/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Mako_Canoe_Moc_2Eye_Boat_Shoe_in_Coffee_9d05GG33QQQ/geometry.png)

### 045. Mens_RR_Moc_in_Navy_Suede_vmFfijhBzL3

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.010368 | 0.000191789 | 59.97% | 99.17% | 0.011405 |
| TRELLIS.2 | 0.010065 | 0.000197386 | 67.94% | 99.06% | N/A |
| Hybrid | 0.011810 | 0.000297827 | 58.51% | 97.78% | 0.024026 |
| Pixal3D | 0.009522 | 0.000162859 | 67.15% | 99.68% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

Pixal3D 的 CD-L1 最低，TRELLIS.2 的 F@0.01 略高，差距较小。三个网格都补出了蝴蝶结鞋带，但具体交叉和后跟形状与 GT 不同；Hybrid 侧面有较多凸点和颜色残片。WT 保留可见配色，隐藏面简化。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_RR_Moc_in_Navy_Suede_vmFfijhBzL3/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_RR_Moc_in_Navy_Suede_vmFfijhBzL3/geometry.png)

### 046. Mens_Santa_Cruz_Thong_in_Chocolate_lvxYW7lek6B

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.019236 | 0.000642946 | 36.47% | 94.39% | 0.040280 |
| TRELLIS.2 | 0.007116 | 0.000081565 | 76.46% | 100.00% | N/A |
| Hybrid | 0.017577 | 0.000541203 | 39.60% | 95.33% | 0.065938 |
| Pixal3D | 0.020278 | 0.000726606 | 34.78% | 91.48% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Hybrid < WT < Pixal3D**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 明显更好地保持鞋底长度和鞋带弓形；WT、Hybrid、Pixal3D 在后侧视图中更圆钝/压短，带子与底部关系改变。单个正面视图容易忽略这种沿深度方向的比例错误。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Santa_Cruz_Thong_in_Chocolate_lvxYW7lek6B/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Santa_Cruz_Thong_in_Chocolate_lvxYW7lek6B/geometry.png)

### 047. Mens_Santa_Cruz_Thong_in_Tan_r59C69daRPh

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.014256 | 0.000359934 | 47.17% | 97.13% | 0.022789 |
| TRELLIS.2 | 0.006377 | 0.000065534 | 82.92% | 100.00% | N/A |
| Hybrid | 0.014618 | 0.000379634 | 43.60% | 97.15% | 0.045345 |
| Pixal3D | 0.005021 | 0.000037163 | 90.21% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 与 TRELLIS.2 都较好恢复夹趾拖鞋，前者形状分数更好。WT 鞋带内侧和鞋底较模糊，Hybrid 在带子处出现连接/弯折改变。类似类别在 #46 与本例表现不同，不能以类别概括稳定胜负。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Santa_Cruz_Thong_in_Tan_r59C69daRPh/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Santa_Cruz_Thong_in_Tan_r59C69daRPh/geometry.png)

### 048. Mens_Tremont_Kiltie_Tassel_Loafer_in_Black_Amaretto_FT0I9OjSA6O

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.008723 | 0.000118415 | 68.13% | 99.99% | 0.023900 |
| TRELLIS.2 | 0.009329 | 0.000150971 | 66.02% | 99.88% | N/A |
| Hybrid | 0.011252 | 0.000271250 | 60.24% | 97.69% | 0.025354 |
| Pixal3D | 0.009763 | 0.000184444 | 66.04% | 99.48% | N/A |

CD-L1 从低到高：**WT < TRELLIS.2 < Pixal3D < Hybrid**；F@0.01 最高：**WT**。

WT 的整体鞋体最接近；三种网格的大轮廓相似，但鞋面装饰、后跟和开口形状变化。Pixal3D 底色明显比 GT 深，Hybrid 鞋头细节趋平。此例中表面精致程度与几何排名并不一致。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Tremont_Kiltie_Tassel_Loafer_in_Black_Amaretto_FT0I9OjSA6O/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Mens_Tremont_Kiltie_Tassel_Loafer_in_Black_Amaretto_FT0I9OjSA6O/geometry.png)

### 049. Nescafe_Tasters_Choice_Instant_Coffee_Decaf_House_Blend_Light_7_oz

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009909 | 0.000179930 | 63.94% | 99.92% | 0.007387 |
| TRELLIS.2 | 0.008344 | 0.000098214 | 67.31% | 100.00% | N/A |
| Hybrid | 0.024353 | 0.001483356 | 31.03% | 80.94% | 0.017047 |
| Pixal3D | 0.014803 | 0.000348746 | 45.87% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好保留细长容器轮廓。Hybrid 显得更粗高且标签重绘，Pixal3D 在瓶壁生成较明显的标志/文字形起伏，形状精度反而下降；WT 保留总体体积但背侧平滑。瓶身标签朝向受纯几何配准的轴对称歧义影响。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Nescafe_Tasters_Choice_Instant_Coffee_Decaf_House_Blend_Light_7_oz/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Nescafe_Tasters_Choice_Instant_Coffee_Decaf_House_Blend_Light_7_oz/geometry.png)

### 050. Nestle_Skinny_Cow_Dreamy_Clusters_Candy_Dark_Chocolate_6_pack_1_oz_pouches

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.005838 | 0.000045558 | 83.53% | 100.00% | 0.005694 |
| TRELLIS.2 | 0.004569 | 0.000026332 | 97.30% | 100.00% | N/A |
| Hybrid | 0.018204 | 0.000989488 | 47.56% | 87.55% | 0.018591 |
| Pixal3D | 0.004531 | 0.000027289 | 95.93% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

Pixal3D 与 TRELLIS.2 的 CD-L1 几乎相同，TRELLIS.2 的严格 F-score 更高。native 复查显示 Pixal3D 保留了更接近输入的紫白配色、侧面排版和产品图案，而 TRELLIS.2 / Hybrid 明显重绘；Pixal3D 灰模仍有印刷图案浮雕。Hybrid 盒面更鼓、边缘不平。配准中的正反面互换不代表纹理丢失。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Nestle_Skinny_Cow_Dreamy_Clusters_Candy_Dark_Chocolate_6_pack_1_oz_pouches/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Nestle_Skinny_Cow_Dreamy_Clusters_Candy_Dark_Chocolate_6_pack_1_oz_pouches/geometry.png)

### 051. Netgear_Ac1750_Router_Wireless_Dual_Band_Gigabit_Router

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.003809 | 0.000020366 | 97.06% | 100.00% | 0.002384 |
| TRELLIS.2 | 0.006392 | 0.000053971 | 78.81% | 100.00% | N/A |
| Hybrid | 0.015703 | 0.000667414 | 52.71% | 89.94% | 0.015523 |
| Pixal3D | 0.014868 | 0.000675916 | 67.73% | 91.81% | N/A |

CD-L1 从低到高：**WT < TRELLIS.2 < Pixal3D < Hybrid**；F@0.01 最高：**WT**。

WT 的薄盒体最准确。TRELLIS.2 保留盒状结构，但路由器图案和文字变形；Hybrid 标签大面积涂抹。Pixal3D 将部分印刷内容表现为三维框架和外伸细杆，偏离 GT 平面包装；decoder PLY 与 GLB 均有该缺陷，排除了仅为查看器材质效果的解释。尚不能区分神经生成与解码流程首次补洞，也未用消融证明图案条件是单独原因。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Netgear_Ac1750_Router_Wireless_Dual_Band_Gigabit_Router/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Netgear_Ac1750_Router_Wireless_Dual_Band_Gigabit_Router/geometry.png) · [decoder PLY / GLB 对照](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/stages/051-Pixal3D.png)

### 052. Nintendo_2DS_Crimson_Red

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.007612 | 0.000092121 | 72.63% | 100.00% | 0.019377 |
| TRELLIS.2 | 0.006276 | 0.000089496 | 82.59% | 100.00% | N/A |
| Hybrid | 0.009321 | 0.000140889 | 59.57% | 99.96% | 0.019563 |
| Pixal3D | 0.003960 | 0.000034035 | 95.08% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 与 TRELLIS.2 都较好恢复掌机薄壳和屏幕布局，前者形状更准。Hybrid 双屏区域变成不正确的单块/暗色面，外壳边缘也更不规则；WT 背侧细节不足。这里屏幕布局错误比整体轮廓分数更直接反映外观忠实度。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Nintendo_2DS_Crimson_Red/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Nintendo_2DS_Crimson_Red/geometry.png)

### 053. Nintendo_Yoshi_Action_Figure

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.011711 | 0.000268541 | 57.72% | 98.49% | 0.025982 |
| TRELLIS.2 | 0.008945 | 0.000155322 | 69.26% | 99.55% | N/A |
| Hybrid | 0.015911 | 0.000507663 | 41.19% | 94.61% | 0.042734 |
| Pixal3D | 0.017702 | 0.000560864 | 41.74% | 94.89% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Hybrid < Pixal3D**；F@0.01 最高：**TRELLIS.2**。

输入看到 Yoshi 背面，TRELLIS.2 较合理地补出前面的鼻子、腹部和四肢。WT 的隐藏面更扁平；Hybrid 的头身比例、背部红圈和腹部几何改变较大，Pixal3D 也改变鼻子/腿部比例。此例重在不可见面而不只是背面颜色。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Nintendo_Yoshi_Action_Figure/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Nintendo_Yoshi_Action_Figure/geometry.png)

### 054. OXO_Soft_Works_Can_Opener_SnapLock

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.022559 | 0.000881111 | 31.91% | 90.81% | 0.015199 |
| TRELLIS.2 | 0.017442 | 0.000558764 | 41.76% | 95.48% | N/A |
| Hybrid | 0.015965 | 0.000469912 | 42.31% | 96.48% | 0.015672 |
| Pixal3D | 0.017858 | 0.000631288 | 41.92% | 94.10% | N/A |

CD-L1 从低到高：**Hybrid < TRELLIS.2 < Pixal3D < WT**；F@0.01 最高：**Hybrid**。

Hybrid 是本批唯一 CD-L1 四方法第一的样本，但仍只是相对最好：三个网格对开罐器齿轮、背侧旋钮和手柄关系均有误差。WT 出现多层重叠的手柄外观；TRELLIS.2 / Pixal3D 的金属件和端部几何有偏差。不能将此胜例扩展为整体收益。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/OXO_Soft_Works_Can_Opener_SnapLock/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/OXO_Soft_Works_Can_Opener_SnapLock/geometry.png)

### 055. Office_Depot_Canon_CLI_8CMY_Remanufactured_Ink_Cartridges_Color_Cyan_Magenta_Yellow_3_count

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.005043 | 0.000037003 | 93.62% | 100.00% | 0.005384 |
| TRELLIS.2 | 0.005920 | 0.000050725 | 80.59% | 100.00% | N/A |
| Hybrid | 0.026730 | 0.002149173 | 23.77% | 84.41% | 0.018842 |
| Pixal3D | 0.005273 | 0.000059218 | 95.20% | 99.56% | N/A |

CD-L1 从低到高：**WT < Pixal3D < TRELLIS.2 < Hybrid**；F@0.01 最高：**Pixal3D**。

WT 盒体比例最好，Pixal3D 接近且保留了更多正面排版；TRELLIS.2 正面内容被重绘，Hybrid 标签大片缺失/涂抹、盒体比例也差。Pixal3D 仍有错字和额外面上折纹，外观改善并非完美复制。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Office_Depot_Canon_CLI_8CMY_Remanufactured_Ink_Cartridges_Color_Cyan_Magenta_Yellow_3_count/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Office_Depot_Canon_CLI_8CMY_Remanufactured_Ink_Cartridges_Color_Cyan_Magenta_Yellow_3_count/geometry.png)

### 056. Office_Depot_Canon_CL_41_Remanufactured_Ink_Cartridge_TriColor

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009005 | 0.000495796 | 87.93% | 96.43% | 0.004631 |
| TRELLIS.2 | 0.006105 | 0.000061897 | 79.55% | 100.00% | N/A |
| Hybrid | 0.019922 | 0.001139522 | 43.52% | 88.74% | 0.018092 |
| Pixal3D | 0.004508 | 0.000029210 | 96.93% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 盒体分数最好，保存配准下显示白色背面；native 复查可见其墨盒图案、彩色条带及排版更接近输入。灰模对侧的标签起伏说明几何仍有伪影。TRELLIS.2 / Hybrid 的文字与图案均失真，后者盒壁更不平整。WT 保留总体外形和输入图案，隐藏面较简化。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Office_Depot_Canon_CL_41_Remanufactured_Ink_Cartridge_TriColor/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Office_Depot_Canon_CL_41_Remanufactured_Ink_Cartridge_TriColor/geometry.png)

### 057. Office_Depot_HP_74XL75_Remanufactured_Ink_Cartridges_BlackTriColor_2_count

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.004194 | 0.000026112 | 95.12% | 100.00% | 0.003722 |
| TRELLIS.2 | 0.006662 | 0.000063425 | 87.54% | 100.00% | N/A |
| Hybrid | 0.028900 | 0.002124444 | 26.18% | 78.55% | 0.020141 |
| Pixal3D | 0.005819 | 0.000045661 | 90.62% | 100.00% | N/A |

CD-L1 从低到高：**WT < Pixal3D < TRELLIS.2 < Hybrid**；F@0.01 最高：**WT**。

WT 的包装盒比例最准确。Pixal3D 保留较好的墨盒图案位置与色条，TRELLIS.2 改写了标签构图；Hybrid 盒体鼓起、面上出现多余结构且文字严重模糊。Pixal3D 的表面浮雕和侧面凹凸说明图案清楚并不保证几何无伪影。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Office_Depot_HP_74XL75_Remanufactured_Ink_Cartridges_BlackTriColor_2_count/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Office_Depot_HP_74XL75_Remanufactured_Ink_Cartridges_BlackTriColor_2_count/geometry.png)

### 058. Office_Depot_HP_96_Remanufactured_Ink_Cartridge_Black

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.005899 | 0.000045632 | 88.44% | 100.00% | 0.001777 |
| TRELLIS.2 | 0.006340 | 0.000053266 | 85.86% | 100.00% | N/A |
| Hybrid | 0.022609 | 0.001285815 | 33.29% | 83.55% | 0.010940 |
| Pixal3D | 0.008067 | 0.000078602 | 71.62% | 100.00% | N/A |

CD-L1 从低到高：**WT < TRELLIS.2 < Pixal3D < Hybrid**；F@0.01 最高：**WT**。

WT 与 TRELLIS.2 的盒体形状接近且优于 Hybrid；Pixal3D 保留大轮廓但背板有额外斜纹/折面。三个生成结果的品牌文字均有错误，Hybrid 高背卡及盒体比例变化最大。WT 的输入文字来自原图，不属于新生成的纹理能力。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Office_Depot_HP_96_Remanufactured_Ink_Cartridge_Black/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Office_Depot_HP_96_Remanufactured_Ink_Cartridge_Black/geometry.png)

### 059. Ortho_Forward_Facing_CkAW6rL25xH

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.015005 | 0.000437044 | 47.51% | 97.62% | 0.018392 |
| TRELLIS.2 | 0.013691 | 0.000331785 | 48.58% | 98.16% | N/A |
| Hybrid | 0.017724 | 0.000679343 | 38.77% | 93.50% | 0.040923 |
| Pixal3D | 0.012838 | 0.000302660 | 54.17% | 98.58% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 在头盔整体形状和输入花纹上较好，但背侧灰模仍有额外突出的附件状结构。TRELLIS.2 保持圆壳但花纹更简化；Hybrid 额外开口、凸起和面罩关系明显改变，WT 隐藏壳面较平滑。本例高排名不能掩盖面积较小的局部错误。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Ortho_Forward_Facing_CkAW6rL25xH/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Ortho_Forward_Facing_CkAW6rL25xH/geometry.png)

### 060. PEEKABOO_ROLLER

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.017961 | 0.000959552 | 50.36% | 92.37% | 0.008864 |
| TRELLIS.2 | 0.010463 | 0.000249457 | 66.63% | 97.79% | N/A |
| Hybrid | 0.026541 | 0.001695593 | 23.91% | 80.16% | 0.040608 |
| Pixal3D | 0.016430 | 0.000366103 | 25.05% | 98.77% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 保留圆筒轮廓、槽口和支脚较好，但端面增加了圆形起伏。Hybrid 槽口和端面出现不规则挤压/凹凸，Pixal3D 端面趋平、开槽比例改变；WT 隐藏面细节较弱。彩色同心圈接近不能替代槽口几何评价。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/PEEKABOO_ROLLER/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/PEEKABOO_ROLLER/geometry.png)

### 061. PINEAPPLE_MARACA_6_PCSSET

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.024688 | 0.000901940 | 20.64% | 92.29% | 0.005719 |
| TRELLIS.2 | 0.016630 | 0.001059456 | 61.15% | 90.69% | N/A |
| Hybrid | 0.023792 | 0.001299459 | 27.09% | 85.21% | 0.032447 |
| Pixal3D | 0.007051 | 0.000091405 | 79.81% | 99.67% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < Hybrid < WT**；F@0.01 最高：**Pixal3D**。

Pixal3D 较好恢复球状玩具整体体积，尽管表面刻痕仍有变化。TRELLIS.2 侧边绿色部件外伸较大，Hybrid 出现过大的分块/缝隙，WT 背侧过于圆滑且比例不对。本例是 Pixal3D 相对原生 TRELLIS.2 的明显几何改善。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/PINEAPPLE_MARACA_6_PCSSET/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/PINEAPPLE_MARACA_6_PCSSET/geometry.png)

### 062. Perricone_MD_Best_of_Perricone_7Piece_Collection_MEGsO6GIsyL

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.008428 | 0.000103270 | 66.11% | 100.00% | 0.005898 |
| TRELLIS.2 | 0.007707 | 0.000084618 | 72.30% | 100.00% | N/A |
| Hybrid | 0.020708 | 0.000988365 | 32.05% | 86.33% | 0.017780 |
| Pixal3D | 0.028686 | 0.001392221 | 28.01% | 80.88% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Hybrid < Pixal3D**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 和 WT 保住长条包装的大体比例。Pixal3D 将长盒明显压短，Hybrid 盒壁/边缘变形，且两者文字更凌乱。Pixal3D 并非所有包装类都占优；正确识别为盒子仍可能严重误估不可见长度。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Perricone_MD_Best_of_Perricone_7Piece_Collection_MEGsO6GIsyL/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Perricone_MD_Best_of_Perricone_7Piece_Collection_MEGsO6GIsyL/geometry.png)

### 063. Perricone_MD_Cold_Plasma

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.006345 | 0.000054147 | 82.71% | 100.00% | 0.006266 |
| TRELLIS.2 | 0.004438 | 0.000024299 | 99.26% | 100.00% | N/A |
| Hybrid | 0.026470 | 0.001714247 | 23.45% | 84.42% | 0.014026 |
| Pixal3D | 0.004287 | 0.000024158 | 97.27% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

Pixal3D 与 TRELLIS.2 的规则盒形都很接近 GT，前者 CD-L1 略好而后者 F@0.01 更高。Hybrid 盒体比例及边缘明显偏离，WT 隐藏面简化。Pixal3D 灰模也有不应被精细标签外观掩盖的斜向面上起伏。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Perricone_MD_Cold_Plasma/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Perricone_MD_Cold_Plasma/geometry.png)

### 064. Perricone_MD_Skin_Total_Body_Supplements

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.004332 | 0.000025807 | 94.16% | 100.00% | 0.002321 |
| TRELLIS.2 | 0.003447 | 0.000014712 | 99.58% | 100.00% | N/A |
| Hybrid | 0.018580 | 0.001388553 | 53.56% | 89.90% | 0.016491 |
| Pixal3D | 0.003554 | 0.000015291 | 99.80% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

TRELLIS.2 和 Pixal3D 的盒形近似同样准确；Pixal3D 保留更多表格排版，TRELLIS.2 小字更模糊。Hybrid 文字变成散乱笔画、边角更圆，形状也较差。WT 保留输入内容但背侧缺少细节，不能将其颜色当生成纹理比较。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Perricone_MD_Skin_Total_Body_Supplements/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Perricone_MD_Skin_Total_Body_Supplements/geometry.png)

### 065. Playmates_nickelodeon_teenage_mutant_ninja_turtles_shredder

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009793 | 0.000176537 | 65.10% | 99.47% | 0.010590 |
| TRELLIS.2 | 0.007456 | 0.000092562 | 74.28% | 99.98% | N/A |
| Hybrid | 0.010639 | 0.000206492 | 60.02% | 99.27% | 失败 |
| Pixal3D | 0.007739 | 0.000115347 | 75.62% | 99.80% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

TRELLIS.2 与 Pixal3D 接近：前者 CD-L1 最低、后者 F@0.01 略高。网格保留盔甲和尖角，但手部/护甲局部结构仍变；Hybrid 尖刺、手臂和靴子关系变化更大。WT 隐藏面较平，细长部件不能仅按整体分数判定完整。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Playmates_nickelodeon_teenage_mutant_ninja_turtles_shredder/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Playmates_nickelodeon_teenage_mutant_ninja_turtles_shredder/geometry.png)

### 066. Pokmon_Y_Nintendo_3DS_Game

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.004344 | 0.000031594 | 91.27% | 100.00% | 0.008139 |
| TRELLIS.2 | 0.006341 | 0.000046051 | 93.20% | 100.00% | N/A |
| Hybrid | 0.009353 | 0.000166826 | 74.63% | 100.00% | 0.015325 |
| Pixal3D | 0.012565 | 0.000394141 | 61.55% | 96.34% | N/A |

CD-L1 从低到高：**WT < TRELLIS.2 < Hybrid < Pixal3D**；F@0.01 最高：**TRELLIS.2**。

WT 的薄游戏盒整体距离最好，TRELLIS.2 的 F@0.01 略好。Pixal3D 在背/侧面增加下翻的片状附件，拉低几何质量；Hybrid 盒形较规则但封面内容仍重绘。复杂图案的可辨识程度需与这些小面积结构错误分开。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Pokmon_Y_Nintendo_3DS_Game/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Pokmon_Y_Nintendo_3DS_Game/geometry.png)

### 067. Pokémon_Omega_Ruby_Alpha_Sapphire_Dual_Pack_Nintendo_3DS

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.040557 | 0.001981338 | 5.57% | 66.46% | 0.001731 |
| TRELLIS.2 | 0.008903 | 0.000092839 | 57.35% | 100.00% | N/A |
| Hybrid | 0.021891 | 0.000908548 | 24.20% | 82.75% | 0.005548 |
| Pixal3D | 0.012012 | 0.000581578 | 60.31% | 97.84% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**Pixal3D**。

WT 是其全组最差 CD-L1 样本，正面方盒外观不能保证厚度与完整体积正确。TRELLIS.2 的 CD-L1 最好；native 复查显示 Pixal3D 的封面角色和标题更接近输入，F@0.01 略高，但背/侧面有外伸片与表面伪影。Hybrid 封面严重涂抹、几何明显退化。其 OOM 恢复只是执行成功，不是按质量挑选新 seed。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Pokémon_Omega_Ruby_Alpha_Sapphire_Dual_Pack_Nintendo_3DS/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Pokémon_Omega_Ruby_Alpha_Sapphire_Dual_Pack_Nintendo_3DS/geometry.png)

### 068. Predito_LZ_TRX_FG_W

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.011007 | 0.000195388 | 55.24% | 99.69% | 0.009824 |
| TRELLIS.2 | 0.009265 | 0.000157237 | 66.83% | 99.35% | N/A |
| Hybrid | 0.010928 | 0.000216272 | 59.37% | 98.97% | 0.018027 |
| Pixal3D | 0.012521 | 0.000289001 | 51.91% | 97.80% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Hybrid < WT < Pixal3D**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 在足球鞋整体形状上略占优，WT 与 Hybrid 中等接近。Pixal3D 鞋面出现密集重复起伏，明显多于 GT 平滑鞋面；Hybrid 的颜色与鞋头比例也有变化。更细的表面纹路不必然是正确细节。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Predito_LZ_TRX_FG_W/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Predito_LZ_TRX_FG_W/geometry.png)

### 069. Provence_Bath_Towel_Royal_Blue

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.017585 | 0.000497488 | 36.98% | 96.76% | 0.012611 |
| TRELLIS.2 | 0.019004 | 0.000600743 | 31.16% | 90.68% | N/A |
| Hybrid | 0.023052 | 0.000960587 | 30.38% | 84.69% | 0.017831 |
| Pixal3D | 0.019439 | 0.000557867 | 26.81% | 97.37% | N/A |

CD-L1 从低到高：**WT < TRELLIS.2 < Pixal3D < Hybrid**；F@0.01 最高：**WT**。

四方法严格 F-score 都偏低，WT 虽 CD-L1 最低，隐藏面仍像圆钝薄垫。TRELLIS.2 / Pixal3D 补出较多折叠层，但厚度、折边和形状不同；Hybrid 最圆滑、折叠层次较弱。不能把本例相对第一说成高质量重建。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Provence_Bath_Towel_Royal_Blue/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Provence_Bath_Towel_Royal_Blue/geometry.png)

### 070. Quercetin_500

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.014494 | 0.000554064 | 59.15% | 92.47% | 0.003528 |
| TRELLIS.2 | 0.003217 | 0.000014116 | 98.09% | 100.00% | N/A |
| Hybrid | 0.028203 | 0.001917274 | 18.56% | 83.67% | 0.015431 |
| Pixal3D | 0.003655 | 0.000018944 | 96.81% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 / Pixal3D 的瓶身整体准确，后者文字排版相对更接近输入但并非精确复制。Hybrid 瓶肩和瓶体比例明显改变、标签涂抹，WT 保留体积但误差较高。规则外形的高 F-score 对细小标签起伏和错字不敏感。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Quercetin_500/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Quercetin_500/geometry.png)

### 071. ROAD_CONSTRUCTION_SET

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.018346 | 0.000681121 | 39.65% | 93.95% | 0.020079 |
| TRELLIS.2 | 0.017380 | 0.000653852 | 45.68% | 93.22% | N/A |
| Hybrid | 0.022498 | 0.001249813 | 37.91% | 85.27% | 失败 |
| Pixal3D | 0.018716 | 0.000587413 | 35.61% | 94.51% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

多个工程车的数量/布局大致可辨，但背侧几何仍有明显差异。TRELLIS.2 相对最好；Hybrid 把多个部件挤压/连接成更混乱结构，Pixal3D 局部车轮与铲臂改变，WT 后侧轮廓模糊。本例须同时评价组合布局与单车结构。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/ROAD_CONSTRUCTION_SET/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/ROAD_CONSTRUCTION_SET/geometry.png)

### 072. Razer_BlackWidow_Stealth_2014_Keyboard_07VFzIVabgh

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.016989 | 0.000515590 | 40.24% | 95.12% | 0.023423 |
| TRELLIS.2 | 0.007524 | 0.000095630 | 73.45% | 100.00% | N/A |
| Hybrid | 0.015834 | 0.000516684 | 53.05% | 94.43% | 失败 |
| Pixal3D | 0.013214 | 0.000371897 | 56.81% | 95.97% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好保留键盘板形、按键和盘绕线缆。Hybrid 前后边框与线缆区域产生较厚的条带/连接，Pixal3D 背视出现额外伸出的整排结构，WT 按键层次较弱。文字标签未作 OCR 评价，不按键帽清晰度推断字符正确。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Razer_BlackWidow_Stealth_2014_Keyboard_07VFzIVabgh/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Razer_BlackWidow_Stealth_2014_Keyboard_07VFzIVabgh/geometry.png)

### 073. Razer_BlackWidow_Ultimate_2014_Mechanical_Gaming_Keyboard

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.010381 | 0.000197200 | 61.68% | 99.30% | 0.014828 |
| TRELLIS.2 | 0.007405 | 0.000119013 | 79.96% | 99.36% | N/A |
| Hybrid | 0.009703 | 0.000170523 | 63.46% | 99.55% | 失败 |
| Pixal3D | 0.004650 | 0.000033896 | 92.13% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < Hybrid < WT**；F@0.01 最高：**Pixal3D**。

Pixal3D 最好保持另一款键盘的扁平轮廓与键区，TRELLIS.2 次之；与 #72 的局部失败不同。Hybrid 部分按键和线缆被改形，WT 隐藏面近似平滑薄板。即使主体形状较好，细线和字符仍需单独检查。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Razer_BlackWidow_Ultimate_2014_Mechanical_Gaming_Keyboard/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Razer_BlackWidow_Ultimate_2014_Mechanical_Gaming_Keyboard/geometry.png)

### 074. Razer_Taipan_White_Ambidextrous_Gaming_Mouse

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.027818 | 0.001506248 | 27.91% | 79.90% | 失败 |
| TRELLIS.2 | 0.010401 | 0.000194527 | 59.83% | 99.03% | N/A |
| Hybrid | 0.025702 | 0.001229776 | 27.73% | 82.01% | 0.076111 |
| Pixal3D | 0.021026 | 0.001154885 | 39.14% | 91.86% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好恢复鼠标曲面及盘线。WT 的线团/鼠标相对体积明显失真，而且本例是 WT 唯一 SSI 深度拟合失败项；Hybrid 线团过大且鼠标曲面变形，Pixal3D 线缆变成较长外伸条。不是单纯白色纹理导致的观感差异。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Razer_Taipan_White_Ambidextrous_Gaming_Mouse/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Razer_Taipan_White_Ambidextrous_Gaming_Mouse/geometry.png)

### 075. Reebok_DMX_MAX_MANIA_WD_D

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.019469 | 0.000670872 | 33.30% | 95.10% | 0.017282 |
| TRELLIS.2 | 0.010868 | 0.000228785 | 62.53% | 98.49% | N/A |
| Hybrid | 0.016601 | 0.000542901 | 39.27% | 94.29% | 0.060459 |
| Pixal3D | 0.013215 | 0.000341864 | 52.44% | 97.47% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 在不可见鞋头与鞋带上较接近 GT，Pixal3D 也形成合理鞋形。WT 隐藏面圆钝、结构简化；Hybrid 鞋头偏宽、鞋口和后跟形状变化更明显。后跟品牌字样各生成结果仍有差异。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Reebok_DMX_MAX_MANIA_WD_D/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Reebok_DMX_MAX_MANIA_WD_D/geometry.png)

### 076. Reebok_SOMERSET_RUN

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.008983 | 0.000156397 | 68.90% | 99.25% | 0.011617 |
| TRELLIS.2 | 0.010860 | 0.000217868 | 59.24% | 98.66% | N/A |
| Hybrid | 0.010678 | 0.000201167 | 59.88% | 99.27% | 0.018618 |
| Pixal3D | 0.011662 | 0.000276048 | 56.88% | 97.40% | N/A |

CD-L1 从低到高：**WT < Hybrid < TRELLIS.2 < Pixal3D**；F@0.01 最高：**WT**。

WT 整体鞋体误差最低，尽管背侧更平滑。三个网格把鞋底、鞋面和系带补得更丰富，但轮廓与 GT 有不同偏差；Hybrid 的鞋底和鞋头形状改变，Pixal3D 的侧面沟纹更深。此例再次说明生成细节不等于精度收益。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Reebok_SOMERSET_RUN/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Reebok_SOMERSET_RUN/geometry.png)

### 077. Room_Essentials_Dish_Drainer_Collapsible_White

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.008238 | 0.000105280 | 73.82% | 100.00% | 0.023554 |
| TRELLIS.2 | 0.008579 | 0.000119828 | 68.54% | 100.00% | N/A |
| Hybrid | 0.008390 | 0.000104336 | 65.62% | 100.00% | 0.035417 |
| Pixal3D | 0.008592 | 0.000111700 | 67.89% | 99.99% | N/A |

CD-L1 从低到高：**WT < Hybrid < TRELLIS.2 < Pixal3D**；F@0.01 最高：**WT**。

四者 CD-L1 很接近，WT 最低。三个网格均恢复碗碟架的大量竖齿，但局部数量、排列与分隔槽仍有差异；Hybrid 边框颜色/形状较不稳定，WT 隐藏面齿状细节较少。整体面积加权指标可能弱化细齿错误。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Room_Essentials_Dish_Drainer_Collapsible_White/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Room_Essentials_Dish_Drainer_Collapsible_White/geometry.png)

### 078. Room_Essentials_Fabric_Cube_Lavender

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.008463 | 0.000119998 | 71.83% | 99.90% | 0.009940 |
| TRELLIS.2 | 0.005630 | 0.000042702 | 90.45% | 100.00% | N/A |
| Hybrid | 0.029027 | 0.002483963 | 34.14% | 77.66% | 0.031226 |
| Pixal3D | 0.008005 | 0.000128134 | 76.58% | 99.74% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 最好保持开口布筐，Pixal3D 也形成内腔但外壁褶皱偏重。Hybrid 顶部有跨过开口的近水平面、底部有异常起伏；decoder PLY 与 GLB 中均存在。WT 保留开口轮廓但隐藏面平滑。缺陷定位在 GLB 导出之前，仍不能据此区分结构注入、生成和首次补洞，也未测量内部填充体积。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Room_Essentials_Fabric_Cube_Lavender/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Room_Essentials_Fabric_Cube_Lavender/geometry.png) · [decoder PLY / GLB 对照](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/stages/078-Hybrid.png)

### 079. Room_Essentials_Kitchen_Towels_16_x_26_2_count

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.018341 | 0.000732592 | 42.96% | 91.59% | 0.012088 |
| TRELLIS.2 | 0.018434 | 0.001070435 | 46.03% | 93.57% | N/A |
| Hybrid | 0.024198 | 0.001301749 | 29.89% | 81.71% | 0.021565 |
| Pixal3D | 0.011064 | 0.000202078 | 58.07% | 99.77% | N/A |

CD-L1 从低到高：**Pixal3D < WT < TRELLIS.2 < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 较好同时保持格纹与多层折叠外形，明显优于其余三个的形状均值。TRELLIS.2 / Hybrid 将格纹拉成长条波纹且折层厚薄改变，WT 保留输入格纹但背侧折层模糊。纹理改善与几何改善在本例同向，仍不能据此做单因素归因。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Room_Essentials_Kitchen_Towels_16_x_26_2_count/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Room_Essentials_Kitchen_Towels_16_x_26_2_count/geometry.png)

### 080. SHAPE_MATCHING_NxacpAY9jDt

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.008544 | 0.000116621 | 67.37% | 100.00% | 0.008737 |
| TRELLIS.2 | 0.009446 | 0.000159638 | 67.76% | 99.95% | N/A |
| Hybrid | 0.010710 | 0.000189969 | 58.18% | 100.00% | 0.024827 |
| Pixal3D | 0.008121 | 0.000142161 | 75.67% | 99.72% | N/A |

CD-L1 从低到高：**Pixal3D < WT < TRELLIS.2 < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 相对最好保留四块拼板的位置、颜色及板形。TRELLIS.2 的颜色/块形关系变化，Hybrid 板面出现多余隆起及不规则连接；WT 主体布局接近，但背侧更像平板。不能只按四块数量正确判断形状匹配正确。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/SHAPE_MATCHING_NxacpAY9jDt/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/SHAPE_MATCHING_NxacpAY9jDt/geometry.png)

### 081. SPEED_BOAT

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.034294 | 0.002119506 | 22.24% | 76.24% | 0.062997 |
| TRELLIS.2 | 0.024660 | 0.000894263 | 24.42% | 92.13% | N/A |
| Hybrid | 0.029218 | 0.001625919 | 24.05% | 76.33% | 0.096577 |
| Pixal3D | 0.027809 | 0.001389273 | 28.04% | 86.82% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**Pixal3D**。

四方法都难以恢复船体与人偶的完整关系，F@0.01 均不足 30%。TRELLIS.2 的 CD-L1 最低，Pixal3D 的 F@0.01 最高，仍有体积和人物位置误差；WT / Hybrid 的保存配准出现上下语义错置。native 中 WT、Hybrid、Pixal3D 保留输入的上下关系，TRELLIS.2 展示侧向布局；该方向观察不能替代完整形状评价。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/SPEED_BOAT/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/SPEED_BOAT/geometry.png)

### 082. Santa_Cruz_Mens

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.012108 | 0.000261260 | 55.68% | 99.30% | 0.019998 |
| TRELLIS.2 | 0.013785 | 0.000359314 | 47.99% | 96.56% | N/A |
| Hybrid | 0.013826 | 0.000351790 | 47.78% | 97.81% | 0.034246 |
| Pixal3D | 0.010660 | 0.000262419 | 65.06% | 97.49% | N/A |

CD-L1 从低到高：**Pixal3D < WT < TRELLIS.2 < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 的鞋体与鞋口比例较好，WT 次之但隐藏侧平滑。TRELLIS.2 鞋头/后跟比例有变化，Hybrid 鞋口及鞋面较粗糙且颜色明显变深。织物质感与整体体积不能合为一个质量判断。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Santa_Cruz_Mens/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Santa_Cruz_Mens/geometry.png)

### 083. Seagate_3TB_Central_shared_storage

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.011895 | 0.000335884 | 59.82% | 95.49% | 0.003750 |
| TRELLIS.2 | 0.003191 | 0.000023979 | 97.94% | 99.97% | N/A |
| Hybrid | 0.016725 | 0.000556665 | 34.42% | 92.58% | 0.019069 |
| Pixal3D | 0.008534 | 0.000127583 | 76.57% | 99.28% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好保持硬盘盒的圆角梯形轮廓。Pixal3D 增加了背部接口状细节，Hybrid 壳体轮廓与前面接口位置变化且表面粗糙；WT 的背侧厚度也不够准确。GT 在此背视较平整，新增接口不能自动视为有益补全。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Seagate_3TB_Central_shared_storage/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Seagate_3TB_Central_shared_storage/geometry.png)

### 084. Simon_Swipe_Game

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.007875 | 0.000121875 | 78.85% | 99.54% | 0.012434 |
| TRELLIS.2 | 0.005822 | 0.000049542 | 90.56% | 100.00% | N/A |
| Hybrid | 0.011697 | 0.000244699 | 54.30% | 98.97% | 失败 |
| Pixal3D | 0.010911 | 0.000202019 | 58.99% | 99.69% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好恢复圆环和中央按钮结构，但彩色区段与 GT 的对应不同。Hybrid 中心及边缘变形。Pixal3D 的 native 图保留四色分区，配准后看不到色块不能认定材质消失；其中央凸起高度仍有偏差。WT 保留大轮廓，隐藏结构较弱。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Simon_Swipe_Game/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Simon_Swipe_Game/geometry.png)

### 085. Sony_Acid_Music_Studio

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.019194 | 0.000445713 | 9.48% | 99.98% | 0.002683 |
| TRELLIS.2 | 0.006872 | 0.000065731 | 79.65% | 99.97% | N/A |
| Hybrid | 0.015307 | 0.000394282 | 37.93% | 97.18% | 0.003584 |
| Pixal3D | 0.004604 | 0.000026268 | 97.94% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < Hybrid < WT**；F@0.01 最高：**Pixal3D**。

Pixal3D 的薄盒几何最好，TRELLIS.2 次之；WT 正面接近但完整形状误差较大。Pixal3D 配准后显示浅色背面，native 却保留接近输入的绿色斜纹、人物照片与 Music Studio 排版；小字仍有错误。TRELLIS.2 / Hybrid 更明显地改写文字与构图，Hybrid 盒缘也较粗糙。不能将配准翻面解释成封面纹理消失。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Sony_Acid_Music_Studio/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Sony_Acid_Music_Studio/geometry.png)

### 086. SpiderMan_Titan_Hero_12Inch_Action_Figure_oo1qph4wwiW

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.005324 | 0.000053943 | 86.00% | 99.99% | 0.005332 |
| TRELLIS.2 | 0.004440 | 0.000031574 | 92.83% | 100.00% | N/A |
| Hybrid | 0.008099 | 0.000120353 | 71.67% | 99.98% | 失败 |
| Pixal3D | 0.005842 | 0.000058172 | 84.05% | 99.93% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好恢复人体比例，WT 的整体几何次之；Pixal3D 也较接近。三个生成结果背部服装的细纹/标志较 GT 简化，Hybrid 头身及腿部比例偏差更明显。WT 隐藏的正面细节不完整，输入颜色忠实不代表新视角服装可用。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/SpiderMan_Titan_Hero_12Inch_Action_Figure_oo1qph4wwiW/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/SpiderMan_Titan_Hero_12Inch_Action_Figure_oo1qph4wwiW/geometry.png)

### 087. Squirt_Strain_Fruit_Basket

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.023883 | 0.000987553 | 28.21% | 87.37% | 0.033816 |
| TRELLIS.2 | 0.009987 | 0.000191209 | 64.31% | 99.17% | N/A |
| Hybrid | 0.024451 | 0.001160841 | 25.50% | 83.26% | 0.032376 |
| Pixal3D | 0.019754 | 0.000659821 | 32.06% | 94.55% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 最好保持水果篮和大水果的相对体积。WT 隐藏面简化，Hybrid 额外加粗/堆叠局部形状，Pixal3D 水果比例和篮内物体布局改变。高饱和颜色相似并不能掩盖篮内三维关系错误。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Squirt_Strain_Fruit_Basket/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Squirt_Strain_Fruit_Basket/geometry.png)

### 088. Super_Mario_3D_World_Wii_U_Game

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.004424 | 0.000030882 | 94.15% | 100.00% | 0.004734 |
| TRELLIS.2 | 0.003804 | 0.000024236 | 92.83% | 100.00% | N/A |
| Hybrid | 0.007644 | 0.000098719 | 74.01% | 100.00% | 0.006561 |
| Pixal3D | 0.003874 | 0.000023185 | 95.50% | 100.00% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**Pixal3D**。

WT、TRELLIS.2、Pixal3D 的薄盒几何都很好，Hybrid 稍差。保存配准使三个网格均朝向蓝色底壳；native 复查显示 Hybrid 与 Pixal3D 均保留封面，Pixal3D 的角色/标题更接近输入，Hybrid 更模糊。TRELLIS.2 默认方向近侧缘，不能据此断言它没有封面。主体平整也仍可能含细小折面和图案起伏。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Super_Mario_3D_World_Wii_U_Game/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Super_Mario_3D_World_Wii_U_Game/geometry.png)

### 089. TABLEWARE_SET_5CHkPjjxVpp

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.035283 | 0.001957090 | 18.58% | 71.40% | 0.064313 |
| TRELLIS.2 | 0.006128 | 0.000068466 | 86.18% | 100.00% | N/A |
| Hybrid | 0.030531 | 0.001593630 | 25.69% | 77.30% | 失败 |
| Pixal3D | 0.027607 | 0.001256008 | 27.10% | 82.63% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 明显最好地保留分离餐具的空间布局、杯碗形状与相对高度。WT 的物体上下层关系与厚度失真，Hybrid 布局扭转、器皿挤叠，Pixal3D 存在错误堆叠/倾斜。此例是四方法差距很大的组合物体案例，而不是纯纹理问题。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/TABLEWARE_SET_5CHkPjjxVpp/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/TABLEWARE_SET_5CHkPjjxVpp/geometry.png)

### 090. TABLEWARE_SET_5ww1UFLuCJG

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.010876 | 0.000252978 | 63.05% | 97.94% | 0.015352 |
| TRELLIS.2 | 0.006514 | 0.000068065 | 82.84% | 100.00% | N/A |
| Hybrid | 0.008567 | 0.000147354 | 71.72% | 99.23% | 失败 |
| Pixal3D | 0.007811 | 0.000144160 | 78.35% | 98.93% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好恢复两套餐具及独立刀具。WT 把碗盘层次简化，Hybrid 碗/盘边界变形；Pixal3D 整体接近，但前方刀具呈分裂片状。严格形状分数可以较高，却仍漏掉小面积薄部件错误。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/TABLEWARE_SET_5ww1UFLuCJG/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/TABLEWARE_SET_5ww1UFLuCJG/geometry.png)

### 091. TROCHILUS_BOOST

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.010629 | 0.000207757 | 61.82% | 99.42% | 0.011465 |
| TRELLIS.2 | 0.009631 | 0.000179199 | 66.07% | 98.87% | N/A |
| Hybrid | 0.010227 | 0.000187550 | 61.29% | 99.63% | 0.015990 |
| Pixal3D | 0.009993 | 0.000194474 | 64.11% | 98.77% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

四者整体鞋形分数接近，TRELLIS.2 略优。Pixal3D 的斑点与绿色鞋带较贴近输入，Hybrid 配色明显变深、鞋带颜色改变；三个网格的后跟和侧面装饰均有偏差。WT 隐藏面平滑，本例不支持稳定的大幅方法差距。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/TROCHILUS_BOOST/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/TROCHILUS_BOOST/geometry.png)

### 092. Tag_Dishtowel_Waffle_Gray_Checks_18_x_26

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.022766 | 0.000918216 | 35.64% | 88.19% | 0.035308 |
| TRELLIS.2 | 0.009861 | 0.000175525 | 68.07% | 99.93% | N/A |
| Hybrid | 0.019783 | 0.000660842 | 32.26% | 92.52% | 0.030815 |
| Pixal3D | 0.019027 | 0.000558304 | 28.00% | 95.31% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 最接近薄折叠毛巾的层次和厚度。WT 背侧偏厚且细节少，Hybrid 增大了褶皱/层厚并改变格纹，Pixal3D 把条格纹表现为较强的几何凹凸。纹理是否可辨与布料是否保持平整应分开。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Tag_Dishtowel_Waffle_Gray_Checks_18_x_26/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Tag_Dishtowel_Waffle_Gray_Checks_18_x_26/geometry.png)

### 093. Thomas_Friends_Wooden_Railway_Deluxe_Track_Accessory_Pack

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.004510 | 0.000035995 | 93.58% | 99.98% | 0.005277 |
| TRELLIS.2 | 0.004641 | 0.000048908 | 90.91% | 99.98% | N/A |
| Hybrid | 0.005131 | 0.000048951 | 87.08% | 100.00% | 失败 |
| Pixal3D | 0.003665 | 0.000026630 | 96.57% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < WT < TRELLIS.2 < Hybrid**；F@0.01 最高：**Pixal3D**。

四者都较好保留轨道、交叉部件和两个标志杆，Pixal3D 略好。Hybrid 端部和标志形状/颜色有变化，WT 隐藏面细节少。小杆、标志文字的误差可能被大面积轨道主导的整体分数弱化。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Thomas_Friends_Wooden_Railway_Deluxe_Track_Accessory_Pack/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Thomas_Friends_Wooden_Railway_Deluxe_Track_Accessory_Pack/geometry.png)

### 094. Timberland_Mens_Earthkeepers_Casco_Bay_Suede_1Eye

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.011302 | 0.000204887 | 54.23% | 99.85% | 0.015416 |
| TRELLIS.2 | 0.008503 | 0.000153862 | 74.49% | 99.30% | N/A |
| Hybrid | 0.013817 | 0.000380078 | 49.50% | 96.41% | 0.024473 |
| Pixal3D | 0.008492 | 0.000119636 | 68.41% | 99.83% | N/A |

CD-L1 从低到高：**Pixal3D < TRELLIS.2 < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

Pixal3D 与 TRELLIS.2 的 CD-L1 仅有极小差别，TRELLIS.2 的 F@0.01 更高，不宜据 CD 均值宣称明显胜负。Hybrid 鞋口/侧面生成了额外不规则起伏，WT 背侧较平滑；三种网格的鞋带交叉仍不同于 GT。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Timberland_Mens_Earthkeepers_Casco_Bay_Suede_1Eye/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Timberland_Mens_Earthkeepers_Casco_Bay_Suede_1Eye/geometry.png)

### 095. US_Army_Stash_Lunch_Bag

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.011987 | 0.000242560 | 55.30% | 99.73% | 0.014291 |
| TRELLIS.2 | 0.009420 | 0.000147748 | 64.47% | 99.65% | N/A |
| Hybrid | 0.020881 | 0.001217171 | 36.81% | 89.35% | 0.019080 |
| Pixal3D | 0.011498 | 0.000271349 | 59.88% | 98.75% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好保留午餐袋整体外形，Pixal3D 保留部分迷彩图案但多出明显长垂带，背侧纹理对应的起伏也较重。Hybrid 轮廓/折面和图案改变更多，WT 隐藏面平滑。迷彩图案改善不能抵消额外结构错误。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/US_Army_Stash_Lunch_Bag/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/US_Army_Stash_Lunch_Bag/geometry.png)

### 096. Wilton_PreCut_Parchment_Sheets_10_x_15_24_sheets

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.003056 | 0.000012488 | 99.75% | 100.00% | 0.004780 |
| TRELLIS.2 | 0.009707 | 0.000108177 | 45.36% | 100.00% | N/A |
| Hybrid | 0.012134 | 0.000432696 | 65.97% | 93.60% | 失败 |
| Pixal3D | 0.002199 | 0.000006121 | 99.95% | 100.00% | N/A |

CD-L1 从低到高：**Pixal3D < WT < TRELLIS.2 < Hybrid**；F@0.01 最高：**Pixal3D**。

Pixal3D 同时保留长条盒体和饼干照片/排版，是其几何与外观同向改善的代表；WT 盒体也很接近。TRELLIS.2 标签明显涂抹，Hybrid 文字和图片被重绘且形状较差。Pixal3D 接近满分仍不等于逐字符验证通过。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Wilton_PreCut_Parchment_Sheets_10_x_15_24_sheets/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Wilton_PreCut_Parchment_Sheets_10_x_15_24_sheets/geometry.png)

### 097. Womens_Authentic_Original_Boat_Shoe_in_Classic_Brown_Leather

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.021698 | 0.000802885 | 32.80% | 91.41% | 0.031964 |
| TRELLIS.2 | 0.009199 | 0.000170967 | 68.99% | 98.86% | N/A |
| Hybrid | 0.019362 | 0.000682582 | 37.56% | 92.74% | 0.072386 |
| Pixal3D | 0.021457 | 0.000818378 | 33.23% | 92.02% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Hybrid < Pixal3D < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 在完整鞋形上明显最好；WT、Hybrid、Pixal3D 从后跟看较像，但隐藏鞋头/鞋口的长度和比例偏离。Pixal3D 后跟外观较完整并未带来本例几何收益；几何缺陷主要不能从输入后跟一面看出。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Womens_Authentic_Original_Boat_Shoe_in_Classic_Brown_Leather/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Womens_Authentic_Original_Boat_Shoe_in_Classic_Brown_Leather/geometry.png)

### 098. Womens_Bluefish_2Eye_Boat_Shoe_in_Linen_Natural_Sparkle_Suede_w34KNQ41csH

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.008251 | 0.000119612 | 72.90% | 99.92% | 0.011668 |
| TRELLIS.2 | 0.006716 | 0.000100999 | 83.07% | 99.33% | N/A |
| Hybrid | 0.011036 | 0.000249830 | 59.65% | 98.20% | 0.016771 |
| Pixal3D | 0.008393 | 0.000117661 | 70.06% | 99.85% | N/A |

CD-L1 从低到高：**TRELLIS.2 < WT < Pixal3D < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 的鞋身轮廓和鞋帮比例较好。WT 与 Pixal3D 的整体距离接近，前者背侧平滑、后者改变了部分面料颜色和鞋带；Hybrid 鞋头、后跟及鞋舌更不规则。均保留类别，但局部精度有差异。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Womens_Bluefish_2Eye_Boat_Shoe_in_Linen_Natural_Sparkle_Suede_w34KNQ41csH/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Womens_Bluefish_2Eye_Boat_Shoe_in_Linen_Natural_Sparkle_Suede_w34KNQ41csH/geometry.png)

### 099. Womens_Canvas_Bahama_in_White_UfZPHGQpvz0

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.017209 | 0.000480938 | 37.44% | 97.04% | 0.026346 |
| TRELLIS.2 | 0.010181 | 0.000195802 | 63.61% | 99.24% | N/A |
| Hybrid | 0.016704 | 0.000499988 | 40.02% | 95.68% | 0.056605 |
| Pixal3D | 0.014767 | 0.000384203 | 44.74% | 97.20% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < Hybrid < WT**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 较好补出不可见鞋头与系带，Pixal3D 次之。WT 的隐藏鞋面更平，Hybrid 鞋口/鞋舌和系带趋于粘连、输入视角开口细节减弱。背视更能解释三者在整体形状上的差距。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Womens_Canvas_Bahama_in_White_UfZPHGQpvz0/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Womens_Canvas_Bahama_in_White_UfZPHGQpvz0/geometry.png)

### 100. Womens_Cloud_Logo_Authentic_Original_Boat_Shoe_in_Black_Supersoft_cZR022qFI4k

| 方法 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ | SSI AbsRel ↓ |
| --- | --- | --- | --- | --- | --- |
| WT | 0.009466 | 0.000139609 | 62.20% | 99.97% | 0.010304 |
| TRELLIS.2 | 0.007000 | 0.000097507 | 81.13% | 99.61% | N/A |
| Hybrid | 0.010992 | 0.000250467 | 61.54% | 98.06% | 0.017206 |
| Pixal3D | 0.007845 | 0.000104563 | 73.81% | 99.81% | N/A |

CD-L1 从低到高：**TRELLIS.2 < Pixal3D < WT < Hybrid**；F@0.01 最高：**TRELLIS.2**。

TRELLIS.2 与 Pixal3D 的完整船鞋形状较接近 GT，前者更准。Hybrid 鞋头/鞋身拉长、侧面细节改变，WT 隐藏鞋面平滑；外侧绳带和缝线各有偏差。该例没有支持仅凭深色鞋面纹理判断严重几何失败。

[输入/原生方向/配准纹理](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Womens_Cloud_Logo_Authentic_Original_Boat_Shoe_in_Black_Supersoft_cZR022qFI4k/appearance.png) · [正/背/底灰模](/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/Womens_Cloud_Logo_Authentic_Original_Boat_Shoe_in_Black_Supersoft_cZR022qFI4k/geometry.png)
