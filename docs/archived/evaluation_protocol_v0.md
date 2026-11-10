# 定量评估协议

代码核对日期为 2026-11-08。本文维护当前 GSO 评测实现的计算定义、适用范围和复现约定。CD、相机与 SSI 深度成绩见 `experiments.xlsx`，多视角几何结果见实验目录的 `multiview.json` 及输出根目录的 `evaluation/multiview/<revision>/<experiment>/summary.json`。案例分析见 `docs/`。本协议由项目自行定义，不能直接视为原论文 Table 1 的同协议复现。

## 1. 协议概览

| 协议 ID | 评价前允许的对齐 | 衡量内容 | 当前适用方法 |
| --- | --- | --- | --- |
| `gso-shape-sim3-v1` | GT 辅助旋转、平移、正等比缩放 | 去除整体姿态和尺度差异后的完整形状 | WT、TRELLIS.2、hybrid、Pixal3D |
| `gso-camera-native-v1` | 不做 GT 配准 | 原生相机坐标下形状、姿态、位置和尺度的综合偏差 | WT、hybrid |
| `gso-depth-ssi-v1` | 深度正尺度与偏移拟合 | 输入视角可见面的深度结构，另报覆盖率和轮廓 IoU | WT、hybrid |
| `gso-multiview-mesh-sim3-v1` | 复用 shape-sim3 的单个 Sim(3) | 原生三角形的四视角深度、法向与轮廓一致性 | TRELLIS.2、hybrid、Pixal3D |
| `gso-multiview-surfel-sim3-v1` | 同上 | 统一网格、PCA 法向和 surfel 渲染后的四视角几何一致性 | WT、TRELLIS.2、hybrid、Pixal3D |

各协议按其对齐约定解释。相机原生和 SSI 深度保持各自的对齐定义，两条多视角路线共用 shape-sim3 的配准矩阵。TRELLIS.2 缺少原输入相机位姿；Pixal3D 虽估计 FoV，但其规范化物体与原视图的尺度、位姿对应尚未建立，因此当前相机与深度指标为 **N/A**，不使用 GT 配准替它们补齐。

主要实现：[评测入口](../examples/evaluate_gso.py)、[几何与深度公式](../evaluation/geometry.py)、[方法适用性](../wt/experiment.py)。

## 2. 数据、单位与采样

当前 GSO v1 基线将排序后的 1030 个有效资产用 `PCG64(20261013)` 打乱，前 10 个为 P0 调试集，随后 100 个为 R2 评测集，其余保留；P0 不并入 R2。每资产一个固定视图，基线推理 seed=42，不做 best-of-N，不以其他资产替换失败样本。R1 object 图像没有配套几何 GT，以上指标不适用。

**尺度统一。** 完整 GT 资产在原资产坐标中的 AABB 对角线为 $D$。将其以包围盒中心居中，并等比缩放至 $D=1$，保存资产到评测坐标的变换；不按预测包围盒或旋转后的包围盒再次归一化。距离 `0.01` 表示原资产对角线的 1%，不是 1 cm；不宣称物理米制精度。

**评价对象与采样。**

| 对象 | 配准点 | 最终评价点 | 处理规则 |
| --- | ---: | ---: | --- |
| 完整 GT mesh | 10,000 | 100,000 | 按三角形面积均匀采样，两个用途使用不同 seed |
| 预测 mesh | 10,000 | 100,000 | 同上，读取 `decoded_mesh.ply` |
| WT 六层点图 | 最多 10,000 | 最多 100,000 | 汇集有效 XYZ，去除非有限值与完全重复坐标，再无放回抽样；不足时全部使用 |

WT 不重建表面、不使用 hybrid ray-fill 点、不按误差删除离群点。其配准点不足 10,000 时，GT 配准点取相同数量；GT 最终评价仍使用 100,000 点。两套 WT 抽样使用不同 seed，但可能选到重叠点，不保证集合互斥。

Mesh 评价位于 GLB 重网格化、简化、纹理烘焙之前；TRELLIS.2 解码流程已经执行 `fill_holes()`，因此保存的 decoder PLY 不能称为完全未经后处理的神经网络原始输出。WT 的像素采样与 mesh 的面积采样分布不同，应保留这一表示差异。

## 3. 完整形状：`gso-shape-sim3-v1`

### 3.1 GT 辅助配准

对预测点施加：

$$
p'=sRp+t,\qquad s>0,\quad R^\top R=I,\quad \det(R)=1.
$$

允许旋转、平移、等比缩放，禁止镜像。使用 24 个右手立方体旋转初始化，以两点云质心和均方根半径初始化平移、尺度；每个起点最多进行 100 次双向最近邻 Sim(3) ICP 更新。平方损失的平方根改善小于 `1e-6` 时停止该起点，损失上升也会触发停止；保留所有起点、所有已访问迭代中对称平方距离最小的变换。

配准只使用配准点，最终成绩在另一组评价点上计算。该数值优化仍可能受局部最优、对称物体和采样影响，不能保证找到全局最佳语义朝向。

### 3.2 CD 与 F-score

设对齐后的预测点集为 $P$，完整 GT 点集为 $Q$，最近邻距离为：

$$
d(p,Q)=\min_{q\in Q}\|p-q\|_2.
$$

$$
\mathrm{CD\!-\!L1}=\frac12\left[
\frac1{|P|}\sum_{p\in P}d(p,Q)+
\frac1{|Q|}\sum_{q\in Q}d(q,P)\right],
$$

$$
\mathrm{CD\!-\!L2}=\frac12\left[
\frac1{|P|}\sum_{p\in P}d(p,Q)^2+
\frac1{|Q|}\sum_{q\in Q}d(q,P)^2\right].
$$

| 展示名称 / 存储字段 | 方向与单位 | 含义 |
| --- | --- | --- |
| CD-L1 / `cd_euclidean_mean` | 越小越好；`GT_diagonal` | 双向平均表面偏差 |
| CD-L2 / `cd_squared_mean` | 越小越好；`GT_diagonal_squared` | 平方距离对严重偏离和离群点更敏感 |
| F@0.01 / `f@0.01` | 越大越好；`ratio` | 对角线 1% 容差下的准确性与完整性 |
| F@0.05 / `f@0.05` | 越大越好；`ratio` | 对角线 5% 容差下较宽松的形状吻合程度 |

这里 **L1 是欧氏距离的均值，不是逐坐标曼哈顿距离；L2 是平方距离的均值，不开平方；双向均含 1/2**。原始指标不暗乘 100 或 1000；图表若改变显示倍率，必须注明。

对阈值 $\tau\in\{0.01,0.05\}$：

$$
\mathrm{Precision}_\tau=\frac{\#\{p\in P:d(p,Q)<\tau\}}{|P|},\qquad
\mathrm{Recall}_\tau=\frac{\#\{q\in Q:d(q,P)<\tau\}}{|Q|},
$$

$$
F_\tau=\frac{2\,\mathrm{Precision}_\tau\,\mathrm{Recall}_\tau}
{\mathrm{Precision}_\tau+\mathrm{Recall}_\tau}.
$$

分母为零时 F=0，阈值判断为严格小于。Precision 反映预测中贴近 GT 的比例，Recall 反映 GT 被预测覆盖的比例；F 是二者调和平均，不是“正确重建的物体百分比”。当前仅保存 F，不单独保存 Precision、Recall。

这组指标覆盖完整表面，包括不可见区域；整体姿态和尺度误差已被配准吸收，不能据此宣称输入姿态恢复准确。

## 4. 相机坐标：`gso-camera-native-v1`

沿用第 3 节四个指标和阈值，但不做 GT 配准：

- WT：直接使用抽样后的原始相机 XYZ。
- Hybrid：对 decoder mesh 及采样点应用 `canon_inverse`，恢复到其上游 WT 预测的相机坐标；不对 decoder PLY 额外应用 GLB 轴转换。
- GT：将完整 GT 评价点按保存的 `T_world_to_camera` 变换至相机坐标。

相机坐标约定为 **RDF：X 向右、Y 向下、Z 向前**。这张表保留原生位置、方向和尺度差异，衡量它们与形状误差的综合作用；不单独计算旋转角、平移向量或尺度比误差。默认推理未输入 GT 标定，也不能把该表解读为已隔离相机假设的纯姿态评价。

## 5. 可见深度：`gso-depth-ssi-v1`

### 5.1 深度来源与对齐

GT 按与 WT 相同的裁剪窗口更新内参 `K_crop`，在 **504×504** 下重新光栅化，使用线性相机 Z，而非射线长度或 NDC depth。WT 直接读取 `xyz[0, ..., 2]` 与第 0 层 mask；hybrid 恢复相机坐标后，在同一 `K_crop` 下渲染最前方表面的 Z。

令 $M_p$、$M_g$ 分别为预测和 GT 的有效 mask；二者均要求深度有限且大于零。只在交集 $M=M_p\cap M_g$ 上进行最小二乘：

$$
(a,b)=\arg\min_{a,b}\sum_{i\in M}(a z_i+b-g_i)^2,\qquad
\hat z_i=a z_i+b.
$$

代码先做普通最小二乘，再检查 $a>0$，不是将负尺度截断为极小正数。拟合和误差评价使用同一交集；该协议消除全局深度尺度与偏移，不消除旋转或像素位置错位，也不衡量绝对距离精度。

### 5.2 指标与有效性

令 $e_i=|\hat z_i-g_i|$，$r_i=\max(\hat z_i/g_i,g_i/\hat z_i)$，下表误差均在 $M$ 内计算。

| 指标 / 存储字段 | 计算方式 | 含义与单位 |
| --- | --- | --- |
| MAE ↓ / `mae` | $\operatorname{mean}(e_i)$ | 平均深度误差；`GT_diagonal` |
| RMSE ↓ / `rmse` | $\sqrt{\operatorname{mean}(e_i^2)}$ | 更强调局部严重错误；`GT_diagonal` |
| AbsRel ↓ / `absrel` | $\operatorname{mean}(e_i/g_i)$ | 相对 GT 相机深度的误差；`ratio` |
| δ1 ↑ / `delta1` | $r_i<1.25$ 的像素比例 | 较宽松深度比例阈值下的通过率；`ratio` |
| δ2 ↑ / `delta2` | $r_i<1.25^2$ 的像素比例 | 更宽松的通过率；`ratio` |
| 覆盖率 ↑ / `depth_coverage` | $\#(M_p\cap M_g)/\#M_g$ | GT 可见区域被预测覆盖的比例；`ratio` |
| 轮廓 IoU ↑ / `silhouette_iou` | $\#(M_p\cap M_g)/\#(M_p\cup M_g)$ | 综合漏覆盖与多余投影区域；`ratio` |

以下任一情况使 MAE、RMSE、AbsRel、δ1、δ2 记为失败、数值留空：交集不足 3 个像素；拟合矩阵秩不足 2；$a\le0$；交集内任一对齐深度非正；覆盖率 **小于 95%**。不插值补洞。正常返回的深度质量失败仍保留覆盖率、IoU，两项各自有独立有效数。

GT 没有有效深度或评测抛出异常时，走整项评价失败分支，详情记录在 `evaluation_error.json`；不能保证仍有覆盖率或形状成绩。`depth_fit.json` 中的 `scale`、`shift`、`raw_mae` 为可用时保存的诊断字段，不属于当前工作簿主指标。

## 6. 多视角渲染几何一致性

两条路径使用相同四视角和原生 GT 深度、面法向、前景遮罩，衡量配准后的几何一致性。固定配置位于 `configs/multiview.json`。独立协议记录了参考文献、实现细节、参数选择、P0 验收和 R2 完成结果。[独立协议与校准](20261107_multiview-geometric-consistency.md)

### 6.1 几何与渲染

- 原生 mesh 路径使用 `decoded_mesh.ply` 的全部三角形和面法向。WT 的该项状态为 N/A。
- Surfel 路径对 mesh 进行 2,000,000 点面积采样，使用 `asset_seed("multiview_surface", asset_id)`。WT 汇集六层有效有限 XYZ 并去除完全重复点。
- 应用已有 `registration.json` 后，以世界原点固定的 0.002D 网格保留最靠近网格中心的真实点。PCA 邻域半径 0.006D，最多 32 点、至少 6 点，第二特征值与最大特征值比值至少 0.01。
- 每点渲染半径 0.003D 的有向正八边形 surfel。法向无效的点使用相同半径的相机朝向面片，其深度与遮罩仍参与评测，法向标记无效。
- 两条路径共用输入方位加 0°、90°、180°、270°的视角，仰角 20°，512²，水平 FoV 40°，距离 `0.5/sin(20°)×1.2`，near/far 为 0.01/10。
- RDF 相机坐标、像素中心、双面不透明最近 Z 光栅化。法向逐像素朝向相机。WT 渲染遮罩由变换后的 XYZ 几何投影生成，输入 alpha 用于最初的有效点筛选。

每个预测的四视角共享一个正向 Sim(3)。深度直接使用 camera-Z，距离单位为 GT 对角线 D。

### 6.2 指标

设 P、G 为预测和 GT 的深度有效遮罩，N 为双方深度及法向均有效的交集。深度误差使用 P∩G，法向误差使用 N。

| 字段 | 计算 | 方向 |
| --- | --- | --- |
| `depth_mae` | mean(abs(zp−zg))/D | ↓ |
| `depth_rmse` | sqrt(mean((zp−zg)²))/D | ↓ |
| `silhouette_iou` | count(P∩G)/count(P∪G) | ↑ |
| `depth_coverage` | count(P∩G)/count(G) | ↑ |
| `normal_mean_angle` | 单位法向夹角的均值，度 | ↓ |
| `normal_psnr` | RGB=(n+1)/2，−10log10(max(MSE,1e−12))，上限 120 dB | ↑ |
| `normal_lpips` | 全图法向 RGB，固定中性灰背景，预训练 AlexNet LPIPS v0.1 | ↓ |
| `normal_coverage` | count(N)/count(G) | ↑ |

另存 `normal_mse`、前景交集像素数、法向有效像素数和点邻域诊断。LPIPS 使用浮点法向图与 [−1,1] 输入范围。有效性按指标逐项记录。空预测的覆盖率和 IoU 为零，缺少交集的深度、角度和 PSNR 留空并记录原因。

逐资产先对四视角等权平均，要求相应指标四视角均有效。然后按方法、配置 ID、seed 和实际推理参数哈希对资产等权平均，汇总均值、总体标准差、有效数、失败数、N/A 数以及共同有效资产的成绩。完整失败的运行进入计划总数。包含运行来源的原始配置哈希保存在 `source_config_hashes`，相同参数的恢复重试归入同组。

### 6.3 采样影响与复现

同时保存每份 mesh 的 surfel 对原生渲染误差、两条路径相对 GT 的配对分数差，以及 GT 的 surfel 对原生渲染误差。Surfel 的局部平滑、有限支撑半径和 WT 观测密度均会影响成绩，需结合这些诊断解释比较。

P0 的 50 个运行在冻结配置下全部完成，10 个 GT 通过校准。R2 的 400 个运行全部完成，原生 mesh 路径 300 份、surfel 路径 400 份，两套协议均有 100 个共同有效资产，适用指标失败数为 0。最终 171 项 Python 测试通过，文件哈希审计与 30 组独立数值复算通过。

本轮渲染数据 revision 为 `ed7c00868a202db3de37`，保存配置、环境与权重哈希及渲染源码归档。每份结果保存预测、GT、配准和运行元数据哈希及四视角浮点渲染图，支持校验后续跑。汇总源码独立归档，记录在 `summary.json` 的 `aggregation` 中。汇总按实际推理参数分组，渲染数据可用 `examples.summarize_multiview` 重新校验并统计。

## 7. 汇总与比较

先计算逐资产指标，再在相同实验、方法、配置、seed 下对有效样本取**等权算术均值**，不将所有资产的点或像素拼接计算。工作簿还按实际参数摘要区分配置，防止同名配置、不同参数被合并。

- 失败、不适用、待评价不填零，不进入均值；同时保留有效 `n / total`、失败数和原因。失败率为失败数除以该组总数，N/A 与失败分开。工作簿的 `total` 来自已登记 run 记录，不使用可能过期的 manifest 计划数量；尚未登记的任务不会自动补入分母，应对照输入清单核查执行范围。
- 工作簿批注中的 `statistics.pstdev` 是有效资产成绩的总体标准差，反映物体间差异，不是均值的标准误或置信区间；当前导出未计算 bootstrap 区间。
- 工作簿“共同有效深度”取相同 seed 的 WT `defaults-v1` 与 hybrid `defaults-v1` 中，MAE、RMSE、AbsRel 全部有效的资产交集。`shared-wt-v1` 和其他配置不会自动进入该交集。
- 形状比较若出现方法间失败集合不同，需另报明确方法/配置集合的共同有效结果，不能把各自成功均值称为配对比较。`evaluation.records.summarize` 支持指定形状比较集合，默认集合为三方法 `defaults-v1`；加入 Pixal3D 时须显式指定其配置。

比较深度时优先查看**共同有效集合的误差、各方法覆盖率和失败率**，避免成功样本难度不同造成误读。推理完成、评测流程完成、单个指标有效是三种状态：`run.json.status=complete` 和 `metrics.json.evaluation_status=complete` 均不保证所有深度指标有效，应读取逐指标 `status`。

## 8. 解释边界

| 研究问题 | 当前可以参考的证据 | 尚未覆盖或需要注意 |
| --- | --- | --- |
| 完整形状、细结构 | 配准后 CD-L1、F@0.01；CD-L2 辅助识别严重偏差 | 面积小的细杆、孔洞可能被整体均值弱化；WT 与 mesh 采样权重不同 |
| 原生姿态和尺度保持 | 未配准相机坐标指标 | 混合形状、位置、方向和尺度，不是纯姿态角误差 |
| 输入视角几何忠实度 | SSI 深度误差、覆盖率、IoU | WT 仅取像素对应的 Z，不检查其预测 XY 是否重投影回该像素；不等于完整三维对齐 |
| 缺失与额外几何 | 双向距离、F-score、投影覆盖率和 IoU | 深度交集外的错误不进入 MAE 等误差；需结合覆盖率、IoU 判断 |
| 内部填充、空腔、拓扑 | 表面距离与逐阶段几何诊断 | 未计算占据体积、水密性或拓扑指标；内部多余面仅通过采样面积和距 GT 的距离影响成绩 |
| 纹理、文字与材质 | 受控渲染及人工案例检查 | 外观 RGB、OCR 与 PBR 评价待扩展，法向 PSNR / LPIPS 按第 6 节计算 |

第 5 节 SSI 深度的 WT mask 来自输入 alpha，需结合该来源解释 IoU。第 6 节多视角遮罩由几何重新投影产生。δ1/δ2 的比例阈值较宽，且受 GT 相机距离影响，容易饱和；AbsRel 也以相机 Z 为分母，不是相对物体厚度的误差。材质、灯光和 viewer 中的展示平移不参与上述几何指标。

## 附录 A：渲染、随机种子与保存文件

`gso-render-v1` 使用 1024² 输入、水平 FoV 40°、俯仰 20°，方位角按资产固定 seed 在 `[0, 360)` 采样。归一化资产的包围球半径上界为 0.5，相机距离为 `0.5 / sin(20°) × 1.2`；near/far 为 0.01/10。当前数据集声明资产 Z-up，转换依据保存的 `asset_up` 与矩阵，不从名称猜轴向。

相机使用 RDF，像素中心为 `(x+0.5, y+0.5)`。双面光栅化、像素中心单次采样、不做抗锯齿；GT 输入 RGB 使用原贴图和单位环境光，无色调映射，mask 为不透明几何覆盖。504² GT depth 按裁剪后的 K 重新渲染，禁止跨背景直接双线性缩放深度。默认 WT 推理的假定内参不能替代评价用的 GT 标定。

视图、GT 配准/评价采样、预测配准/评价采样分别使用：

```text
seed = int(SHA256("20261013|用途|asset_id")[:8], 16)
用途 = view / gt_reg / gt_eval / pred_reg / pred_eval
RNG = numpy.random.Generator(numpy.random.PCG64(seed))
```

跨方法同一资产的预测采样 seed 相同，但采样对象不同；相同推理整数 seed 也不表示跨模型使用相同 latent。实际 seed、采样点、依赖环境和源码版本应一并保留。

| 位置 | 关键复现文件 |
| --- | --- |
| `$WT_PROCESSED_ROOT/gso/v1/` | `inventory.jsonl`、`split.json`、各 split 清单 |
| 数据集 `samples/<asset>/` | `input.png`、`camera.json`、`render_config.json`、`gt_world.ply`、`gt_camera.ply`、`gt_points.npz`、`gt_depth.npz`、带产物哈希的 `input.json` |
| 实验 `samples/<asset>/<method>/<config>/seed-*/` | `run.json`、`config.json`、`prediction.npz` 或 `decoded_mesh.ply`、mesh 坐标元数据 |
| 同一结果目录中的评价产物 | `metrics.json`、`evaluation_points.npz`、`registration.json`；适用时有 `depth_fit.json`，异常时有 `evaluation_error.json` |

数据集位于 `$WT_PROCESSED_ROOT/gso/v1/`，实验位于 `$WT_OUTPUT_ROOT/experiments/` 下各实验目录。原始数据在 `$WT_DATA_ROOT/raw/gso/`，只读；渲染和评价入口先检查完整性标记 `COMPLETE.json`。

## 附录 B：执行与维护

按照 [README 环境说明](../README.md#环境与安装) 在远程项目目录加载 `scripts/env.sh`，使用项目 `.venv`。长任务使用已确认的 tmux socket `wt-recovery` 与 `scripts/run_task.py` 记录状态。

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing
source scripts/env.sh

python -B -m scripts.setup_multiview

python -B -m examples.evaluate_multiview \
  "$WT_OUTPUT_ROOT/experiments/20261013-R2-gso-quant-v1"

# 校验已有多视角结果并刷新汇总
python -B -m examples.summarize_multiview \
  "$WT_OUTPUT_ROOT/experiments/20261013-R2-gso-quant-v1"

python examples/evaluate_gso.py \
  --experiment "$WT_OUTPUT_ROOT/experiments/20261013-R2-gso-quant-v1" \
  --workers 1

python examples/export_experiments.py \
  --experiments "$WT_OUTPUT_ROOT/experiments" \
  --out experiments.xlsx \
  --audit "$WT_OUTPUT_ROOT/validation/experiments-workbook.json"
```

评价使用完成的推理结果，hybrid 深度渲染需要 CUDA；Excel 导出仅读取保存的 JSON 并重新汇总，不重新推理、采样、配准或渲染。

维护时同步检查以下实现入口：

| 责任 | 代码 |
| --- | --- |
| 固定划分、用途 seed | [prepare_gso_inventory.py](../examples/prepare_gso_inventory.py)：`split_ids`、`asset_seed` |
| GT 归一化、相机、渲染 | [render.py](../evaluation/render.py)：`normalize_parts`、`make_camera`、`Rasterizer.render`；[prepare_gso_views.py](../examples/prepare_gso_views.py)：`prepare` |
| 抽样、配准、指标 | [geometry.py](../evaluation/geometry.py)：`surface_points`、`register_sim3`、`chamfer`、`depth_metrics` |
| 方法坐标和状态分支 | [evaluate_gso.py](../examples/evaluate_gso.py)：`evaluate_run`、`evaluate_one`；[canon.py](../wt/textured_mesh/canon.py)；[experiment.py](../wt/experiment.py)：`CAMERA_NA` |
| 多视角渲染与指标 | [multiview.py](../evaluation/multiview.py)、[evaluate_multiview.py](../examples/evaluate_multiview.py) |
| 多视角已存结果汇总 | [summarize_multiview.py](../examples/summarize_multiview.py) |
| 按资产汇总、共同集合 | [records.py](../evaluation/records.py)：`summarize`；[research_workbook.py](../evaluation/research_workbook.py)：`_stats`、`_paired` |

改变指标公式、单位、采样、配准、渲染或有效性规则时，应更新本文、相关协议 ID / 数据集版本，并先用 P0 检查，再生成新版本结果；旧成绩保留其原协议和来源。仅补充说明且数值行为不变时，不更改协议 ID。

CD / 相机 / SSI 评测器当前将入口、`geometry.py`、`render.py`、`canon.py` 的源码摘要合成为 `evaluator_sha256`；已有评价摘要不一致时默认拒绝跳过。`--force` 会重算并覆盖评价产物，不自动归档旧结果，也不自动升级协议 ID，使用前需明确版本与保留方式。渲染配置变化则要求新建数据集版本。哈希保护不替代完整的源码、环境及输入来源记录。
