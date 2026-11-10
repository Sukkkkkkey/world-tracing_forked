# 初版评测协议结果

2026-11-10 汇总。本文将已恢复的单 seed 评测及四视角扩展统称为 protocol v0，具体计算定义见 [初版协议](evaluation_protocol_v0.md)。完整逐样本表存于 [初版工作簿](20261110_experiment_baseline_protocol_v0.xlsx)，跨服务器差异见 [结果复现](20261105_recovery-results.md)。

## 评测条件

主定量集为 R2 的 100 个固定 GSO 资产，每资产一个输入视图、seed=42。WT 使用六层有效点云，TRELLIS.2、Hybrid、Pixal3D 使用首次补洞后、GLB 导出前的 decoded mesh。GT AABB 对角线 D=1，完整形状使用 GT 辅助正 Sim(3)。逐资产等权，配对 95% 区间按资产 bootstrap 10,000 次。

初版 Chamfer/F-score 覆盖完整几何。输入可见与遮挡区域的三维 CD/F-score 分解待计算。本文输入方向渲染与 SSI 深度提供各自的辅助证据。P0 10 资产用于校准，R1 用于定性观察。本项目数据和协议与论文 Table 1 存在差异，论文采用的 best-of-8 将在新协议中补充。[初版协议](evaluation_protocol_v0.md) [World Tracing](https://arxiv.org/html/2606.13652v1#S4)

## 完整几何

四方法均有 100/100 有效资产。

| 方法 | CD-L1 ↓ | F@0.01 ↑ | CD 最优资产数 |
| --- | ---: | ---: | ---: |
| TRELLIS.2 | 0.009297 | 70.75% | 60 |
| Pixal3D | 0.011796 | 64.13% | 29 |
| WT | 0.013285 | 56.94% | 10 |
| Hybrid | 0.017753 | 44.30% | 1 |

Hybrid−WT 的 CD 差为 +0.004468，95% 区间 [0.002987, 0.006061]，73/100 个资产更差。Hybrid−TRELLIS.2 为 +0.008456，区间 [0.006989, 0.010040]，89/100 个资产更差。排除两个超大 Hybrid 样本后，后一差值仍为 +0.008395，87/98 个资产更差。[配对统计](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/baseline-analysis-20261110/statistics.json>)

**可确认** 当前配置下 Hybrid 的完整形状误差高于 WT，WT 高于 TRELLIS.2，Pixal3D 位于 TRELLIS.2 与 WT 之间。WT defaults 与 Hybrid defaults 的背景和 mask 腐蚀设置不同，差值包含整个流程的影响。P0 shared-WT 对照中，WT/Hybrid CD 分别为 0.013857/0.017740，也观察到后续流程的形状损失。

## 输入方向与四视角渲染

四方法共同使用 surfel 表示，mesh 采用 2M 面积采样点，网格尺寸 0.002D、面片半径 0.003D。渲染复用完整形状的配准变换。初版四方向为输入方位加 0°、90°、180°、270°，仰角 20°、512²、FoV 40°。下表每项为 100 个资产的均值。

| 范围 | 方法 | 深度 MAE / D ↓ | 轮廓 IoU ↑ | 法向角误差 / ° ↓ | 法向覆盖率 ↑ |
| --- | --- | ---: | ---: | ---: | ---: |
| 输入方向 | TRELLIS.2 | 0.020552 | 91.72% | 19.00 | 96.48% |
| 输入方向 | Pixal3D | 0.028564 | 89.33% | 22.21 | 94.97% |
| 输入方向 | WT | 0.037186 | 87.48% | 24.21 | 81.97% |
| 输入方向 | Hybrid | 0.038906 | 82.69% | 25.52 | 96.29% |
| 四视角 | TRELLIS.2 | 0.021318 | 90.04% | 20.09 | 95.42% |
| 四视角 | Pixal3D | 0.028764 | 86.98% | 23.17 | 93.44% |
| 四视角 | WT | 0.041859 | 85.06% | 27.63 | 75.87% |
| 四视角 | Hybrid | 0.041532 | 81.28% | 27.56 | 94.77% |

输入方向沿用原始 GT 视锥缩放到 512²，与实际裁剪输入的 K_crop 评测范围有差异。此条件下 TRELLIS.2−WT 深度 MAE 为 −0.016634D，区间 [−0.021784, −0.011435]，87/100 个资产更低。**可确认** 配准后输入方向的这项渲染比较支持 TRELLIS.2 优于 WT。**待确认** 实际裁剪视锥中的可见三维几何排名。[输入方向统计](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/evaluation-review-20261110/input-view.json>)

四视角中 Hybrid−WT 深度差的区间为 [−0.003690, 0.002997]，法向角误差差的区间也跨零。WT 法向覆盖率更低，有效交集上的误差需要同时结合覆盖率解释。原生三角面渲染的 TRELLIS.2/Pixal3D/Hybrid 深度 MAE 为 0.021589/0.029262/0.041570。GT 转 surfel 本身带来平均 0.000572D 深度误差和 6.26° 法向误差，极端 Hybrid 样本还存在更大的表示转换影响。[多视角汇总与校准](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/multiview/ed7c00868a202db3de37/>)

P0 50 个、R2 400 个运行完成多视角评测，适用指标失败数为 0。冻结 revision 为 `ed7c00868a202db3de37`，171 项测试通过，3,755 个文件摘要核验通过。原生/surfel 渲染、浮点深度/法向/mask、逐视角统计及源码快照由运行目录 `multiview.json` 索引。[最终审计](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/evaluation/multiview/ed7c00868a202db3de37/final_audit.json>)

## WT 尺度与原生坐标

R2 WT 的 CD-L1 从原生坐标 0.110963，变为仅绕原点缩放 0.065244，再变为完整 Sim(3) 后 0.013285。Sim(3) 尺度中位数为 0.7598，范围 0.5761–0.9621。单独尺度拟合仍有明显残差，平移、内参映射和形状误差均需进一步分解。[相机诊断](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/evaluation-review-20261110/wt-camera.json>)

WT 的旧轮廓 IoU 98.79% 继承输入 alpha mask。真实 XYZ 用 GT 内参重投影的平均误差为 48.41 px，使用拟合内参降至 0.216 px。原生指标可用于诊断相机、位置与尺度约定，配准后指标用于当前形状比较。物理尺度准确性需要已知单位与相机约定。[内参诊断](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/evaluation-review-20261110/wt-intrinsics.json>)

SSI 只覆盖 WT 与 Hybrid，当前有效数为 99/100、80/100。两方法共同有效 79 个资产的 AbsRel 为 0.013214、0.028135。TRELLIS.2 的输入方向结论使用上节四方法统一渲染结果。

## 输出膨胀与 GLB

| R2 方法 | 面数中位数 / 百万 | P95 / 百万 | 最大值 / 百万 |
| --- | ---: | ---: | ---: |
| Pixal3D | 5.75 | 11.48 | 16.50 |
| TRELLIS.2 | 5.99 | 18.61 | 43.50 |
| Hybrid | 11.37 | 29.26 | 189.50 |

Hybrid 的 3M Antislip、Pokémon Dual Pack 分别为 1.895 亿、1.454 亿面，PLY 为 3.065/2.788 GB，配准后总三角形面积为 GT 的 67.79/33.34 倍。逐面检查的非法索引、非有限坐标和精确零面积面均为 0。额外面积已确认，内部壳层、重叠面与表面起伏的贡献待分解，体积变化尚未量化。[规模与几何审计](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/mesh-scale-20261108/>)

导出 GLB 后两例降至约 0.983/0.966 百万面，固定 decoded 配准后的面积比为 4.22/24.23。七份选择性检查中，导出对面积与 CD 的影响方向并不一致。导出包含 remesh、简化与投影，GLB 全量排名仍待测量。[阶段对照](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/evaluation-review-20261110/glb-stage.json>)

TRELLIS.2 论文讨论了薄结构、QEF 混叠和稀疏解码孔洞，官方 issue 也记录内部表面与 remesh 问题。当前文献证据尚不足以将本项目亿级面数和几十倍面积视为正常范围，具体原因需逐阶段支持域与几何对照。[论文](https://arxiv.org/html/2512.14692v1) [内部表面问题](https://github.com/microsoft/TRELLIS.2/issues/140) [Remesh 问题](https://github.com/microsoft/TRELLIS.2/issues/25)

## 评测局限与下一版

- 正 Sim(3) 允许尺度、平移和旋转调整，评价 GT 辅助对齐后的形状。点云与 mesh 的采样权重、ICP 局部最优和物体对称性仍影响公平性。
- 四视角覆盖有限，误差交集会遗漏缺失区域。共同 surfel 参数提供一致处理，同时引入采样与法向估计偏差。
- 单 seed 与选择性的 GLB 检查限制了生成稳定性和输出阶段的结论。旧完整几何指标的可见/遮挡分解仍为空缺。

新评测采用配准后的完整几何与输入可见几何为主结果，四方法各 8 个 seed，decoded/GLB 独立按完整 CD-L1 选取同组最优候选。输入相机使用裁剪变换后的固定 GT 内参，multi-view 增至 30 个球面方向并保存全部对应渲染图。原生坐标作为附加参照。[v0.5 协议](evaluation_protocol_v0.5.md)

v0.5 正式结果将在实现验收与新版 P0 校准后补录。先前 v2 试运行停于 79/700 项 seed-42 阶段评价，seed 43–49 待生成，该批中间值用于开发核验。合并前报告与试运行记录可由整理清单定位。[整理清单](</mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/archives/20261110-baseline-consolidation/manifest.json>)
