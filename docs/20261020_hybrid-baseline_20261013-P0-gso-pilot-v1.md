# P0 基线分析与深度诊断

> 2026-11-07 历史记录说明
>
> 本文保留旧服务器实验的数值、分析和当时路径。新服务器已完成重跑并更新 experiments.xlsx，最新数值、差异和验收记录见 [恢复结果报告](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_recovery-results.md)。

2026-10-20。主体分析 `20261013-P0-gso-pilot-v1`：固定 10 个 GSO 调试样本，WT、TRELLIS.2、hybrid、Pixal3D，以及 shared-WT hybrid 对照，共 50 项；均单视图、seed=42。深度诊断另引用 R2 的 100 个样本，两个集合分开统计。P0 不用于总体显著性或原论文 Table 1 的复现结论。

## 关键结论

- **TRELLIS.2 的配准后形状最好，纹理仍有明显失败。** 它在四个主要方法中获得 8/10 项最低 CD-L1；文字和复杂包装图案失真未被几何指标反映。
- **当前 hybrid 没有稳定收益。** 9/10 项 CD-L1 差于 TRELLIS.2；复用同份 WT 后总体结果接近，不能只用 WT 预处理差异解释失败。
- **WT 的可见面布局较好，完整几何与绝对尺度仍有误差。** Hat 内腔额外点、Frozen 厚度偏差、MEAT 背面细节简化均有证据。其可见面颜色来自输入 RGB，不是生成纹理。
- **Pixal3D 对部分图案的保留优于 hybrid，但可能伴随几何失真。** Frozen、Olive 的改善成立；Horse 的破损、Olive/Frozen 的花纹状起伏也存在。不能据完整方法对比认定某个 conditioning 分支的因果作用。

## P0：方法对比

完整形状先经 GT 辅助 Sim(3) 配准，消除旋转、平移和正等比尺度误差；下表不能评价原生姿态或尺度。各方法均为相同 10 个物体的等权均值，距离按 GT 资产包围盒对角线归一化。

| 方法 / 配置 | 有效数 | CD-L1 ↓ | CD-L2 ↓ | F@0.01 ↑ | F@0.05 ↑ |
| --- | ---: | ---: | ---: | ---: | ---: |
| WT / defaults-v1 | 10/10 | 0.014764 | 0.000432 | 51.70% | 96.64% |
| TRELLIS.2 / defaults-v1 | 10/10 | **0.009740** | **0.000231** | **69.03%** | **98.84%** |
| Hybrid / defaults-v1 | 10/10 | 0.017195 | 0.000663 | 41.16% | 92.25% |
| Pixal3D / resolution1024-v1 | 10/10 | 0.014763 | 0.000435 | 49.19% | 96.81% |
| Hybrid / shared-wt-v1 | 10/10 | 0.017190 | 0.000646 | 40.74% | 92.55% |

WT 与 Pixal3D 的 CD-L1 均值仅差约 `1.05e-6`；逐样本 WT 在 7/10 项更低，不据均值末位排序。相机坐标与深度指标见附录 B；纹理结论来自逐图核验，本批没有 OCR 或 RGB 保真分数。

## P0：逐样本核对

外观图第一行只居中、统一显示尺寸，保留原生朝向；后两行经 GT 配准。几何图关闭纹理。对称物体的 ICP 可能翻面，不能用配准后的图案朝向判断原生姿态。

| 样本 | 核对结论与定量支持 | 证据 |
| --- | --- | --- |
| `DPC_tropical_Trends_Hat` | **内腔额外点成立，但未证明填成实体。** WT 是六层点集，尚未经 hybrid ray fill；GT 也有内衬。配准后 L0/L5 单向点距为 0.006745/0.014450，整体 CD 却与 TRELLIS.2 几乎相同，掩盖了局部问题。 | [分层][hat-layers]、[截面][hat-sections] |
| `Frozen_Olafs_In_Trouble_PopOMatic_Game` | **WT 可见面贴合好，但不能说生成方法同等失败。** Pixal3D 保留了可辨人物与棋盘，优于 TRELLIS.2/hybrid，仍有细节错误及图案浮雕。WT SSI AbsRel 仅 0.002430，完整形状 CD-L1 却为 0.031865，厚度错误明显。 | [外观][frozen-appearance]、[几何][frozen-geometry] |
| `Granimals_20_Wooden_ABC_Blocks_Wagon` | **Pixal3D 显示朝向改变，仍未对齐参考；conditioning 的单独作用未证实。** 该 ID 在原始包中实际对应开罐工具，缩略图与 OBJ 校验确认不是本次串样。Pixal3D CD-L1 0.013144，差于 TRELLIS.2 的 0.009578。 | [朝向][wagon-appearance]、[原始图][wagon-raw] |
| `HELICOPTER` | **文字失败成立。** `PlanToys` 标记变为伪字形、条纹或被省略；TRELLIS.2 的 CD-L1 仍最低（0.007861），说明形状分数对文字不敏感。WT 字样来自输入 RGB。 | [文字与外观][helicopter-appearance] |
| `Horse_Dreams_Pencil_Case` | **复杂图案失真、Pixal3D 几何破损成立。** 凹陷、凸条和附件变形在 decoded PLY 中已有，不能只归因于 GLB 导出。Pixal3D CD-L1 0.031795、F@0.05 82.76%；hybrid 的 F@0.05 也仅 84.24%。未据此宣称完成拓扑检查。 | [外观][horse-appearance]、[导出前后][horse-export] |
| `MEAT_SET` | **背面细节简化成立，同时有局部缺失。** 同表示 GT 点云对照仍可见差异，但六层点距未呈递增趋势，不能认定遮挡平滑机制。Pixal3D 是本批唯一在该样本上 CD-L1 优于 TRELLIS.2；hybrid 深度覆盖率仅 84.70%。 | [几何][meat-geometry]、[分层][meat-layers] |
| `Metallic_Pewter_Tieks_Italian_Leather_Ballet_Flats` | **Hybrid 有局部缺陷，“其他都好”过强。** 鞋口连接与填充物失真在 decoded PLY 已存在；其他方法也有鞋头起伏或虚构鞋底纹。GT 本来有纸填充物。整体 CD-L1 为 WT 0.011978 < hybrid 0.012381 < TRELLIS.2 0.014341 < Pixal3D 0.017307。 | [几何][flats-geometry]、[导出前后][flats-export] |
| `Olive_Kids_Paisley_Pencil_Case` | **Pixal3D 花纹保持优于 hybrid，但产生花纹状几何起伏。** CD-L1 0.011510 优于 hybrid 0.024651，仍差于 TRELLIS.2 0.009180；shared-WT 也未消除差距。 | [外观][olive-appearance]、[浮雕核验][olive-export] |
| `SCHOOL_BUS` | **文字失败成立，hybrid 还叠加几何误差。** TRELLIS.2/Pixal3D 的 F@0.01 为 98.62%/93.18%，仍未正确保留 `SCHOOL BUS`；hybrid 仅 34.33%。 | [文字与外观][bus-appearance]、[几何][bus-geometry] |
| `Schleich_Hereford_Bull` | **Hybrid 头颈、躯干和腿部关系失真，非空输出。** 缺陷在 decoded PLY 已有，shared-WT 未修复；hybrid CD-L1 0.019685，TRELLIS.2 0.007574。默认 hybrid 深度覆盖率 94.74%，未过门槛。 | [几何][bull-geometry]、[导出前后][bull-export] |

## 深度诊断：现象与原因边界

### 1. WT 可见面平均偏近，全层 Z 跨度平均偏大

统计直接读取 `prediction.npz` 中已反标准化的 `xyz[..., 2]`，与对应 GT 相机 Z 比较，不从颜色反推。**L0 平均 Z 表示深度位置，`max(Z)−min(Z)` 表示跨度**，两者也不同于三维包围盒大小；单位是本实验 GT 归一化单位，不是米。

| 诊断量 | P0（10） | R2（100） |
| --- | ---: | ---: |
| L0 平均偏差 `mean(Z_WT−Z_GT)` | −0.177941 | −0.113879 |
| L0 原始 MAE | 0.179558 | 0.204400 |
| 全层 Z 跨度 / GT 完整 Z 跨度，样本均值 | **1.222** | **1.213** |
| 全层 Z 跨度大于 GT 的样本数 | 9/10 | 78/100 |
| 全层 1%–99% Z 跨度 / GT 完整跨度，均值 | 1.088 | 1.093 |
| 同射线厚度比 `mean(Z5−Z0)_WT / mean(Z5−Z0)_GT`，样本均值 | 1.333 | 1.264 |
| L0 拟合 `aZ+b` 后的厚度比 / 有效数 | 1.134 / 10 | 1.069 / 99 |

极端点放大了全范围，但 L0 校准也没有同时消除深层残差。Frozen 的原始厚度比 **2.090**，L0 校准后仍为 **1.747**；此时 L0/L5 MAE 为 **0.00403/0.11066**。这些数值定位了误差，尚未解释网络为何产生它。

### 2. 三样本裁剪对照：占幅增大时预测平均 Z 减小

固定权重、seed=42、20 步、504²、六层、bf16、灰背景128、mask 腐蚀0，仅改变裁剪配置。占幅指物体包围框长边占最终输入边长的目标比例，非面积百分比；比例越大，裁剪越紧。

| 前景占幅 | Hat 平均 L0 Z | Frozen 平均 L0 Z | Bus 平均 L0 Z |
| --- | ---: | ---: | ---: |
| 50% | 1.853747 | 2.012988 | 1.963041 |
| 默认 66.7% | 1.410122 | 1.451785 | 1.545153 |
| 80% | 1.268457 | 1.322950 | 1.391438 |

每种配置按实际裁剪后的 K 重渲染 GT；三例 GT 平均 Z 的变化均小于 0.0004。**已观察到的是这三个样本、该 seed 下对裁剪预处理整体的敏感性。** 裁剪同时改变占幅、RGB 重采样、mask/边界和噪声对应位置，尚未分离各因素，也未检验多 seed。关闭裁剪改善 Hat/Frozen 的距离偏差，却使 Bus 更近，不能直接作为通用修复。

**代码事实：** XYZ 分支不以真实 K 或裁剪参数为条件；15 项推理均正确执行 `Z=0.706423·Z_norm+1.904278`，默认三例与原 P0 输出逐值一致，排除了本地保存时漏做反标准化的解释。**待验证假设：** 模型可能学到了占幅—尺寸—距离关系，但“把裁剪放大解释为靠近”、缺少 K 的因果作用，以及训练分布对总体偏差的贡献，都尚未证实。

### 3. 绝对 Z 与深度颜色的差异

**视觉观察与读图范围：** 用户反馈可视化整体看着较一致，但此前 WT 与 GT/其他方法的深度颜色明显不同。`depth_color_diagnostic.png` 的三行是 Hat/Frozen/Bus 的默认裁剪结果，五列是独立色标、统一色标及 L0 SSI 对照，**不是三种裁剪配置的对照图**；此前将该视觉反馈写成“裁剪结果一致”缺乏依据。图像按输入像素绘制 L0 Z，不用预测 X/Y 重投影，WT mask 来自输入 alpha，因此轮廓接近不证明完整三维形状一致；第五列使用 GT 拟合 `aZ+b`，仅诊断可见面残差。

[Viewer 配色](../viewer_utils/glb.py)对每项结果分别用 `t=(z−z_min)/(z_max−z_min)` 归一化，且展示时平移居中。正仿射变换 `z′=az+b` 在端点同步重算时不改变颜色，因此**视觉接近与平均 Z 改变可以并存**；这不证明三种裁剪输出之间只有整体缩放/平移。

**数值对应：** Frozen 默认输出的完整 Z 跨度为 GT **0.4314**、WT **0.6918**；L0 的1%–99%跨度占各自完整跨度的 **62.6% / 44.9%**。WT 可见面覆盖了自身色条中更窄的一段，这种相对比例差异不能通过整体 `aZ+b` 消除。WT 色条取六层点，GT 取完整 mesh，局部/后层几何及极端点均影响相对配色。见[逐项数值][z-inference]与[固定/独立色标对照][z-colors]。

**证据边界：裁剪实验证明本次平均深度对预处理敏感，尚未解释最初观察到的 WT 颜色分布差异。** 后者已有相对深度结构和层间厚度差异的数值支持，但其生成原因仍未确定。

原生 TRELLIS.2/Pixal3D 保留规范坐标，其显示 Z 也不是输入相机 Z。比较绝对深度需要共同相机系与固定色标；低 Sim(3) 或 SSI 误差不能证明原生尺度正确。X/Y 展开和三维包围盒的补充统计见附录 C.1。

## 后续验证重点

固定同份 WT，逐阶段检查层有效性、层间插值、体素填充和 Stage 2，定位 hybrid 的空腔/薄结构损伤；针对文字与复杂图案补充可见面评价。Z 的原因验证需分离裁剪带来的占幅、重采样和 mask 变化，并增加 seed。以上均为待做对照，当前结果没有确立唯一机制。

## 附录 A：配置与评价协议

| 方法 | 实际配置 |
| --- | --- |
| WT | object-model-6layer；504²；20 steps；灰背景128；alpha erosion=0 |
| TRELLIS.2 | 原生 Stage 1→shape→texture；1024_cascade；各 stage 12 steps；上游 alpha 裁剪与黑背景 |
| Hybrid | WT 20 steps；黑背景、erosion=2；ray_steps=4；32³ 稀疏结构替换 Stage 1；1024_cascade，shape/texture 各12 steps |
| Shared-WT hybrid | 复用 WT 默认输出（10/10 SHA-256 相同）；其余同 hybrid |
| Pixal3D | main 实现，resolution1024-v1 / 1024_cascade，各 stage 12 steps；MoGe2 FoV + normalized cube；上游 alpha/RMBG 裁剪与黑背景；独立权重与投影条件 |

Mesh 纹理4096、GLB decimation target=1,000,000；shape/texture guidance=7.5/1.0。Pixal3D 为1024配置，不是其上游默认1536或 Direct3D-S2 分支。有效参数以各项 `config.json` 和[源码锁](../compare_methods/pixal3d/sources.lock)为准；通用 JSON 中原生 TRELLIS.2 的 WT/腐蚀/ray 参数不参与执行。Hybrid Stage 2 仍接收图像条件，不能称为没有纹理条件。

- **随机性：** 推理 seed=42、batch=1，每样本在对应 pipeline 入口重置 RNG；跨方法同 seed 不等于同 latent。划分 seed=20261013；视图、采样 seed 按用途和 asset_id 派生，保存在 `camera.json` / `metrics.json`，无 best-of-N。
- **形状：** `gso-shape-sim3-v1`，GT 资产 AABB 对角线=1；24个 proper rotation 初始化、最多100次 ICP，允许正尺度，禁止镜像。配准10,000点、评价100,000点分开；WT 有效点去重抽样，mesh 按面积采样。CD-L1/L2 分别为双向最近邻欧氏/平方欧氏距离均值的平均，含 `1/2`。完整定义见[评价协议](evaluation_protocol.md)。
- **产物：** 形状评测使用 `decoded_mesh.ply`，早于 GLB 导出，但 `decode_latent()` 内已调用 `fill_holes()`；缺陷在该文件中出现只能排除 GLB 导出是唯一来源。
- **核验：** 50项形状指标由保存的评价点与配准重算，差异≤`1e−10`；10/10 GT RGB 重渲染与原输入逐像素一致。证据图按保存坐标变换绘制，无单例手工旋转；WT 用点云，GT/生成结果用 mesh，Hat/MEAT 另有同表示对照。纹理图仅显示 base color。

## 附录 B：P0 详细指标

每格为 **CD-L1×1000 / F@0.01 (%)**，简称对应正文完整 ID；shared-WT 是补充对照。

| 样本 | WT | TRELLIS.2 | Hybrid | Pixal3D | Hybrid shared-WT |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hat | 8.189 / 73.55 | 8.184 / 77.25 | 13.694 / 54.53 | 9.602 / 69.97 | 12.515 / 59.57 |
| Frozen | 31.865 / 7.36 | 2.966 / 100.00 | 18.249 / 32.26 | 16.304 / 24.86 | 20.038 / 27.39 |
| Wagon | 11.983 / 54.46 | 9.578 / 66.12 | 10.957 / 58.31 | 13.144 / 46.50 | 12.370 / 50.02 |
| HELICOPTER | 11.996 / 59.93 | 7.861 / 78.52 | 12.239 / 55.01 | 13.098 / 54.77 | 12.635 / 54.32 |
| Horse | 24.321 / 25.36 | 18.703 / 29.62 | 23.742 / 25.64 | 31.795 / 7.64 | 23.771 / 24.08 |
| MEAT | 19.291 / 38.49 | 15.224 / 55.94 | 17.268 / 38.73 | 12.887 / 57.51 | 17.799 / 36.94 |
| Flats | 11.978 / 50.77 | 14.341 / 45.73 | 12.381 / 51.78 | 17.307 / 38.93 | 12.559 / 50.59 |
| Olive | 10.177 / 58.53 | 9.180 / 61.82 | 24.651 / 27.24 | 11.510 / 53.79 | 21.251 / 33.29 |
| Bus | 6.091 / 91.38 | 3.788 / 98.62 | 19.081 / 34.33 | 5.176 / 93.18 | 18.806 / 38.34 |
| Bull | 11.752 / 57.15 | 7.574 / 76.67 | 19.685 / 33.82 | 16.809 / 44.72 | 20.154 / 32.82 |

Frozen 的100.00%为舍入，原值99.9955%，不代表零几何误差。完整精度、其余指标与样本间标准差见[逐项 TSV][p0-tsv]及[审计 JSON][p0-audit]。

| 相机/深度指标 | WT | Hybrid | Shared-WT hybrid |
| --- | ---: | ---: | ---: |
| 相机系 CD-L1 ↓（均10/10） | 0.080735 | 0.058923 | 0.070087 |
| 相机系 F@0.05 ↑（均10/10） | 38.47% | 50.15% | 44.25% |
| 轮廓 IoU ↑（均10/10） | 98.82% | 48.86% | 45.50% |
| SSI AbsRel ↓ / 有效数 | 0.011710 / 10 | 0.024427 / 8 | 0.023329 / 9 |
| 共同8样本 SSI AbsRel ↓ | 0.010879 | 0.024427 | 0.022933 |

相机系 CD 混合位置、方向、尺度与形状误差。WT mask 来自输入 alpha，高 IoU 不证明独立分割或完整姿态准确；SSI 允许正尺度和位移拟合。默认 hybrid 的 MEAT/Bull、shared-WT 的 MEAT 未过95%深度覆盖门槛，相关值缺失；共同8样本排除 MEAT/Bull。TRELLIS.2/Pixal3D 无经验证的原相机映射，以上指标为 N/A。[缺失清单与配对结果][p0-pairs]。

## 附录 C：尺度诊断与输出索引

### C.1 三维显示大小与 X/Y（不用于解释 Z）

显示尺寸比为各物体 `r_D=对角线(AABB_预测)/对角线(AABB_GT)`，再跨样本平均。GT 在资产坐标归一化为对角线1，旋转后不再次归一化；显示 GT 对角线均值为 P0 1.089、R2 1.127，不能直接以1作分母。

| 诊断量 | P0 | R2 |
| --- | ---: | ---: |
| WT 显示尺寸比均值 | 1.296 | 1.292 |
| Hybrid 恢复 WT 坐标后的尺寸比均值 | 1.277 | 1.282 |
| TRELLIS.2 / Pixal3D 尺寸比均值 | 1.150 / 1.194 | 1.157 / 1.147 |
| WT 的1%–99%包围盒 / 完整 GT 包围盒，中位数 | 1.172 | 1.209 |
| GT 裁剪后 / WT 拟合 `fx`，各自中位数（px） | 860.94 / 531.19 | 733.93 / 526.83 |
| 保留 WT Z、用 GT K 重建 X/Y 后的尺寸比均值 | 1.016 | 1.041 |

拟合 `K_WT` 的像素回投 RMSE 均值为0.219/0.228 px，110/110项焦距短于 GT；`X=(u−cx)Z/fx` 解释相同 Z 下较短焦距对应更宽的 X/Y。换 K 的诊断只改变 X/Y，Z 不变是构造结果，不能据此证明或排除 Z 的上游成因，也不是修复后的成绩。

Viewer 保留数值尺寸；hybrid 开启 `Restore WT frame` 时恢复的是自身 WT 上游坐标，未校准到 GT。关闭后其尺寸比变为1.089/1.054，比较口径不同。AABB 还受朝向影响，不能按原生 TRELLIS.2/Pixal3D 的比值接近1判定尺度更准。完整450项统计及配准/坐标记录见下表。

### C.2 Z 指标与验证口径

- **聚合：** P0/R2 分开、样本等权；每个比值先逐样本计算，再取均值。L0 使用双方共同有效像素；全层范围为 WT 六层有效点与完整 GT 相机系 mesh 的 Z 跨度之比。
- **逐层 GT：** 按同一相机做 depth peeling，取前六次交点，不足时末次交点向后填充；射线厚度为 `Z5−Z0`。L0 拟合 `aZ+b` 后统一应用六层，仅保留正尺度；R2 的 Razer 鼠标 SSI 尺度非正，相关项留空，有效99/100。
- **裁剪/背景配置：** 三例各5项：`baseline`=占幅2/3、灰背景128；`crop50/crop80`=占幅50%/80%；`whole`=不裁剪直接缩放；`black`=占幅2/3、黑背景0。其余固定参数见正文，每项实际 K、seed 与 GT/预测均值保存在 JSON。
- **核验：** 110/110个 L0 重渲染与原 GT 逐值一致；seed=42 的320条 P0 内部射线经双精度求交复查，六层最大误差9.22e−5。335份原始来源文件校验未变。诊断没有覆盖基线预测或成绩。

### C.3 完整明细与输出路径

本文保留关键表格，逐项完整数值引用原 TSV/JSON；诊断记录不再写入用户维护的 `experiments.xlsx`。

| 内容 | 输出与复现入口 |
| --- | --- |
| P0 原始实验 | [结果目录][p0]：`samples/<asset>/<method>/<config>/seed-0042/`；R2 主分析见[结果报告](20261014_hybrid-baseline_results.md) |
| P0 外观/几何核验 | [证据目录][p0-evidence]：逐样本外观、去纹理、分层、导出检查；`verification.json` 与 `reproduction/` 保存核验及脚本 |
| 450项显示尺度统计 | [逐项 TSV][scale-tsv]、[汇总][scale-summary]；[诊断目录][scale-root]包含相机/坐标记录、核验及复现脚本 |
| 原输出 Z 统计 | [汇总][z-summary]、[逐项/逐层 JSON][z-records] |
| 15项裁剪/背景推理 | [逐项 TSV][z-ablation]、[完整 JSON][z-inference]；[推理目录][z-inference-dir]按 `<sample>/<variant>/` 保存 `input.png`、`prediction.npz`、`metrics.json` |
| P0 10项 / R2 100项逐层诊断 | [逐项 TSV][z-layers]、[完整 P0 JSON][z-p0-layers]、[完整 R2 JSON][z-r2-layers]、[汇总][z-root-summary]；[诊断根目录][z-root]的 `layers/`、`r2/layers/` 保存逐样本指标和 GT 层数据，`reproduction/` 保存配置/脚本入口 |

[p0]: /data1/LiuShuqi/output/world_tracing/experiments/20261013-P0-gso-pilot-v1
[p0-evidence]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020
[p0-tsv]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/per_sample.tsv
[p0-audit]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/audit.json
[p0-pairs]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/comparisons.json
[hat-layers]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/DPC_tropical_Trends_Hat/wt_layers.png
[hat-sections]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/DPC_tropical_Trends_Hat/wt_sections.png
[frozen-appearance]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Frozen_Olafs_In_Trouble_PopOMatic_Game/appearance.png
[frozen-geometry]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Frozen_Olafs_In_Trouble_PopOMatic_Game/geometry.png
[wagon-appearance]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Granimals_20_Wooden_ABC_Blocks_Wagon/appearance.png
[wagon-raw]: /data1/LiuShuqi/data/world_tracing/raw/gso/objects/Granimals_20_Wooden_ABC_Blocks_Wagon/thumbnails/0.jpg
[helicopter-appearance]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/HELICOPTER/appearance.png
[horse-appearance]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Horse_Dreams_Pencil_Case/appearance.png
[horse-export]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Horse_Dreams_Pencil_Case/pixal3d_export_check.png
[meat-geometry]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/MEAT_SET/geometry.png
[meat-layers]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/MEAT_SET/wt_layers.png
[flats-geometry]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Metallic_Pewter_Tieks_Italian_Leather_Ballet_Flats/geometry.png
[flats-export]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Metallic_Pewter_Tieks_Italian_Leather_Ballet_Flats/wt_trellis2_export_check.png
[olive-appearance]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Olive_Kids_Paisley_Pencil_Case/appearance.png
[olive-export]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Olive_Kids_Paisley_Pencil_Case/pixal3d_export_check.png
[bus-appearance]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/SCHOOL_BUS/appearance.png
[bus-geometry]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/SCHOOL_BUS/geometry.png
[bull-geometry]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Schleich_Hereford_Bull/geometry.png
[bull-export]: /data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/Schleich_Hereford_Bull/wt_trellis2_export_check.png
[scale-root]: /data1/LiuShuqi/output/world_tracing/validation/gso-scale-analysis-20261020
[scale-tsv]: /data1/LiuShuqi/output/world_tracing/validation/gso-scale-analysis-20261020/per_run.tsv
[scale-summary]: /data1/LiuShuqi/output/world_tracing/validation/gso-scale-analysis-20261020/summary.json
[z-summary]: /data1/LiuShuqi/output/world_tracing/validation/gso-scale-analysis-20261020/z-diagnosis/summary.json
[z-records]: /data1/LiuShuqi/output/world_tracing/validation/gso-scale-analysis-20261020/z-diagnosis/per_run.json
[z-root]: /data1/LiuShuqi/output/world_tracing/validation/z-root-cause-20261020
[z-root-summary]: /data1/LiuShuqi/output/world_tracing/validation/z-root-cause-20261020/summary.json
[z-ablation]: /data1/LiuShuqi/output/world_tracing/validation/z-root-cause-20261020/ablation.tsv
[z-inference]: /data1/LiuShuqi/output/world_tracing/validation/z-root-cause-20261020/inference_records.json
[z-inference-dir]: /data1/LiuShuqi/output/world_tracing/validation/z-root-cause-20261020/inference
[z-layers]: /data1/LiuShuqi/output/world_tracing/validation/z-root-cause-20261020/layers.tsv
[z-p0-layers]: /data1/LiuShuqi/output/world_tracing/validation/z-root-cause-20261020/layers_records.json
[z-r2-layers]: /data1/LiuShuqi/output/world_tracing/validation/z-root-cause-20261020/r2/layers_records.json
[z-colors]: /data1/LiuShuqi/output/world_tracing/validation/z-root-cause-20261020/depth_color_diagnostic.png
