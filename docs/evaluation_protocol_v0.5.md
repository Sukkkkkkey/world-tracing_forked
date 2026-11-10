# 评测协议 v0.5

2026-11-10。主结果评价配准后的完整几何与输入可见几何，原生坐标指标作为附加参照。实现配置为 gso-baseline-v2。

## 1. 数据与评测对象

- 使用 GSO v1 的 R2 100 个固定资产、输入图、GT 和相机，P0 10 个资产用于校准。
- 四方法为 WT defaults-v1、TRELLIS.2 defaults-v1、Hybrid defaults-v1、Pixal3D resolution1024-v1，各取 seed 42–49。
- WT 使用六层有效点云。三个 mesh 方法分别评价 decoded mesh 和 exported GLB，两组独立配准、独立选 seed。GLB 应用场景变换并恢复方法坐标。
- 固定 checkpoint、预处理、推理与导出参数，WT tensor batch=1。保存来源摘要，Hybrid 另存实际 WT parent。
- seed 42 复用已有输出，技术性重试使用原 seed，失败计入八次候选预算。

## 2. 采样与配准

GT 按资产 AABB 对角线归一化为 D=1。Mesh 按表面积采样，WT 汇集六层有效有限点并去除精确重复点。使用独立用途 seed 生成 10,000 个配准点和 100,000 个评价点，点数不足时使用全部点并记录数量。

采用主轴坐标下 24 个右手旋转初始化的正 Sim(3) ICP，允许旋转、平移和正等比缩放。保存最终变换与配准诊断。可见区域、输入视角和 multi-view 复用完整形状的配准变换。

## 3. 几何指标

设 P、G 为预测与 GT 评价点，d 为最近邻欧氏距离。

\[
CD_{Lk}=\frac12\left[
\operatorname{mean}_{p\in P}d(p,G)^k+
\operatorname{mean}_{g\in G}d(g,P)^k
\right],\quad k\in\{1,2\}.
\]

CD-L1、CD-L2 单位分别为 D、D²。Precision、Recall 分别为预测点和 GT 点的最近邻距离严格小于 τ 的比例，F=2PR/(P+R)，分母为零时 F=0。阈值为 0.01D、0.05D，并保存双向距离。

| 主结果 | 定义 |
| --- | --- |
| 完整几何 | 全部评价点的 CD-L1/L2、Precision、Recall、F-score |
| 输入可见几何 | GT 可见区域及对应预测点的相同指标 |

可见区域由固定输入相机对 GT 点发射射线确定，与首个 GT 交点重合的点标为 visible。容差为 1e-4D，经 P0 校准冻结。遮挡与视锥外标签保留为附加诊断。射线使用双精度求交，近切线阈值为 1e-12。为消除坐标舍入，射线端点校正到 GT 表面，位移上限为 1e-6D 并逐点保存。完整几何使用冻结的 GT 评价点。

预测点按最近 GT 评价点继承区域标签，在区域内重新计算双向最近邻指标。记录区域点数。GT 区域非空而预测为空时 Recall/F-score=0，CD 标记无有效比较。GT 区域为空时标记 N/A。区域边界归属误差随可见性校准记录。

## 4. 相机与渲染指标

输入视角采用生成输入图时保存的 GT 相机。裁剪左上角为 (x₀,y₀)、边长为 l，缩放到 504×504 后，s=504/l，焦距乘 s，主点变为 s(cx−x₀)、s(cy−y₀)。外参沿用输入相机。四方法共用固定 K_crop、外参及 GT。

Multi-view 使用 30 个固定球面 Hammersley 方向，512×512、FoV 40°、距离约 1.754D。采用 u=(i+0.5)/30、仰角 asin(2u−1)、输入方位加 360°×radical_inverse₂(i)，上下半球各 15 个方向。数量与采样方式参考官方工具，半步偏移用于避免极点退化。输入视角单独报告。[TRELLIS.2 渲染实现](https://github.com/microsoft/TRELLIS.2/blob/main/trellis2/utils/render_utils.py)

四方法使用共同 surfel 表示，mesh 另报原生三角面渲染。Mesh 面积采样 2,000,000 点，体素尺寸 0.002D、surfel 半径 0.003D、PCA 法线邻域半径 0.006D，完整参数见 configs/multiview_baseline_v2.json。

逐视角报告深度 MAE/RMSE、轮廓 IoU、法线平均角误差、法线 PSNR/LPIPS、深度与法线覆盖率及有效像素数。深度使用相机 Z，法线采用相机坐标并朝向相机。点误差在有效交集上计算，LPIPS 使用中性背景整图。指标与覆盖率共同报告。

## 5. 候选选择与汇总

每个资产、方法、输出阶段以完整几何 CD-L1 最小的 seed 为 best-of-8，平分时取较小 seed。该组所有几何、区域及渲染指标读取同一候选。Decoded 与 GLB 分组独立选择，WT 点云作为两组共同参照。

同时报告 seed 42、八次候选的有效均值及标准差、best-of-8、有效候选数与失败率。八个候选均达到终态后汇总 best-of-8。全部失败的资产计入失败数。

先对每资产的 30 个视角等权汇总，再对资产等权。完整多视角均值要求相应指标在所有视角有效，另存有效视角数。方法比较报告共同有效资产数，95% bootstrap 区间按资产重抽样。

## 6. 产物与附加参照

- 默认对所有 seed、阶段保存 input-view 的 GT/预测法线、深度、mask、有效性、误差图和对照 PNG。评测入口或队列入口增加 --save-multiview-renders 可同时保存 30 个 multi-view 的 PNG。全部视角的指标和浮点 NPZ 均保存，GT 按资产和视角共享，同资产同视角使用统一色标。
- 保存相机、配准矩阵、采样 seed、输出阶段、指标、文件摘要与源码/config revision，best-of-8 指向对应候选产物。
- 原生坐标、scale-only、内参重投影、SSI、RGB 外观、遮挡区域、面积/GT 和 Hybrid parent 对照作为附加参照。
- 导出影响另以同 seed、同 decoded 配准变换比较 decoded→GLB，并报告 decoded winner 的 GLB 成绩。
- 点云与 mesh 的采样权重、surfel 转换误差及 ICP 局部最优作为解释条件，保留 GT 自一致性校准。

实现包含区域指标、30 视角 PNG/NPZ、同变换导出对照与独立数值缓存。可见性依赖 rtree==1.4.1，已纳入依赖清单。

P0 通过 --calibration --seeds 42 完成 10 资产、70/70 阶段验收，每项含输入视角及 30 个 multi-view。47,430 张 PNG 已逐图校验，216 项项目测试覆盖通过。评测 revision 为 f99c2f63a273b21b0d2e，完整 CD-L1 与上一轮相同采样及配准结果的最大差值为 0。summary、supplementary、render_index 和 calibration 保存汇总、附加参照、产物索引及校准结果。
