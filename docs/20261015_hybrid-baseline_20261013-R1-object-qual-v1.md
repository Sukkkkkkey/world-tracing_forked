# R1 object baseline：按原因分类的归因分析

> 2026-11-07 历史记录说明
>
> 本文保留旧服务器实验的数值、分析和当时路径。新服务器已完成重跑并更新 experiments.xlsx，最新数值、差异和验收记录见 [恢复结果报告](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_recovery-results.md)。

实验：`20261013-R1-object-qual-v1`；初次分析：2026-10-15；归因整理：2026-10-18；新版 viewer 与指定案例复核：2026-10-19；冰淇淋固定形状、纹理种子对照：2026-10-20（G.2）。

**本轮结论：指定案例支持 WT 的输入视角忠实度优势和 hybrid 的方向保持收益。Hybrid 的退化包含上游预处理损失、粗结构构造和后续生成/导出；“体积与表面冲突”仍是待消融的机制解释。WT 的有效图像分辨率和点图采样限制有实现依据；狐狸偏黑已定位到资产材质与 PBR 渲染的共同影响。**

2026-10-19 核查覆盖用户指定的 20 个样本、40 份 hybrid 上游与结构、60 份 GLB 材质。**当前 viewer 已修复后层 RGB 广播，并在 balanced/full 保留完整 GLB。** 附录 B 中的重复面部属于旧版显示问题，不再作为本轮新观察的解释。新增证据、逐例结论见附录 G。

R1 是 30 张示例图的定性实验，没有配套真值网格、多视图或标定相机。本文补充的是可复核的结构、预处理、显示和资源统计，**不是 CD/F-score、纹理真实性或姿态准确率评测**；不混入 GSO P0/R2 的分数。

## 1. 现象与原因对应

“已确认”指实现机制或直接影响已验证；“支持性证据”指观察与统计支持，但尚未隔离全部因素；“待消融”指合理候选原因，不能据此分配质量损失比例。

| 现象 | 主要归因 | 次要因素与证据边界 |
| --- | --- | --- |
| WT 在输入视角的外观最忠实 | **模型表示 + 显示方式**：相机点图配输入 RGB，颜色来源已确认 | 不等于完整纹理生成能力更强；点云与 PBR mesh 的显示条件不同 |
| 四个样本“后脑勺变脸” | **历史可视化问题，当前已修正** | 旧版把正面 RGB 广播给六层；新版只给 L0 输入颜色，后层灰色 |
| WT 横竖白线 | **模型输出连续性，支持性证据**：14 px patch 边界点间距偏大 | 点抽样、点大小和视角可放大；已排除漏拼像素，训练/输出头/精度因素未分离 |
| 原生 TRELLIS.2 朝向不对应，hybrid 改善 | **模型输出坐标语义 + hybrid 结构约束** | 属于任务能力差异与 hybrid 收益；未发现轴变换或重复缩放错误，尚无标定姿态误差 |
| Hybrid 结构增厚、空隙连接或疑似内部面 | **Hybrid 结构构造是优先候选，质量因果待消融** | 插值/闭运算改变支持域；最终 hole-fill 新增为 0；生成和导出可能共同影响，内部面尚未逐一验证 |
| `obj141` 细环/支杆丢失 | **Hybrid 预处理有已确认的直接损失**：腐蚀删除 14.30% 前景 | shared-WT 恢复多条细环；32³ 量化、生成和导出的剩余影响未隔离 |
| Hybrid 脸部、条纹、机械细节变差 | **Hybrid 条件与生成阶段的共同候选，待消融** | 不能用默认输出直接认定 Stage 2 能力不足；上游预测、结构和导出都可能影响 |
| WT 局部细节稀疏、TRELLIS 爪子/机械结构更清楚 | **有效输入分辨率 + 输出表示 + 生成先验** | WT 504² 输入中物体长边约 336 px；尚无分辨率消融，清楚不等于真实准确 |
| WT / TRELLIS 尺度观感不同 | **输出尺度约定、比例与朝向共同影响** | 珠宝/树的最长边几乎一致；玉龙有实际尺度和深度范围差异，非统一 viewer 缩放错误 |
| 狐狸等 mesh 偏黑 | **资产材质 + PBR 渲染，均有证据** | 狐狸金属度异常高；无光照底色仍有偏色，不能全归为灯光；客户端还会重算法线 |

## 2. 按原因分类

### 2.1 模型能力与表示边界

- **WT 当前配置不预测纹理。** `r75b` 输出 XYZ，保存的 RGB 是输入图。因此输入视角的颜色忠实是其表示与显示方式的优势；缺少不可见面颜色属于当前输出能力的边界，“背面长脸”的直接原因则在查看器，不能当作模型生成纹理失败。
- **“输入分辨率限制”应具体到模型实际输入。** 本次 20 张原图均为 1376×768；WT 裁剪留白后缩为 504²，物体长边通常约 336 px。TRELLIS 使用更紧的裁剪及 512/1024 图像条件，且输出连续 mesh。狐狸爪子、狮子滚球、机械细节和宫殿阶梯受有效图像采样、输出点密度及模型先验共同影响；只提高原图尺寸不会自动提高该 WT checkpoint 的输出网格分辨率。14 px patch 也不等于每 14 px 只输出一个几何点。
- **WT 的 patch 边界连续性存在问题迹象。** 30/30 点图的跨边界平均点间距更大，逐样本比值中位数为 1.143×；真实拼接函数精确往返。可以归到预测几何的连续性问题，但还不能定为训练缺陷、线性输出头缺陷或数值精度问题。六层 mask 相同、forward-fill 重复交点，也意味着不能把六层视为六个独立有效表面。详见附录 B。
- **原生 TRELLIS.2 输出标准坐标资产，不提供本次比较所需的输入相机姿态。** 默认观察方向不同不等于网格轴变换出错；hybrid 利用 WT 结构保留方向，属于新增约束带来的收益。部分原生结果朝向本就较接近输入，不能泛化为每例都失配。
- **Stage 2 能合成细节，但没有逐点保留 WT 的保证。** 现有 decoder 中已出现结构损失，说明错误在导出之前就存在；但它接收的条件也已经改变。只有固定同一 WT、图像条件和结构处理后，才能进一步判断生成能力的贡献。目前不能把剩余退化全部归于模型。

### 2.2 Hybrid 预处理与衔接逻辑

- **预处理删除细结构：直接影响已确认。** 默认 hybrid 用黑底、`alpha_erode=2`，WT 基线用灰底、不腐蚀。望远仪的 5,932 个前景像素被腐蚀删除，细环在进入结构构造前就已缺失。shared-WT 恢复多条外环，但它还改变了背景与预测，因此不是纯 erosion 单因素生成对照。详见附录 D。
- **稀疏结构构造改变几何支持：机制已确认，最终质量因果待消融。** 对所有相邻层插值，不识别入/出表面或空气区间；32³ 量化及闭运算可能合并细杆与空隙。默认结构中平均 16.18% 的最终格子由处理新增；最后的 hole-fill 在 60/60 份结构上均新增 0，不能把本轮退化具体归咎于这一步。TRELLIS.2 的粗尺度 latent 支持域也不能简单等同于薄壳或实心占据；是否分布失配需保存原生结构并做消融。详见附录 C。
- **坐标与等比缩放：本轮未发现实现错误。** 60 份变换往返通过，未发现镜像、重复缩放或错误 parent；shared-WT 的 30 份预测与 WT 基线逐文件一致。恢复坐标能保留整体方向，但不能撤销生成阶段的局部形变，也不能替代相机重投影误差评测。

### 2.3 网格导出后处理

`to_glb` 还执行补洞、重网格化、简化、UV 展开和材质烘焙；`remesh_project=0` 不将顶点投回原表面。这些步骤会改变几何与外观，细杆、孔洞和纹理可能进一步受损，**目前属于贡献尚未量化的候选因素，未确认导出实现存在 bug**。

新增确认：导出固定 `alphaMode='OPAQUE'`，即使纹理保存了小于 1 的 alpha，也按不透明材质显示。海蛇的水浪/薄片不能只从“不透明块”的观感判断实体填充；玻璃宫殿本轮保存的 alpha 本身也几乎全为 1，不能指望仅改显示模式恢复玻璃。另，`decoded_mesh.ply` 是 `decode_latent()` 返回后保存，**已执行 `m.fill_holes()`**；它并非未经任何后处理的 decoder 原始输出。

望远仪 decoder PLY 已缺失多条外环，确认至少部分损失发生在 GLB 导出之前；椅子侧板与海蛇的闭塞结构在保存的 PLY 中也已经存在。尚未保存解码后首次补洞前的 mesh，因此“生成本身”与这次补洞的影响仍未分离。同一套导出参数也不保证对不同输入几何的影响相同。详见附录 D、G。

### 2.4 可视化代码与显示设置

- **旧问题已修复。** 当前 `surface` 模式仅 L0 使用输入 RGB，后层灰色；balanced 保留完整 GLB、纹理缩至 1024、WT 最多 50k 点；full 保留原纹理与全部 WT 点。fast 仍可能使用顶点预览。不能继续用旧版 balanced 的行为解释新版结果。[显示预算](/data1/LiuShuqi/code/world_tracing/viewer.py:27)
- **“灰色”不是统一中性材质。** 当前 gray 模式仍保留 mesh 原纹理，仅把无纹理几何和 WT 点置灰；surface 对 mesh 同样保留原材质，只为 WT L0 加输入颜色。比较纯几何应看去材质诊断或 depth，而不能把 gray 当作所有方法相同材质。
- **颜色差异有实际材质因素。** 狐狸原生/默认 hybrid 的表面采样平均金属度为 0.999/0.997；相同 GLB 在 Viser 中仅取消金属度就明显变亮。当前服务端保留原材质参数；浏览器正常应用 PBR 光照，不能把偏黑简单当作 RGB 丢失。附录 G 给出材质与无光照对照。
- **依赖层仍有隐含显示变更。** 本地 Viser 1.1.1 的 `GlbLoaderUtils.ts` 无条件调用 `computeVertexNormals()`。狐狸原生/默认 hybrid 中，相对保存法线改变超过 10° 的顶点分别占 16.2%/58.3%；这可能改变局部明暗，未改变顶点位置或面。此处是当前依赖实现的行为，不能泛化为所有 Viser 版本。

这些显示问题影响观测，不会改变保存的 XYZ 或 GLB。修复显示语义后仍存在的几何/外观缺陷，才应继续定位到上游阶段。

### 2.5 评价协议与比较条件

这一类解释**结论可能偏向何处**，本身不是生成质量的根因。

- WT 的输入 RGB 已包含光照、高光与阴影，TRELLIS 的生成纹理/PBR 材质是另一种输出。金属、玻璃、珠宝的亮暗不能直接当纹理误差；本次 base-color 诊断图不评透明度、粗糙度或重光照。
- viewer 分别居中模型并使用通用观察相机；输入方向接近、像素严格对齐、隐藏形状准确是不同问题。应分开记录方向、局部几何、纹理和多视角完整性；默认 WT 与 hybrid 的预处理差异也要单列。
- R1 无 GT，不能报告 Table 1 的形状指标、隐藏面准确率，或用挑出的四例计算整体失败率。点数、面数、文件大小仅表示复杂度；不同队列的历史耗时不能直接推导算法速度。
- “与作者一致”仅能限定到 WT 的像素对应优势。论文 Table 1 全几何排名为 **WT > hybrid > TRELLIS.2**，与本轮主观综合排序 **WT > TRELLIS.2 > hybrid** 的后两位不同，且未评纹理，不能称整条排序复现。[WT 论文 Table 1 与 §5.3](https://arxiv.org/html/2606.13652v1#S4)
- 多物体的数量/相对布局、错误连接，以及模型生成的额外底板仍需检查，不能被上述分类遗漏。部分原生恐龙的底板是 GLB 自带几何；本文渲染未添加地面。其产生机制尚未单独归因，30 样本覆盖见附录 E。

## 3. 按归因安排验证顺序

| 优先级 | 原因类别与动作 | 可验证的完成条件 |
| --- | --- | --- |
| 1 | 材质/显示：分开原生 PBR、无光照底色、中性几何 | 记录灯光、纹理分辨率和法线策略；后层着色与完整 GLB 显示已修复，不重复列为待修 |
| 2 | Hybrid 预处理：隔离腐蚀与背景影响 | 固定图像和 seed，分别单独比较 erosion=0/2、灰底/黑底；现有 shared-WT 仅作辅助证据 |
| 2 | Hybrid 结构：分开验证插值、closing | 固定同一 WT 与规范化；保存原生 Stage 1、注入坐标和 cascade 支持域；比较端点、仅插值、仅 closing、默认处理 |
| 3 | 生成/导出：定位 decoder 前后的损失 | 同时检查 decoder PLY 与 GLB，少量样本补切面/连通分量；再判断错误内部面及导出贡献 |
| 3 | 模型输出/显示：分离 patch 连续性与点密度 | 固定相机比较全点与预览，用原始 XYZ 边界距离验证；加大点半径不算几何修复 |

**本次核查未修改推理、导出或 viewer 源码，未重跑模型生成。** 结构复算、已有资产渲染和内存中的材质对照已执行；体素构造与模型分辨率的生成消融尚未执行。

## 附录 A：实际配置与可报告的量化结果

30 张输入 × 4 配置 = **120/120 完成**。以下均使用修正原生 TRELLIS 路由之后的结果。推理 seed=42、batch=1；WT `r75b`、504²、六层、20 步；mesh 为 `1024_cascade`、shape/texture 各 12 步、4096² 纹理、简化目标 1,000,000，导出采用 `remesh=True, remesh_band=1, remesh_project=0`。

| 配置 | WT 上游 | TRELLIS 稀疏结构来源 | 点数或 decoder 面数中位数 | GLB 面数中位数 | GLB 平均大小 |
| --- | --- | --- | ---: | ---: | ---: |
| WT `defaults-v1` | 灰底、alpha 不腐蚀 | 不使用 TRELLIS | 214,335 点 | — | — |
| TRELLIS.2 `defaults-v1` | 无 WT | 原生 Stage 1 | 6,784,944 面 | 962,676.5 | 37.59 MiB |
| Hybrid `defaults-v1` | 黑底、alpha 腐蚀 2 px | 32³，ray_steps=4 | 7,430,148 面 | 977,909 | 41.19 MiB |
| Hybrid `shared-wt-v1` | 与 WT 基线同一份预测 | 32³，ray_steps=4 | 9,676,064 面 | 979,295 | 41.45 MiB |

面数和文件大小反映复杂度，不能替代质量。默认 hybrid 的 WT parent 与 WT 基线 **30/30 不同**；shared-WT **30/30 的预测文件 SHA-256 相同**。原生 TRELLIS 配置 JSON 中虽有统一 schema 的 `alpha_erode/wt_steps/ray_steps` 字段，原生分支不使用这些 WT 参数。

## 附录 B：WT 颜色、四个面部案例和 patch 缝隙的证据

### B.1 当前 WT 没有预测纹理

下列链条记录 **2026-10-15 旧版查看器** 的错误机制；2026-10-19 的 viewer 已修正最后一步。WT 模型与预测文件的语义未改变：

```text
CONFIGS['r75b']: predict_color=False, split_token, depth_only=True, output_mode='xyz'
  → inference_diffusion() 返回 xyz、mask、None
  → InferenceBackend.predict_wt() 保存 prediction.npz
      xyz: [6,504,504,3]；mask: [6,504,504]；rgb: [504,504,3]（输入图）
  → viewer.read_points() 读取 rgb
  → viewer.prepare_points() 将 rgb 广播到 [6,504,504,3]
      同一像素的颜色被赋给全部六层三维点
```

因此旧版的“后脑勺变脸”并非 WT 把背面纹理生成成了正脸，也不是推理代码把后层坐标强行拉到正面。它是查看器把可见面的颜色赋给不可见几何。原生 `wt.viz.log_prediction()` 已采用更合适的语义：第 0 层输入 RGB，其余层深度灰度。[模型配置](/data1/LiuShuqi/code/world_tracing/wt/checkpoint.py:128)、[输出保存](/data1/LiuShuqi/code/world_tracing/wt/batch.py:287)、[当前已修正的着色位置](/data1/LiuShuqi/code/world_tracing/viewer.py:125)、[原生显示](/data1/LiuShuqi/code/world_tracing/wt/viz.py:138)

### B.2 四个案例的颜色与几何对照

仅使用现有 XYZ，固定绕竖直轴转到后视方向；分别显示输入 RGB、局部法线中性着色和 Z 深度，不重推理、不改几何。

| 样本 | 复制 RGB 时的现象 | 去掉 RGB 后的后视几何 |
| --- | --- | --- |
| `obj025_cartoon_dino` | 眼睛、嘴和腹部颜色出现在背面 | 背部棘突、尾巴和后脑轮廓可见；侧向吻部轮廓不等于背面又长出一张脸 |
| `obj069_pixar_dwarf` | 胡须、五官、围裙覆盖背部 | 后脑、肩背和背部衣物形状，无对应的正脸几何 |
| `obj083_chibi_swordsman` | 后脑出现眼睛、鼻嘴 | 后脑是发束体积，背部为衣服 |
| `obj149_hand_painted_kokeshi_set` | 后侧仍显示完整脸部与前侧衣纹 | 后脑为圆滑头部，身体为柱状；彩绘表情并非几何输出 |

后视诊断中，来自第 0 层的可见像素占比分别为 **0.327%、0.291%、0.393%、0.366%**（全物体，非面部框）；因此重复面部主要不是穿过点云缝隙看到了正面，而是**后层本身被赋予正面 RGB**。该比例依赖诊断相机与 1 px 点半径，只用于验证显示机制，不是质量指标。隐藏几何仍可能有局部粗糙、层间重复或错位，本对照不证明其真实准确。

![四个面部案例：输入、复制 RGB 的后视图、中性几何、深度](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/four-face-geometry-controls.png)

### B.3 横竖白线：存在 patch 周期，不是丢了一圈像素

`r75b` 使用 14×14 patch，504/14=36。输出线性投影到 patch 内 XYZ 后，再用 `einops.rearrange` 恢复完整像素网格；这里没有删除边缘行列或插入空白。对实际函数进行 `[1,6×504×504,3]` 唯一编号张量往返，逐元素相等；30 份 WT 文件也没有有效区 NaN/Inf。[拼接函数](/data1/LiuShuqi/code/world_tracing/wt/_core/arch/models/model_utils.py:238)、[几何输出头](/data1/LiuShuqi/code/world_tracing/wt/model.py:2008)

对第 0 层前景内相邻像素的三维距离，排除轮廓附近 2 px，合并横向、纵向边；比较跨 patch 边界与 patch 内部：

- **30/30** 样本边界平均距离更大；逐样本比值的中位数 **1.143×**，范围 **1.045–1.215×**。
- 使用距离中位数而非均值时，逐样本比值中位数为 **1.087×**。
- `obj141` 的平均距离比为 **1.173×**；但其细结构、深度跳变也很多，不能把每条白线都认作 patch 缝。

这支持“预测点图在 patch 边界的连续性稍差，点渲染将间距差显露为缝”的解释。采样、点大小、斜视时的表面稀疏也会放大空隙。当前证据未把模型训练、线性输出头、数值精度的影响完全分离，**没有发现漏拼 patch 的实现错误，也不应仅靠加大点来宣称几何已修复**。

![全部 30 个样本的 patch 相位统计；0 为边界，灰线为各样本](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/all30-patch-phase.png)

## 附录 C：Hybrid 坐标与稀疏结构的证据

### C.1 保留输入方向是实际收益，严格像素对齐尚未评测

原生 TRELLIS.2 生成标准坐标下的资产；同一个 viewer 相机下，火车/恐龙可能朝向镜头，而输入是侧视。Hybrid 以 WT 相机点图提供结构，生成后利用保存的变换恢复到其 WT 上游坐标，能保留更接近输入的整体方向。手提箱、火车、老虎、恐龙、狐狸、翼龙、房车和木偶均可在全览图中看到这种收益。

坐标链为 `camera RDF → (x,z,-y) canonical Z-up → glTF (x,z,-y) → 撤销 GLB 轴变换 → canon_inverse → WT camera`。两次轴旋转均为右手旋转；canonical 使用正的等比缩放。本轮 60 份 hybrid 的相机点→canonical→相机往返，在保存的 float32 点上最大差为 0；未发现镜像、重复缩放或使用另一份 WT 的变换。[坐标变换](/data1/LiuShuqi/code/world_tracing/wt/textured_mesh/canon.py:25)、[查看器恢复](/data1/LiuShuqi/code/world_tracing/viewer.py:352)

但 shape flow/decoder 会改变几何，恢复坐标不保证逐点一致。viewer 还会分别居中并排、使用通用观察相机，未按输入内参严格重投影。因此应分别记录：**输入方向保持、轮廓/局部形状保持、纹理细节、任意视角完整性**，不以一个总排序替代这些维度。

### C.2 “体积输入与表面模型冲突”应如何表述

实际处理是：六层 XYZ → 对每对相邻层插入 4 个点 → 32³ 量化 → 一次二值闭运算 → `binary_fill_holes` → 注入 shape flow。没有按射线入/出表面配对，也没有空气区间判断。理想有序交点中，入→出可能是实体，出→下一次入可能是空隙；当前循环两者都插值。XYZ 模式本身又不强制严格共线、深度递增，不能把它当作可靠的实体占据重建。[层间插值与体素化](/data1/LiuShuqi/code/world_tracing/wt/textured_mesh/voxelise.py:74)

TRELLIS.2 的 O-Voxel 通过表面相交激活局部体素，并利用边相交标记连接表面；其 sparse structure 训练数据来自压缩后的 shape latent 坐标，而非一条“必须先填成实心”的规则。粗尺度压缩支持域也不能简单等同于一层薄壳。代码注释中“solid, matching TRELLIS.2's training distribution”**缺乏依据**，不能拿来证明当前填充合理；该注释在仓库原始版本中已存在。[TRELLIS.2 §3.1–3.2](https://arxiv.org/html/2512.14692v1#S3)、[训练结构构造](/data1/LiuShuqi/code/world_tracing/dependencies/TRELLIS.2/data_toolkit/encode_ss_latent.py:119)

复算全部 60 份 hybrid 注入结构，与已保存 `injected_voxels` 一致：

| 结构诊断，逐样本统计 | 默认 hybrid | shared-WT |
| --- | ---: | ---: |
| 最终占据数 / 仅 WT 端点占据数，中位数 | 1.116× | 1.133× |
| 最终占据中由处理新增的格子，平均比例 | 16.18% | 16.20% |
| 六个轴向邻格也全部占据的格子，平均比例 | 48.67% | 49.52% |
| 最后 `binary_fill_holes` 新增体素 | **全部为 0** | **全部为 0** |

“内部格子”在此只是六邻域形态指标，不是 GT 物体内部比例，也不是错误 mesh 面比例。结果支持结构变厚、跨空隙连通的风险；**尚未证明它是每个质量问题的原因**，更不能推断所有内部面都是错误的。TRELLIS.2 本就能表示真实的封闭内部表面。

另外，`ray_steps=0` 仍执行闭运算与 hole-fill，不等于 surface-only；本轮仅复算了这些结构计数，没有生成新的消融 mesh。要验证原因，应固定同一 WT 预测、规范化和图像条件，分别比较端点量化、仅 ray 插值、仅 closing、完整默认处理。Stage 1/shape latent 的原生坐标未保存，因此目前没有它们与 hybrid 的直接分布对照。不同支持域会改变随机张量形状，同 seed 也不是逐 token 相同噪声。

## 附录 D：`obj141_brass_telescope_orrery` 的逐阶段证据

**首要证据是预处理，不应跳过它直接归咎于 Stage 2。** 默认 hybrid 在 504² 前景 mask 上执行 5×5 全一核腐蚀（`alpha_erode=2`）：前景由 **41,483 → 35,551** 像素，删除 **5,932 / 14.30%**。复算 mask 与保存结果逐元素相同；细环和支杆的大段已不在有效点图中。RGB 条件仍能看到这些结构，但注入几何缺失相应支持。[预处理](/data1/LiuShuqi/code/world_tracing/wt/data.py:418)

![望远仪：WT 前景与默认 hybrid 腐蚀后的前景](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/telescope-mask-erosion.png)

| 环节 | 默认 hybrid | shared-WT |
| --- | ---: | ---: |
| 有效前景像素 | 35,551 | 41,483 |
| 32³ 仅端点体素 | 1,891 | 2,471 |
| 加层间插值 | 1,997 | 2,629 |
| 加闭运算 / hole-fill 后 | 2,111 / 2,111 | 2,815 / 2,815 |
| 六邻域连通分量：端点 → 最终 | 5 → 3 | 2 → 1 |
| decoder 面数 → GLB 面数 | 7,314,590 → 999,213 | 8,945,542 → 945,128 |

已有 shared-WT GLB **保留了默认结果缺失的多条外环与支杆**，说明细结构并非必然无法经过 TRELLIS.2。shared-WT 同时改了 WT 背景颜色并更换了预测，不能把所有改善都量化归于 mask 单一因素；mask 对细线的直接删除则已确定。见 [默认 / shared-WT 三视角对照](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/telescope-default-shared.png)。

剩余损失还有三个来源，需要分阶段观察：

1. **结构分辨率与连通性。** 默认 canonical scale=0.79536，一格对应 WT 相机单位 `1/(32×scale)=0.03929`，约为该预测最大边长的 **3.96%**。细杆/间隔会共用粗格子；闭运算又增加 114 格。最终 1024³ 解码能合成细节，但并未恢复已丢失的准确结构约束。[体素阶段图](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/telescope-voxel-stages.png)
2. **shape 生成已产生损失。** 默认 decoder PLY 中外环就已大量缺失，所以失败不只是 GLB 纹理或简化造成。shared-WT 仍有杆件变形、断点与局部形状偏移，表明取消腐蚀不是完整解决方案。
3. **导出还会改几何和外观。** `to_glb` 进行补洞、narrow-band dual-contouring remesh、简化、UV 展开和材质烘焙；`remesh_project=0` 不把顶点投回原表面。细结构可能进一步改变。两方法使用同一导出设置，也不能据此认为影响相等。应区分 decoder 几何与最终资产，而非只检查顶点预览。[decode / GLB 对照](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/telescope-decode-export.png)

## 附录 E：30 样本覆盖记录

全览均为同一显示方向，WT/hybrid 采用 WT 朝向，原生 TRELLIS 保持自身朝向；各物体仅为可读性居中并等比缩放。不是最佳视角评选，也不是精确输入相机重投影。以下记录用于覆盖问题类型，不给未经盲评的逐样本胜负分数。

| 样本 | 本次核查重点/补充现象 |
| --- | --- |
| `multi001_chess_set_marble` | 相对布局与各棋子形态；hybrid 可见小块漂浮几何，黑白材质需排除光照因素 |
| `multi006_jewellery_flatlay_layout` | 多物体布局、细链、珠串与颜色；两种 mesh 丢失细小装饰，不能只比整体轮廓 |
| `obj008_lowpoly_tree` | 原生完整叶层较规整；hybrid 树冠层次/底部形态变化，WT 点边缘需排除密度影响 |
| `obj014_leather_briefcase` | hybrid 保留输入斜视方向；WT 锁扣、皮革细节清晰，mesh 深色外观不能直接当材质误差 |
| `obj015_wooden_train` | 原生转向正前方；hybrid 保留侧向构图，连杆、车轮与文字需单独观察 |
| `obj025_cartoon_dino` | 后脑重复面部为着色问题；原生 GLB 还有额外大块底板 |
| `obj035_cartoon_icecream` | 两种 mesh 正面较可比；hybrid 眼周和脸部颜色/形状偏离更明显 |
| `obj040_leather_armchair` | 朝向与皮革凹凸分开判断；mesh 无灯光 base-color 图偏暗，不据此判定所有细节缺失 |
| `obj044_anime_sneaker` | 原生与输入方向较接近；hybrid 鞋带、鞋面图案和轮廓有变化 |
| `obj062_bengal_tiger` | hybrid 保留侧身，原生更正向；条纹和四肢结构需区分纹理与几何 |
| `obj063_trex_dinosaur` | 原生朝向与输入不同且带额外底板；hybrid 保留侧身但局部比例/细节变化 |
| `obj067_triceratops` | 朝向收益明显；角、颈盾、腿与尾部完整性是重点 |
| `obj069_pixar_dwarf` | 后脑正脸由后层着色导致；hybrid 正面胡须、衣饰和锤子细节也有独立退化 |
| `obj070_red_fox` | hybrid 保留侧身；毛发高频纹理、尾部边界与腿部结构变粗 |
| `obj071_griffin` | 羽翼方向较接近输入；羽片、尾部及漂浮片段需关注 |
| `obj072_power_armor` | 三者朝向较可比；面罩、发光区与装甲表面不能只比 RGB 亮度 |
| `obj083_chibi_swordsman` | 后脑正脸为着色问题；hybrid 正面脸部与发束细节偏移 |
| `obj085_pterodactyl` | 原生偏向正面，hybrid 保留侧向飞行姿势；翼膜/喙/爪尖为细结构 |
| `obj087_industrial_mech` | hybrid 大姿态较接近输入；小机械零件、手部结构与表面细节变简 |
| `obj101_crimson_battle_mech` | 非对称姿态、枪和盾相对位置；WT 后层显示与真正的遮挡完成应分开 |
| `obj107_cyberpunk_exoskeleton` | 对比局部装甲、线缆和关节；总体方向差异小于动物侧视例 |
| `obj110_aqua_diving_mech` | 风扇/管线/机械手的空隙与材质；可能的连接增厚需中性几何复核 |
| `obj120_sea_serpent_leviathan` | 环绕躯体、鳞片、须和浪花；透明/反光观感不纳入本次材质定量 |
| `obj122_bronze_athletic_discobolus` | 大姿态三者较接近，是“原生不总失配”的对照；金属高光与几何凹凸分开看 |
| `obj123_jade_dragon_curio` | 主圆孔三者均保留；龙头、雕纹和底座细孔退化，说明填充并非所有孔洞都封死 |
| `obj125_bronze_lion_guardian` | 原生正面与输入斜向不同；hybrid 保留方向，狮毛和底座装饰需细看 |
| `obj138_retro_camper_van` | hybrid 方向接近输入；窗户、车轮、行李架和车身花纹有变化 |
| `obj141_brass_telescope_orrery` | 完整核查 mask→结构→decoder→GLB；shared-WT 恢复多条细环 |
| `obj147_crystal_palace_glass` | 尖塔/窗洞/底座与透明材质均复杂；base-color 图不足评估玻璃质量 |
| `obj149_hand_painted_kokeshi_set` | WT 后脑面部为着色问题；原生默认方向呈背面，hybrid 面朝输入但彩绘图案变化 |

全览图：[1–5](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/contact-01.jpg)、[6–10](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/contact-02.jpg)、[11–15](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/contact-03.jpg)、[16–20](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/contact-04.jpg)、[21–25](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/contact-05.jpg)、[26–30](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/contact-06.jpg)。除四个面部案例及望远仪专项外，其余条目以该方向全览和用户的多视角浏览为基础，未声称逐一验证所有背面与内部拓扑。

## 附录 F：证据、计时与复现边界

诊断产物目录：`/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/`。原始推理产物保持不变。

- [audit.json](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/audit.json)：30 样本/120 run 的配置、SHA-256、mesh 规模、patch 相位和逐阶段结构统计。
- [summary.json](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/summary.json)、[extra-diagnostics.json](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/extra-diagnostics.json)：本文表格与四例后视、腐蚀核查的机器可读数据。
- [render-validation.json](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/render-validation.json)：实际 patchify 往返与诊断渲染设置；[source-sha256.json](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261015/source-sha256.json)：相关源码指纹。
- 同目录保留 `analyze_r1.py`、`render_r1.py`、`extra_diagnostics.py`、`summarize_r1.py` 和 `reproduce.sh`；需在项目 Conda 环境及独立 screen 内运行。绘图依赖安装到任务临时目录，不改项目环境。TRELLIS.2 源码锁定在 `75fbf0183001ed9876c8dbb35de6b68552ee08bd`。

结构复算没有随机采样；viewer 采样 RNG 为 42；离屏点图使用全部有效点，半径 1 px；四例后视采用绕相机 Y 轴 180° 的正交诊断。全览为 384²、每物体 AABB 居中并等比归一最大边长为 0.9、共同相机距离 4、焦距 `384×4/1.2`；不旋转原生资产去匹配输入，不做 GT 配准。GLB 全面渲染只读 base color，不模拟 PBR 光照和透明度；几何法线来自原始点图局部差分或 mesh，均是诊断图而非真值。

历史单样本耗时中位数为 WT **11.80 s**、原生 TRELLIS **359.20 s**、默认 hybrid **212.77 s**、shared-WT **215.85 s**。mesh 记录包括生成及导出、hybrid 合计包括对应 WT 耗时；不含统一的冷启动权重加载。原生修复队列与原 hybrid 的并发/IO 条件不同，**只能作本次运行成本记录，不能据此声称 hybrid 的算法速度更快**。完整耗时分布保存在 summary，未替换为论文的硬件吞吐数值。

## 附录 G：2026-10-19 新版 viewer 下的逐项追踪

### G.1 图像条件：同一图源，不是同一个模型输入张量

对指定 20 张图的 40 份 hybrid，保存的 `rgba.png` 均与源图像素一致；实际复算的 WT RGB/mask 均与保存值一致；hybrid 的 TRELLIS 图像预处理结果均与原生 TRELLIS 一致。区别在处理链：

```text
同一原始 RGBA（本次均为 1376×768）
  ├─ WT：前景占画布 2/3 → 504×504 → 灰底/黑底合成 RGB
  │       alpha>127 → 默认 WT 不腐蚀 / 默认 hybrid 腐蚀 2 px → WT XYZ/mask
  └─ TRELLIS：最长边先限制 1024 → alpha>204 定位紧裁剪
          → alpha 合成黑底 → DINO 图像条件 512 / 1024
```

WT 的腐蚀作用于有效 mask，未用于抹掉 RGB 边缘，也未改写原始 RGBA。TRELLIS 仍能在图像条件中看到 WT 几何引导已经失去的细线。原生 TRELLIS 的 Stage 1 与后续生成共用这套图像条件；hybrid 用 WT 结构替换 Stage 1 的结构输出，**图像条件仍按 TRELLIS 自身流程产生**。[WT 保存与 mesh 入口](/data1/LiuShuqi/code/world_tracing/wt/batch.py:287)、[注入流程](/data1/LiuShuqi/code/world_tracing/wt/textured_mesh/pipeline.py:186)、[TRELLIS 预处理](/data1/LiuShuqi/code/world_tracing/dependencies/TRELLIS.2/trellis2/pipelines/trellis2_image_to_3d.py:127)

因此冰淇淋的问题不能描述为“Stage 2 看了另一张图”，但它确实接收**不同裁剪、分辨率及前景语义的条件**。两种表示间也没有显式二维对应约束。[冰淇淋条件对照](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/obj035_cartoon_icecream-defaults-v1-conditions.png)

### G.2 五个几何损失/污染案例

| 样本 | WT 默认 → hybrid 默认有效像素 | 删除比例 | 仅端点 → 插值 → closing → hole-fill 的占据数 | 结论 |
| --- | ---: | ---: | --- | --- |
| `multi001_chess_set_marble` | 14,957 → 11,402 | 23.77% | 473 → 506 → 518 → 518 | 上游信息损失与局部不连续增加有证据；漂浮碎片不能全归因于填充 |
| `obj035_cartoon_icecream` | 35,904 → 33,711 | 6.11% | 1,995 → 2,588 → 2,641 → 2,641 | 默认 hybrid 面板确实使用腐蚀；固定形状后黑斑仍随纹理 seed 明显变化，且烘焙前已存在 |
| `obj040_leather_armchair` | 72,949 → 69,794 | 4.32% | 3,216 → 4,619 → 4,791 → 4,791 | 粗结构显著增厚；侧板/背板在保存的 decoder PLY 中已存在 |
| `obj120_sea_serpent_leviathan` | 55,141 → 48,779 | 11.54% | 2,801 → 3,103 → 3,348 → 3,348 | 盘绕空隙和薄结构退化已存在于 decoder PLY；还混有不透明导出的外观影响 |
| `obj141_brass_telescope_orrery` | 41,483 → 35,551 | 14.30% | 1,891 → 1,997 → 2,111 → 2,111 | 细环在 mask 阶段已经损失，shared-WT 恢复多条细环；详见附录 D |

**棋子。** 黑 0 / 灰 128 是 RGB 背景值，mask 本身是布尔量。在相同有效前景内，L0 相邻点距离大于物体最长边 1% 的比例，WT 默认为 **0.640%**、hybrid 上游为 **1.574%**；支持局部几何更不连续的观察，但该量不是有 GT 的噪声率。两份上游的 L0 对应点位移中位数为最长边的 **1.91%**，不只是少掉边缘。shared-WT 插值新增 2 格，默认新增 33 格；说明上游变化也改变了插值路径。[mask 对照](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/multi001_chess_set_marble-mask-difference.png)

**冰淇淋：预处理与黑“胡子”的归因（2026-10-20 补充）。** 用户所说的“左下”指 viewer 的默认 hybrid 面板，该配置确实使用 `alpha_erode=2`，删除 **6.11%** 前景；此前按物体空间位置统计四象限，不能用于反驳面板层面的观察。默认 hybrid 的五官扭曲、局部凹凸仍不能全部归于轮廓腐蚀；shared-WT 同时改变背景与腐蚀设置，并非 erosion 单因素对照。[mask 对照](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/obj035_cartoon_icecream-mask-difference.png)、[decoder / GLB](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/obj035_cartoon_icecream-decode-export.png)

WT 不向 TRELLIS 传颜色，但**材质生成同时依赖图像条件和形状 latent**：`sample_tex_slat()` 传入 `concat_cond=shape_slat`，纹理解码还使用形状解码的细分结构。因此几何改变可以间接改变颜色；这不是把 WT 的黑色背景直接复制到贴图。参考图已有棕色眉毛，异常主要是眉毛加粗、加深，以及新增眼下和嘴周深色区域。[纹理采样与解码](/data1/LiuShuqi/code/world_tracing/dependencies/TRELLIS.2/trellis2/pipelines/trellis2_image_to_3d.py:407)

**对照设计。** 独立实验 `20261020-icecream-texture-seeds-v1` 复用 R1 两份 WT 预测（WT seed=42），各以 shape seed=42 复现并缓存形状，再仅改变纹理 seed 为 **7 / 42 / 123**，共六份结果。沿用 `1024_cascade`、shape/texture 各 12 步、`ray_steps=4`、4096² 贴图和 100 万面导出目标。两组复现的顶点坐标、面索引均与原 R1 decoder PLY 完全一致；组内三次共享相同 shape latent 与导出前几何，两组图像条件张量也逐元素一致。**纹理阶段独立重设 seed=42，不等于原 R1 从整个 pipeline 开始设 seed=42 后到达纹理阶段的随机数状态。**

| 配置 | 纹理 seed=7 | 纹理 seed=42 | 纹理 seed=123 |
| --- | --- | --- | --- |
| `wt_trellis2/defaults-v1` | 两张脸的眼周、嘴周及冰淇淋边缘有大面积黑斑 | 黑斑显著减轻，但虹膜/瞳孔颜色仍失真 | 上层脸明显发黑，下层脸出现大片棕色区域 |
| `wt_trellis2/shared-wt-v1` | 无同等大面积黑“胡子”；嘴部偏红，上层嘴周红色扩散 | 无同等大面积黑“胡子”；嘴部偏红、眼睛颜色变化 | 无同等大面积黑“胡子”；眼睛、嘴部及甜筒颜色仍与其他种子不同 |

**验证与结论。** 六份结果均比较了无光照 GLB 底色与烘焙前材质预览；默认组 7、123 的深色区域在烘焙前已存在。因此本例主要黑斑已形成于**依赖形状条件的材质生成／解码链**，不能仅归因于 viewer 光照或 UV 烘焙。固定形状下颜色仍大幅变化，确认纹理采样具有明显的种子敏感性；这三次试验中默认组形状条件关联更严重的材质退化，shared-WT 则未复现同等黑斑，但也没有稳定保留参考图颜色。[GLB 底色六图](/data1/LiuShuqi/output/world_tracing/experiments/20261020-icecream-texture-seeds-v1/previews/texture-seeds-glb.png)、[烘焙前六图](/data1/LiuShuqi/output/world_tracing/experiments/20261020-icecream-texture-seeds-v1/previews/texture-seeds-prebake.png)

**边界。** 固定的是 shape latent 和导出前网格；GLB 重网格化后面数、拓扑略有变化，不能宣称六份导出几何逐元素相同。烘焙前预览在原网格顶点采样材质后作三角形插值，并非逐像素体材质渲染。一个样本、三个纹理种子不能估计通用失败率，也不能分离 WT 背景、腐蚀、插值/closing 或材质生成器与解码器各自的贡献；两组稀疏坐标不同，相同 seed 也不代表逐位置相同噪声。仍需进一步消融才能把黑斑具体归责于某一项 hybrid 操作。

六份 GLB 均通过 viewer full 加载检查，20 个原实验文件 SHA-256 保持不变。新目录保留 shape/texture latent、烘焙前材质体素、配置与复现脚本；使用 `viewer.py --experiment <新实验目录>` 后在 Seed 中全选即可比较。[实验目录](/data1/LiuShuqi/output/world_tracing/experiments/20261020-icecream-texture-seeds-v1)、[验证记录](/data1/LiuShuqi/output/world_tracing/experiments/20261020-icecream-texture-seeds-v1/validation.json)、[逐种子观察](/data1/LiuShuqi/output/world_tracing/experiments/20261020-icecream-texture-seeds-v1/observations.json)

**椅子。** 默认最终支持域中 **32.87%** 的格子不在端点占据中，主要来自插值。中性多视图显示侧面/背面面板已在 PLY 中存在，GLB 主要进一步平滑。可以确认新增几何和粗结构增厚，**不能仅凭不可见侧没有参考图就证明该板必定是错误内部填充**；真实背面也可能有侧板。尚需固定 WT、关闭插值/closing 的生成对照。[decoder / GLB](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/obj040_leather_armchair-decode-export.png)

**海蛇。** 默认最终支持域新增比例为 **16.34%**；中性几何仍呈现盘绕部位的宽面和闭塞，说明并非只有深色纹理造成观感。原始 PLY 已有这些形状，尚不能把插值、首次 mesh 补洞及模型生成的贡献完全分开。其默认 hybrid 表面采样约 **19.98%** 的纹理 alpha 小于 0.95，但导出强制 OPAQUE；这会让水浪等薄片显得更实，和拓扑问题应分别记录。[decoder / GLB](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/obj120_sea_serpent_leviathan-decode-export.png)

“surface modeling 与 volume fill 冲突”的准确表述是：**WT 的无内外判断插值可能给出不合适的 coarse latent 支持域，TRELLIS 后续没有保证修复它。** O-Voxel 的高分辨率表面激活、压缩后的稀疏 latent 坐标和实体占据是三个不同概念。`1024_cascade` 还会从低分辨率预测重新产生高分辨率支持域，并非始终原样保留注入格子。2026-10-19 的核查只复算了注入结构；2026-10-20 的冰淇淋实验新增固定形状、改变纹理种子的生成对照并保存 latent，但未改变填充策略，仍不能把填充冲突假设提升为所有案例的已证实因果。[TRELLIS.2 §3、§4.5](https://arxiv.org/html/2512.14692v1#S3)、[cascade 实现](/data1/LiuShuqi/code/world_tracing/dependencies/TRELLIS.2/trellis2/pipelines/trellis2_image_to_3d.py:280)

### G.3 Faithfulness、方向与细节：按指定案例核查

| 观察组 | 样本与核查结果 | 归因边界 |
| --- | --- | --- |
| 输入视角忠实度 | 棋子数量/布局、`obj025` 表情轮廓、`obj083` 五官服饰、`obj149` 彩绘均支持 WT 更贴近输入；默认 hybrid 有额外形状/纹理变化 | WT L0 使用输入 RGB；整体 `WT > TRELLIS > hybrid` 可作为这组主观概括，不代表每个维度或每张图严格排序 |
| 朝向收益 | `obj014` 手提箱、`obj015` 火车、`obj063` 恐龙、`obj138` 房车均能看到 hybrid 保留 WT 的输入方向，而原生 TRELLIS 朝向不同 | 是方向保持，不是恢复标定相机姿态或重新测得的姿态准确率 |
| `obj149` 特例 | 原生默认方向为背面，hybrid 为正面；因此 hybrid 在方向上优于原生，即使局部彩绘不够忠实 | 比较纹理细节时需明确是否人为转动原生；否则“image-aligned 排名”混入了不同可见面 |
| `obj070` 狐狸 | TRELLIS/native 与 hybrid 的爪部轮廓和连续表面更清晰；原生转到侧面后也看到额外深色条带，非输入中忠实重建 | 分辨率、表面表示与先验共同作用；清楚的爪形不等于 GT 几何更准，外观异常另见 G.5 |
| `obj125` 狮子滚球 | 原生/mesh 能给出更连续的球体与装饰结构；WT 输入中细孔/雕纹只占少量像素 | 球部清晰度需和孔洞拓扑、生成装饰是否忠实分开 |
| `obj107` 外骨骼、`obj110` 潜水机甲 | mesh 的关节、线缆、风扇等有完整表面优势；同时机械部件、发光区和局部比例会改变 | “高频细节更多”可以成立，“每项都比 WT 准确”尚无 GT 支持 |
| `obj147` 宫殿阶梯 | WT 的阶梯与栏杆受有效图像采样和点云稀疏限制；mesh 给出连续台阶，仍有尖塔/窗洞与材质偏差 | 不能仅凭连续表面断言已恢复真实细阶；玻璃外观也受导出和生成材质限制 |
| patch 白线 | 原始 XYZ 的 14 px 边界统计仍成立，详见附录 B | 新版 full 不再抽样；balanced 的 50k WT 点仍可能放大缝隙，漏拼 patch 已排除 |

分辨率核查（bbox 为 WT 504² 中实际前景范围，不把留白计为物体细节）：

| 样本 | WT 前景宽×高 | TRELLIS 紧裁剪边长，进入 DINO 缩放前 |
| --- | --- | ---: |
| 狐狸 | 336×183 | 884 |
| 外骨骼 | 298×336 | 542 |
| 潜水机甲 | 336×205 | 866 |
| 狮子 | 311×336 | 506 |
| 宫殿 | 220×335 | 534 |

TRELLIS 随后产生 512/1024 条件；将紧裁剪放大至 1024 不会创造真实图像细节，但其输入覆盖率和生成表示与 WT 不同。尚未做同一 WT checkpoint 的可支持分辨率消融，不能量化“分辨率”占所有细节差距的百分比。[宫殿输入对照](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/obj147_crystal_palace_glass-resolution.png)

### G.4 尺度：整体尺度、形状比例和显示视角分开

当前 viewer 只居中/平移，不逐物体归一尺度；hybrid 默认恢复到它自己的 WT parent 尺度，原生 TRELLIS 保持 canonical 输出。下表是原始显示方向下 AABB 的宽、高、深（任意模型单位，不是米）；未对原生姿态做配准：

| 样本 | WT 宽 / 高 / 深 | 原生 TRELLIS 宽 / 高 / 深 | 解释 |
| --- | --- | --- | --- |
| 珠宝 | 0.999 / 0.589 / 0.416 | 0.998 / 0.584 / 0.535 | 最长边相差不足 0.1%，主要差在深度/布局；不是全局缩放倍数错 |
| 树 | 0.569 / 0.996 / 0.540 | 0.610 / 1.002 / 0.605 | 最长边相差约 0.6%，枝叶横向与深度更宽；属于形状比例差异 |
| 玉龙 | 0.905 / 1.227 / 1.229 | 0.875 / 1.002 / 0.374 | WT 包围范围确实更大，尤其隐藏方向深度；不能用一个等比缩放消除 |

三例默认 hybrid / 自身 WT parent 的最大边长比分别为 **1.005、1.008、1.020**，没有发现重复逆缩放。玉龙的 AABB 可能受隐藏层范围或少量极值影响，本次没有将其当作物体真实厚度误差。WT 与原生 TRELLIS 也没有共同的物理尺度标定。[珠宝](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/multi006_jewellery_flatlay_layout-same-scale.png)、[树](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/obj008_lowpoly_tree-same-scale.png)、[玉龙](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/obj123_jade_dragon_curio-same-scale.png)

### G.5 狐狸偏黑：资产与渲染共同作用

按三角形面积抽取 50,000 个表面样本（seed=42），通过 UV 读取保存的贴图，而非统计包含空白区的整张 atlas：

| 狐狸输出 | 金属度均值 | 粗糙度均值 | 保存底色亮度均值，0–255 |
| --- | ---: | ---: | ---: |
| 原生 TRELLIS | 0.9989 | 0.9985 | 87.45 |
| 默认 hybrid | 0.9968 | 0.9834 | 84.62 |
| shared-WT hybrid | 0.6118 | 0.8753 | 84.86 |

这些亮度是资产自身表面统计，**不是与输入对齐的误差或质量分数**。主要发现：

1. **保存资产的毛皮材质异常。** 原生和默认 hybrid 近乎金属度 1，不能用毛皮的正常漫反射解释。`baseColorFactor=[1,1,1,1]`，没有统一乘暗因子；导出按 G=roughness、B=metallic 打包，未发现通道互换。未保存解码后的材质属性体，因此当前只能定位到“生成/烘焙所得资产”，不能继续断言一定是模型预测还是烘焙插值。
2. **PBR 会进一步改变外观，材质因素已有显示消融。** 同一默认 hybrid GLB，在同一 Viser 相机和默认灯光下，仅将 `metallicFactor` 设为 0 就变亮；无光照底色又有不同观感。原文件不变。原生狐狸的无光照底色也有深色条带/偏色，因此不能认为一切都由灯光造成。[Viser 材质对照](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/fox-browser-hybrid-default.png)、[原生底色与几何](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/fox-trellis-material.png)
3. **服务端没有把原生纹理整体压黑。** 狐狸 full 路径逐项验证 POSITION、NORMAL、UV、面索引、材质参数保持不变；原生狐狸 balanced 与 full 的无光照 RGB 均值差约 −0.1～−0.2/255，不能解释明显偏黑。hybrid 纹理 atlas 的缩小影响更大，需用 full 评细节，不能把原生检查泛化给所有资产。
4. **浏览器仍重算法线。** 本地 Viser 无条件重算导致保存法线发生变化，原生/默认 hybrid 的超过 10° 顶点比例为 16.2%/58.3%。这是独立的着色干扰；位置、拓扑没有因此改变。当前未用修改依赖的方式消融其亮度贡献。
5. **不能直接把 WT RGB 与 PBR 屏幕亮度当成纹理误差。** 输入包含原图光照，PBR 则受底色、金属度、粗糙度、法线和环境光共同影响。glTF 规定底色用 sRGB、metallic/roughness 用线性通道；本轮没有证据支持另一个“重复 gamma”错误。[glTF 材质规范](https://github.com/KhronosGroup/glTF/blob/main/specification/2.0/Specification.adoc#metallic-roughness-material)

### G.6 证据与复现范围

本轮目录：`/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/`。

- [review.json](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/review.json)：20 样本的图像一致性、WT 复算、结构数量、尺度和狐狸法线/显示检查。
- [extra-review.json](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/extra-review.json)、[resolution.json](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/resolution.json)、[material-audit.json](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/material-audit.json)：对应点差异、四象限 mask、分辨率与 60 份 GLB 的表面材质采样。
- 全览：[1–4](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/review-contact-01.jpg)、[5–8](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/review-contact-02.jpg)、[9–12](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/review-contact-03.jpg)、[13–16](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/review-contact-04.jpg)、[17–20](/data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1/analysis/20261019/review-contact-05.jpg)。全览为可读性分别居中、等比缩放，不用于证明尺度；G.4 的专用图才共用单位和相机。
- 保存诊断脚本及源码指纹；原始推理文件未改。离屏渲染使用完整面和全部 WT 点，无光照底色/中性法线，不模拟原图光照；raw glTF UV、纹理和几何与 trimesh 读取结果交叉核对通过。浏览器材质对照使用本地 Viser 1.1.1 与临时 Chromium，图上明确标出原始 PBR、仅取消金属度、无光照底色。
- 未补跑模型推理、体素构造生成消融、背面 GT 或正式质量指标。浏览器自动化未完成全部三种狐狸资产的截图，只采用已经核对标签的默认 hybrid 对照，不声称三组浏览器测试全部通过。
