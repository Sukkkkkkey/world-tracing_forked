# 项目历史记录

归档日期为 2026-11-07，内容来自恢复完成版本 f00327fc86540047c38cb8553de3d480f6cc32d4。

下文保留各阶段当时的状态、命令和路径。当前服务器状态及操作入口见 [PROGRESS](/mnt/cpfs1/shuqiliu/code/world_tracing/PROGRESS.md) 和 [RUNBOOK](/mnt/cpfs1/shuqiliu/code/world_tracing/RUNBOOK.md)。

## 历史进度

### 2026-10-20 Ablation 浏览与查看器模块整理

- `viewer.py --experiment` 自动识别 WT `<样本>/<配置>/prediction.npz` 目录；支持配置多选并排、按样本加载，以及各配置输入图和参数切换，默认 full / 表面颜色。
- 通用交互留在 `viewer.py`；GLB、mesh 格式处理迁到 `viewer_utils/glb.py`、`mesh.py`，GSO 与 WT ablation 分别由 `gso.py`、`ablation.py` 适配。
- 28 项查看器回归通过；`validation/z-root-cause-20261020/inference` 的 3 个样本、15 份输出验证通过。此目录未声明完整 GT，页面明确提示；没有改写实验或原始数据。验证边界与日志见 RUNBOOK。

### 2026-10-20 R2 四方法与逐样本分析

- [R2 分析报告](docs/20261020_hybrid-baseline_20261013-R2-gso-quant-v1.md) 已覆盖全部 100 个正式物体、400 项结果，并增加论文 Table 1 的形状与深度对照；明确跨协议数值不能直接判定复现成败。
- 全部 1,600 个形状值复算一致，100 个 GT 重渲染与输入一致；完成全量逐图检查及六个重点案例的 decoder PLY / GLB 对照。形状均值为 TRELLIS.2 > Pixal3D > WT > hybrid；共同有效 81 个物体上 WT 的深度优于 hybrid。
- 分析证据存于 `validation/r2-analysis-20261020/`；修正了分析图中的 Pixal3D 原生观察方向。正式实验和工作簿成绩保持原样，未用新 seed、手调配准或替换样本改善分数。

### 2026-10-20 P0 逐样本分析

- 完成固定 10 个 pilot 样本、四方法及 shared-WT 对照共 50 项的指标复算与逐图核验；四个形状指标全部与保存值一致，10 个 GT 重渲染与输入逐像素一致。
- [P0 分析报告](docs/20261020_hybrid-baseline_20261013-P0-gso-pilot-v1.md) 区分形状、姿态和纹理，逐项核对用户观察，并定位 Hat 内腔额外点、Horse/Pixal3D 和 Bull/hybrid 导出前已有的几何缺陷。证据与复查脚本存于 `validation/p0-analysis-20261020/`。
- 本次只读分析既有实验，未重跑模型或覆盖原成绩；R2 不纳入该报告。

### 2026-10-20 带纹理 mesh 与 GT 显示

- 查看器支持 OBJ 多材质库与相对贴图路径、GLTF/GLB 外部资源、带面及 UV/TextureFile 的 PLY；有面的 PLY 自动按 mesh 显示。外部资源变更会使显示缓存失效，缺失材质/贴图在页面提示。
- GSO GT 优先使用 inventory 中的原始带纹理模型和 camera.json 保存的资产→世界→相机变换；缺失来源或变换时回退到原评测几何。评测文件、冻结清单与原始数据保持不变。
- 26 项查看器回归通过。Frozen Olaf 与 MEAT_SET 的 4096×4096 GT 贴图和坐标校验通过，边界最大误差小于 1e-7；full 服务器准备约 0.63/0.86 秒，不包含网络与浏览器渲染。使用说明见 README，验证日志见 RUNBOOK。

### 2026-10-20 Excel 预览兼容修复

- 修复 Office Viewer 4.2.2 因无法识别 openpyxl 批注部件而静默显示空白 Sheet1 的问题；当前工作簿及后续研究记录导出均使用兼容的内部部件路径。
- 原文件已备份，所有单元格、批注、链接、样式和合并区域核验保留；2 项回归及插件原解析器加载通过。本地 VS Code 需关闭旧标签页并重新打开，UI 尚未人工确认。路径、根因与核验记录见 RUNBOOK。

### 2026-10-20 Pixal3D R1/R2 完成复核

- 后台队列于 2026-10-19 22:18 正常结束，`pilot.exit=0`、`formal.exit=0`，本任务推理 screen 已自然退出。当前没有执行阻碍。
- P0：10/10 推理、形状评价及验收通过（10 月 19 日 17:15）；R1：30/30 推理与产物验收通过（17:45，无 GT 定量评价）；R2：100/100 推理、形状评价及验收通过（22:17）。无失败或待处理 Pixal3D run。
- 今天重新核对逐样本状态、既有验收报告和工作簿；旧 P0/R1/R2 的 131/271/1001 条输入及结果索引摘要均未改变。复核报告：`/data1/LiuShuqi/output/world_tracing/validation/pixal3d-progress-20261020.json`。本次没有重跑推理或评价，也没有重复逐网格哈希验收。
- R2 的四方法共同成功集合为全部 100 个物体。在当前 `gso-shape-sim3-v1`、seed 42、1024 配置下，CD-L1 和 F-score 排序均为 TRELLIS.2 > Pixal3D > WT > WT+TRELLIS.2 hybrid。Pixal3D CD-L1=0.011763，F@0.01=0.642681，F@0.05=0.971770；这是本项目协议结果，不是论文数值复现。
- 根目录 `experiments.xlsx` 已更新，`FourMethodShape` 包含 P0/R2 四方法比较。Pixal3D 的 native-camera 与 SSI-depth 仍为 N/A：原视图尺度变换尚未验证；本次完成范围为 R1 产物和 R2 形状评价，不含这些相机指标。

### 2026-10-20 查看器多选与显示默认值

- Method、Config、Seed 改为可折叠的多选勾选列表，提供全选/清空。Method 与 Config 默认全选，Seed 默认第一个；刷新保留有效选择，清空筛选不影响独立 GT 开关。
- 单文件与实验入口默认 full + 表面颜色，可继续通过命令行或页面覆盖。
- 6 项相关回归通过，覆盖多方法/配置/seed 组合筛选、空选择、刷新、过期加载取消及真实 HTTP/WebSocket 交互。使用说明见 README，验证日志见 RUNBOOK。

### 2026-10-19 Pixal3D 对比基线：第二阶段（已完成）

- 新增独立模型适配器和追加入口，复用现有 R1/P0/R2 冻结输入；原三方法推理范围保持原样。结果注册、查看器、形状评价和四方法共同成功统计已联动。
- 固定配置为 `resolution1024-v1`、seed 42、12/12/12 步、4096 纹理和官方 low-VRAM 模式；普通上游默认 1536，因此没有把 1024 配置称为官方默认。
- 38 项契约/评价/原入口回归通过；新增 GPU 分片后 7 项 Pixal3D 专项测试通过。旧实验输入与索引摘要保存在 `validation/pixal3d-existing-results-before.json`。
- 权重已全部下载并通过逐文件校验，清单为 `weights/pixal3d/manifest.json`，新增占用约 22 GiB。DINO 与 decoder 按校验摘要复用已有文件；NAF 从固定本地源码和显式 checkpoint 加载。
- briefcase 真实预训练单样本通过：模型加载 185.6 s，生成/导出 517.9 s；633 万面 decoder PLY 与约 38 MiB GLB 均通过重载和摘要检查，旧 R1 的 271 条索引未变。报告 `validation/pixal3d-single.json`。这是首次冷启动样本，不代表稳定批量速度。
- `wt-pixal3d-pilot`、`wt-pixal3d-formal` 已按单样本→P0→R1→R2 顺序完成推理、适用的形状评价、验收与工作簿更新，两个队列退出码均为 0；完成复核见上方 2026-10-20 记录。
- 形状使用原 `gso-shape-sim3-v1`；Pixal3D 归一化相机距离尚未验证到原始视图的真实尺度变换，native-camera / SSI-depth 标为 N/A，原因随结果保存。

### 2026-10-19 Pixal3D 对比基线：第一阶段

- 按用户确认的结构，独立克隆 `/data1/LiuShuqi/code/Pixal3D`，固定 `f7cf38429b0bd264f1995f0f8743a88b1c728b94`；`compare_methods/Pixal3D` 为相对软链接。
- 已复制专用环境 `/home/LiuShuqi/.conda/envs/world_tracing_pixal3d`；固定 MoGe-2/NAF 源码，新增环境准备、依赖约束和离线 CUDA 验证入口，说明见 `compare_methods/README.md`。
- 第一阶段已验收：新环境 `pip check` 和六组离线验证通过，包括真实 NATTEN/FlashAttention 数值对照、NAF FP32/1024 通道上采样、MoGe 相机 API、Pixal3D 稀疏卷积及网格算子。报告为输出目录 `validation/pixal3d-environment.json`，`build-16.exit=0`。
- 原 `world_tracing` 环境包清单前后相同，`pip check` 通过，原 utils3d 文件与锁定源码一致。新环境安装快照已保存；NATTEN wheel 与哈希已缓存，支持同配置复用。
- 未下载预训练权重、运行模型生成或追加 R1/R2；下一阶段为独立 adapter 与单样本接入。原始数据和既有实验产物保持不变。

### 2026-10-18 可视化颜色与 mesh 显示修正

- 按 R1 报告 2.4 修正输入 RGB 被广播到 WT 隐藏层的问题。新增灰色、表面颜色、深度模式：默认保留已有真实纹理，无纹理填灰；表面颜色仅用于 WT layer-0；深度覆盖所有结构的颜色。单文件和实验浏览均支持网页切换。
- balanced 保留完整 mesh 拓扑、法线及 UV，仅将纹理最长边限制为 1024 px，点云仍采样至 5 万点；full 不再限制点数。当前样本内最多并行两份结果，256 MiB 缓存；保持选中再加载、GT 默认开启和比较数量不限。
- 20 项 viewer 回归通过。文档中的 4 个 R1 样本及含 GT 的 P0 MEAT_SET，默认灰色 + balanced 的本机接收为 3.44–4.62 秒；三模式共 15 次测量中有一次表面颜色为 5.25 秒，其余低于 5 秒。浏览器渲染未验收（现有 Firefox 驱动无法在此系统启动）；详细测量边界见 RUNBOOK。

### 2026-10-15 网页加载改进

- 实验查看器启动仅扫描 JSON 索引，选中样本后才加载图像、全部匹配结果与 GT；GT 默认开启，取消原有 12 项限制。快速切换时只处理最新选择，旧结果不会覆盖新场景。
- 新增服务器准备进度条、阶段说明和耗时；默认 balanced 为每份 5 万点、20 万面预览阈值、1024 px 纹理，大 mesh 明确显示为顶点预览，full 保留原始 mesh/纹理。提供 64 MiB 预览缓存，不改写源文件。
- 14 项 viewer 测试通过，并扩展验证了过期加载取消。真实 P0 的 MEAT_SET：三方法与 GT 共 4 份几何约 3.8 秒准备完成，同端口 WebSocket 收到约 2.7 MB 和中间百分比。未做浏览器 GPU 画面的人工验收，测试服务已退出；命令与测量边界见 RUNBOOK。

### 2026-10-15 R2 正式实验（2026-10-18 验收完成）

- 固定 eval100 的 100 个 GSO × 三方法默认配置：300/300 推理与评价完成。seed=42、batch=1、1024_cascade；与 P0 独立，不含 shared-WT。
- 配准后 CD-L1 排序：TRELLIS.2 > WT > WT + TRELLIS.2 hybrid。共同有效深度集合 81 个物体；深度质量失败 WT 1/100、hybrid 18/100，错误指标留空，不换样本。
- R2 输出、summary.json、reproduction/validation.json 均位于 20261013-R2-gso-quant-v1；结果文档 docs/20261014_hybrid-baseline_results.md 已以 R2 为正文，P0 移至附录。experiments.xlsx 已按实验 ID 更新。
- 修复 Unicode 资产 ID 校验，26 项批量/几何/目录检查通过；100 个原生结果均确认 Stage 1、无 WT parent，200 个 GLB 容器完整，评价源码与修正后的 P0 一致。
- 2 项首次失败后以原 GPU、原配置和 seed 重试成功；2 项使用已验证的独立行 LayerNorm 显存优化。显存策略与失败记录保存在各 worker/retry-*/。
- R1 120 项、P0 40 项既有结果保留；参数扫描及 best-of-8 尚未运行。

### 2026-10-14 修正完成记录（历史）

- R1 120 项与 P0 40 项推理已完成。修复原生 TRELLIS 误用 WT 缓存的问题，40 个错误原生结果已重新推理并覆盖原目录；最终核验全部执行真实 Stage 1，且 GLB 容器完整、无 WT parent。
- 修复 26,031,912 面网格的 CUDA 光栅化错误：每批最多 100 万面、最近 Z 合并，不简化几何；逐 run 独立进程评价。P0 40/40 评价执行成功，旧错误指标已覆盖。默认 hybrid 有 2/10、shared-WT 有 1/10 深度覆盖率低于协议门槛，指标保留为空值；这属于实测质量问题而非执行故障。
- 9 项批量测试、5 项几何/渲染测试、1 项进程隔离测试通过。原失败大网格现可正常渲染；两个原成功真实样本的 15 项指标最大变化约 3.9e-9。最终核验报告在 P0 的 `reproduction/correction-20261014/validation.json`。
- 当前 10 个 pilot 的配准后形状精度排序为 TRELLIS.2 > WT > hybrid，与论文排序不同；数据、配准/归一化及单 seed 协议不同，不能直接视作论文数值复现。结果与完整协议边界见 `docs/20261014_hybrid-baseline_results.md`；`experiments.xlsx` 已更新，包含论文对照和共同有效资产上的深度对比。
- 已清理中断下载、未采用镜像及临时审计文件；完整 raw GSO、有效产物、WT 缓存与复现所需记录保留。
- 正式 R2 100 个物体与参数扫描仍未启动。

### 2026-10-13 启动与入库记录（历史）

- 实验方案已整理为核心正文 + 附录；默认对比、shared-WT、单因素扫描、独立 GSO 划分及形状/相机/深度协议已复查。固定推理 seed=42、划分 seed=20261013，补齐跨库 RNG 与环境记录。
- R1 正在运行：GPU 0、30 张示例、120 个默认/受控任务，从冻结源码和输入快照执行；60 份 WT 缓存已完成，30 个 WT 基线结果已完成，后续为 90 个 mesh 任务。原生 TRELLIS 默认完整预检已成功，GLB/decoder mesh 重载检查通过，预检结果不并入正式统计。
- 原站 GSO ZIP 下载在约 13 GiB 处 TLS 中断且不支持当前通道的 Range 续传。已从 CRC 正确的原清单确认 944+86=1030 个资产；改按此全集下载固定 revision 的原始 ZIP 镜像，额外 16 个镜像条目不采用。已抽查 20 个资产与原 ZIP 的 OBJ 字节、RGB 纹理像素一致。
- GSO 原始数据已完整保存到 `/home/LiuShuqi/Workspace/data/world_tracing/raw/gso/`（真实路径 `/data1/LiuShuqi/data/world_tracing/raw/gso/`）：1030/1030 个 ZIP 的 SHA-256、解压成员 CRC 与必要文件检查通过，`COMPLETE.json` 已生成，`datasets/gso/raw-ready.exit=0`。原始 ZIP 共 8.07 GiB，解压内容未修改。满足用户的数据前置条件后，已恢复输出目录下的派生入库与 P0 队列；raw 原件后续只读。
- 派生入库完成，1030 个资产全部通过网格/纹理检查，排除 0 个；与未完成原站 ZIP 中可读取的 320 个资产比较，OBJ 字节及 RGB 纹理像素均一致。10/100/920 划分已冻结，互斥性与 PCG64(20261013) 精确重放通过。P0 的 10 张输入和 GT 渲染完成，GPU 1 已启动 40 项默认/shared-WT 推理；正式 R2 尚未启动。
- `experiments.xlsx` 已创建并随首轮任务自动更新，登记 R1/P0/R2 状态、实际配置和逐任务记录；没有伪造定量成绩。相关最小验证为 34 + 3 项通过，`pip check` 通过。
- GSO 渲染与形状/相机/深度评价代码已补齐：5 项数学/真实 GPU 渲染测试及合成资产三方法端到端检查通过；真实物体渲染确认源 Z-up。新增工作簿 `MetricSummary`，报告逐资产均值、失败/待处理及共同成功集合。数据完整门槛与汇总/记录的 5 项测试通过；真实 GSO 评测还未执行。
- 待完成：R1 剩余 mesh 结果、P0 推理/评价与验收、正式 100 个物体定量实验、参数扫描与最终汇总。详细命令、screen、路径和进度边界见 RUNBOOK 最后一节。

### 早期完成项（截至 2026-10-13）

- `viewer.py` 改用 Viser 1.1.1 单端口网页，支持输入图像、预测点云及可选 mesh / 真值 / TRELLIS 输出，并排或单项查看。9 项测试通过，包括数据兼容、交互切换、三种停止信号的端口释放；真实点云/mesh 的 HTTP 与 WebSocket 传输检查通过。Rerun 保留用于原生时间轴及 `.rrd` 读取。
- 保留初始 fork 的 Git 历史、origin 及用户已有项目记录；未提交或推送。
- 配置项目独立 Conda 环境的 WT 与共同 Python 依赖，固定 PyTorch 2.6.0 / CUDA 12.4。
- 沿用 `/data1/LiuShuqi/data/world_tracing` 和 `/data1/LiuShuqi/output/world_tracing`；统一输出、权重及缓存默认路径，原始数据保持只读。
- 下载 TRELLIS.2、CuMesh、FlexGEMM、nvdiffrast、utils3d 及相应子模块，记录精确提交和 FlexGEMM 缓存补丁。
- 覆盖重写 README，新增环境脚本、可复现安装脚本、随机张量验证脚本与路径测试。
- 整理 README 为项目说明书，恢复 package layout、模型及输入输出说明；实验记录集中于 RUNBOOK。清理仓库缓存和依赖编译中间文件，保留运行环境与已有结果。
- WT 物体/场景/动态随机权重 GPU 前向、几何数值检查与 Rerun 输出通过；3 项路径测试通过。
- TRELLIS.2 独立 shape/texture SLat 采样，以及 FlashAttention、O-Voxel、FlexGEMM、CuMesh、nvdiffrast、nvdiffrec CUDA 验证通过。
- 更新 token 后，WT object 权重下载和完整 20 步离线物体推理通过，生成 `validation/object_seed42.rrd`。
- TRELLIS.2-4B 与 TRELLIS-image-large sparse structure decoder 匿名下载完成。三组权重约 22.60 GB，26 个文件大小核验、11 个大权重 SHA-256 校验通过。
- TRELLIS.2 的 512/1024 版本 shape、texture 四个真实 flow 模型严格加载与随机条件采样通过，未使用 WT 衔接。
- 从 ModelScope 匿名下载 DINOv3、RMBG-2.0 的 11 个必要文件，主权重与 HF 官方 SHA-256 一致；通过 TRELLIS.2 原有封装完成真实图像离线 GPU 验证，生成全本地路径的独立 pipeline 配置。
- 调试 WT → TRELLIS.2 桥接：修复 cascade 体素网格与图像预处理，补充输入检查、本地模型选择、显存释放、采样控制和导出坐标元数据。25 项回归测试与随机点图到真实 CUDA flow 检查通过。
- 使用自带 briefcase 图像及预训练权重，512 和 1024_cascade 均完成 WT 推理、体素注入、shape/texture 采样、解码与纹理 GLB 导出；日志退出码均为 0。
- 新增 `docs/CODE_STRUCTURE.md`，按推理顺序维护 WT 原生输出与 TRELLIS.2 hybrid 的调用关系、张量与坐标契约；修复裁剪 K、半像素反投影、抽样尺度拟合和 JSON 变换重载问题，保护权重查询不覆盖下载清单。

### 早期验收记录（2026-10-12 至 13 日）

统一版本环境的独立 GPU 逻辑验收已通过。随机权重结果位于 `/data1/LiuShuqi/output/world_tracing/validation/wt-smoke.json`、`trellis2-smoke.json`；后续真实权重报告为 `weights-integrity.json`、`trellis2-pretrained-stage2.json`，WT 真实输入结果为 `object_seed42.rrd`。日志与命令见 RUNBOOK。TRELLIS.2 使用随机条件和 64 个稀疏点，仅验证兼容性与数值，不代表完整图像生成质量或论文指标复现。

2026-10-12 进度复核通过：`pip check` 无冲突、CUDA 可用，6 个依赖仓库 HEAD 及递归子模块与锁定版本一致；37 个模型相关文件存在且大小匹配，两份本地 pipeline 配置引用齐全。物体推理、Stage 2、权重校验和辅助模型验证退出码均为 0。辅助模型报告为 `modelscope-aux-smoke.json`；复核报告为 `validation/progress-audit.json`。该次复核没有重复运行模型推理或大文件 SHA-256 校验。

2026-10-13 衔接验证：`validation/hybrid-smoke.json` 检查合成点图、体素注入及随机权重 shape/texture flow，未运行 mesh decoder；四种模式的路由由接口测试覆盖。真实输入结果为 `validation/hybrid-512/briefcase.glb` 和 `validation/hybrid-cascade/briefcase.glb`，同目录 JSON 保存坐标和运行参数。完整命令与文件重载检查见 RUNBOOK。本次验证能说明链路可运行，不等同于论文质量或指标复现。

同日结构/坐标复查：工作区 47 项测试通过（包括另行新增的 5 项 viewer 测试），修复后的随机 GPU flow 通过；文档代码示例与两份既有 GLB 的坐标回转检查通过，报告 `validation/coordinate-review.json`。本轮没有重跑完整预训练生成；默认旋转保持右手系，恢复相机坐标时必须同时撤销 GLB 轴旋转和 canonical 平移/缩放。

### 早期缺失项（2026-10-13 阶段记录）

2026-10-13 批量入口与查看器已实现：模型按阶段复用，WT 缓存、配置隔离、断点续跑及 schema v1 产物索引可用；Viser 支持批量选择、横向/纵向比较和刷新。44 项相关测试通过，验证使用合成输入和模拟模型后端；两轮正式实验、GSO 渲染评测与 experiments.xlsx 汇总尚未执行，不能将此状态当成批量预训练结果验收。

- 原始数据 `raw/` 和处理数据 `processed/` 当前为空；验证使用内存随机张量和仓库自带示例，输入文件保持原样。
- WT 场景与动态权重、动态复现参考输出未下载，未进行论文指标复现。
- TRELLIS.2 主权重、结构解码器、DINOv3、RMBG-2.0 均已下载并分别验证。辅助权重改从 ModelScope 获取，原 HF 403 不再阻塞本地运行；WT hybrid 的 512 / 1024_cascade 已产出 GLB。
- 直接 1024 仅验证随机张量 flow，1536_cascade 仅验证接口路由；尚未运行这两个模式的完整预训练 GLB、多样本质量评估、场景/动态衔接或论文指标。独立 TRELLIS Stage 1 完整图像生成流程不在本次 hybrid 验证范围内。

## 历史运行记录


项目介绍、目录结构与快速使用见 [README](README.md)，当前状态见 [PROGRESS](PROGRESS.md)。本文件保留操作命令、实验结果及排障过程；下方历史记录中的缺失状态以最新记录为准。


### 2026-11-07 恢复验收与发布完成

621 项已全部完成，P0 50、R1 150、R2 400、裁剪/背景 15、纹理种子 6 均通过对应验收。`recovery-completion-v3` 队列正常结束，R2 基线、Pixal、预发布和最终发布退出码均为 0。最终发布会话 `recovery-final-publication-v2` 的 run_task PID 为 2166572，子进程为 2166592，2026-11-07 02:50:59 UTC 完成。当前结果见 [恢复报告](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_recovery-results.md)。

- 工作簿 SHA-256 为 `83d72e6b3505864b9c18e2b7c1c0db6261449782618820bfe181dffe7f6f6fcf`。4 条人工结论、4 条实验目的和 11 条备注按身份保留，两条旧报告链接映射到当前 CPFS 路径。总验收记录为 `validation/recovery-20261105/final.json`，数值来源审计为同目录 `workbook.json`。
- 发布脚本新增耗时核验时误把 runtime.json 当作原产物审计的必含字段，首轮因此 KeyError 退出。修正为绑定已审计 run.json、检查有限非负耗时及阶段关系，并记录 runtime 文件摘要后，重新发布通过。原脚本和失败日志存于 `logs/recovery-20261105/attempts/final-publication-runtime-manifest/`。最终 `scripts/finalize_recovery.py` SHA-256 为 `9f248ec60220d63e7528d8400266d8c0bfdb3d5a5801934959a960a1b276648d`。
- R2 两项内存修复通过，两个大型解码网格均已完成评价与审计。保护证明确认另外 298 项的 1,689 个文件及两份 WT 父缓存一致。内存决定 SHA-256 为 `18072f4f1ff514e3ad01efc1e44f99ca8848ec60919e853a05e89480acf356a2`。
- R2 Pixal 的 100 项工作进程阶段耗时 25,514.96 秒，显存峰值 36.22 GiB，实例工作集峰值 115.64 GiB，两个进程退出码均为 0，串行重试为 0。Hefty 废纸篓导出耗时 16,453.28 秒。运行控制目录和 resources.json 随执行记录保存。
- R2 形状评价全部 400 项有效。SSI 深度 WT 有效 99/100，hybrid 有效 80/100。hybrid 前后共同有效 79 个样本的 AbsRel 从 0.028529 变为 0.028805，三项转为质量失败，一项转为通过。旧逐样本预测与输入摘要缺失，跨服务器差异来源尚未定位。
- R2 两视图复核按冻结顺序前五个 ID 加最大 hybrid CD-L1 的样本去重补足十个。已检查四页图像并绑定 manifest SHA-256 `7289b1a6be184cf0ae1574acbc9096230082e35f7b70bf95ef7e027a0f4fed09`。全部一百个 R2 样本完成自动产物和指标审计。
- 工作簿三页维度为 25×32、55×32、405×32。ZIP、人工备注、合并区、列宽、行高、冻结窗格和本地链接核对通过。本地预览副本仅规范化 Content Types 的命名空间前缀，正式 XLSX 摘要保持一致。预览工具生成六张 PNG 后异常退出，显式捕获 Windows 退出码 -1073740791。逐样本页合并单元格预览有遮挡，旧工作簿出现相同现象。原生 Excel 界面尚未验证，详细记录为 `validation/recovery-20261105/workbook-review.json`。

- 已核验归档并删除 31 个旧服务器一次性启动/恢复脚本，活动代码引用为 0。`r2_layernorm_memory.py` 和 `r2_topology_memory.py` 继续用于已验证的恢复入口。旧脚本归档为输出 `recovery/20261105T044019Z/obsolete-launchers/scripts.tar.gz`，清理报告为 `validation/recovery-20261105/cleanup.json`。
- 已删除失败的 `.runtime/failed-environments/pixal3d-offline-cache` 环境副本。清理前表观大小为 7,429,660,738 字节，两个有效环境均无指向该目录的软链接，清理后 Python 3.11.11 启动检查通过。
- 最终源码、Git 工作区状态与任务日志的归档入口为输出 `recovery/20261105T044019Z/final-20261107/manifest.json`。归档程序逐文件记录摘要并读回验证，完成状态由该文件记录。

下方 11 月 5 至 6 日条目保留当时的阶段状态，最终完成情况以上方记录为准。

### 2026-11-05 新服务器恢复记录（阶段历史）

- 代码：`/mnt/cpfs1/shuqiliu/code/world_tracing`；原始数据：`/mnt/oss1/lemonade_factory/SYNC/shuqiliu/data/raw`；处理数据：同级 `processed/world_tracing`；输出：`/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing`。
- 新机 Ubuntu 22.04，系统 Python 3.12 与 torch 2.6.0+cu124；项目独立 Python 3.11，CUDA Toolkit 12.4，A100 80GB / SM80。不修改共享环境。
- 源码与工作簿备份：输出 `recovery/20261105T044019Z/`，包含完整 `source-before.tar.gz`、工作区 diff、包版本与原工作簿。`experiments.xlsx` 原 SHA-256 为 `b2e5a91b6274b918138c8852593070b9e41bee01ad1156ceefa3a598c0e80222`。
- 使用 `/etc/dsw/runtime/tmux/bin/tmux -L wt-recovery` 专用会话。`scripts/run_task.py` 记录 PID、子进程、命令、日志、状态和退出码；活动日志在 `.runtime/logs/recovery-20261105/`，完成后归档到输出 `logs/recovery-20261105/`。本地连接目录 `logs/20261105-recovery.json` 保存恢复入口。
- Miniconda 安装器：官方 `Miniconda3-py311_24.11.1-0-Linux-x86_64.sh`，145900576 字节，SHA-256 `807774bae6cd87132094458217ebf713df436f64779faf9bb4c3d4b6615c1e3a`；安装到项目 `.venv`。
- 依赖固定在 `requirements.recovery.txt`。`scripts/reuse_image_cuda.py --target-python .venv/bin/python --exclude nvidia-nccl-cu12` 由镜像 Python 执行，仅复制与旧版本相同的 Python-independent NVIDIA distribution，并逐文件验证 RECORD。镜像 NCCL 文件与安装记录不一致，未采用；使用官方 cu124 wheel，SHA-256 `8579076d30a8c24988834445f8d633c697d42397e92ffc3f63fa26766d25e0a0`。
- DINOv3/RMBG：`scripts/fetch_modelscope_aux.py`，11 文件已校验。TRELLIS.2 的官方 HF revision 与 ModelScope 每文件 revision、SHA/blob ID 固定在 `configs/recovery_weights.lock.json`；下载配置及权重均须匹配官方字节。Pixal3D 对应 `compare_methods/pixal3d/modelscope.lock.json`。
- GSO 使用固定 raw 镜像 revision `6139aa33f6163a9f1c7352dd386760f40691ce0d`。原 1030 ID 由 Google Kubric 官方清单与该原始镜像求交恢复，P0/R2 与旧工作簿逐 ID 一致；不使用 Kubric 转换后的几何。尚未重新取得失效的 MegaPose 整包，因此不声称本次重新完成了与整包的字节比较。
- 代理由用户开启 `127.0.0.1:18081`；HF 连接间歇性返回 502，下载保留断点。凭据仅从忽略的 `.runtime/hf_token`（600）读取，限官方 HF；不输出凭据。
- 下载已完成：GSO 1030 个原始 ZIP、主/辅助模型与 Pixal3D 22 文件。公开 HF 文件采用用户建议的 hf-mirror 直连，带新查询参数避免过期重定向；单个不可用的 GSO ZIP 经官方授权流程取得后直连 CDN。WT 模型 SHA-256 为 `d61cab86969a8f0763225bd07314b79894605439df11b0030fc21d22e3a1c10f`，6211886598 字节。
- `scripts/recover_dataset.py` 分 raw / derive / render 阶段；处理副本改动只发生于 processed；历史整包比较未重做。`scripts/recover_experiments.py` 按固定 600 项主实验执行 baseline / pixal / audit；`scripts/audit_recovery_experiment.py` 验证样本、配置、真实文件、父预测、完整指标口径，保留 SSI 质量失败。
- 17:28 阶段记录（Asia/Shanghai，后续已完成）：base-install-retry7、base-runtime-repair、base-validation、io-validation、gso-raw-and-derived、gso-render 全部 passed。110 份历史视图完成，p0-baseline 已开始 40 项基础推理。pixal-setup 已完成克隆和附加依赖，NATTEN 正按 SM80 源码编译；不得将安装中视作验证通过。GPU 检查、渲染和正式复跑使用项目 CPFS flock 串行化。
- C++ 修复：原 Miniconda libstdc++ 11.2 不含 CuMesh 所需 GLIBCXX_3.4.30。scripts/setup_cpp_runtime.py 根据 configs/conda_runtime.lock.json 从官方 Anaconda 下载并校验五个 14.3.0 build 4 包，离线装入项目环境；conda-linux-64.lock 记录官方 URL。完整回归 117 项通过，WT/TRELLIS/hybrid GPU smoke 与 pip check 通过。
- Conda 克隆：此版本 CONDA_PKGS_DIRS 使用逗号分隔；scripts/env.sh 和 Pixal 环境脚本已修正。克隆完成判据使用 conda-meta/history，避免把中断目录误作可用环境。失败尝试及日志暂存 .runtime/failed-environments 与 logs/recovery-20261105/attempts，待最终验收后清理。
- 存储修复：OSS 挂载的回退写入返回 EINVAL，首次渲染在写压缩 NPZ 时暴露问题。wt/artifacts.py 先在 CPFS 写完可 seek 文件，再顺序复制到目标旁的临时文件并原子替换；适用于 NPZ 和 torch.save。14 项相关测试（含 2 项新增存储故障测试）及真实 OSS NPZ/PT/PNG/纹理 GLB 读回通过，报告为 validation/artifact-storage.json。渲染与复跑入口核对该报告的写入器源码 SHA。
- 恢复入口：scripts/recover_crop_ablation.py 复跑 15 项裁剪/背景；scripts/recover_texture_seeds.py 复跑 6 项纹理种子；scripts/finalize_recovery.py 在 600+15+6 项验收后生成新汇总并可发布工作簿。工作簿发布前核对人工备注身份、历史参数摘要及当前文件未被外部修改。裁剪/背景对照已完成；纹理种子对照及最终发布仍等待后续阶段。
- 审查修复：Pixal 检查接受已确认的 tmux；新依赖 checkout 直接取固定 commit，已有改动保留；WT 下载脚本读取权限 600 的本地 token 文件。FlashAttention 2.7.3 已安装；生成 wheel 的 SHA-256 为 `1f4990d874df05c04522adec4d4f5a3f76a8453b04fb177088c0d78d2471e8bb`（Python 3.11 / torch 2.6 / CUDA 12，191367817 字节）。
- 20:34 更新：P0 基础 40/40 的推理、评价和审计通过。新旧深度质量失败集合一致：default hybrid 2/10、shared-WT 1/10；数值差异保存于 validation/recovery-20261105/historical-comparison.partial.json。旧工作簿的 450 个逐样本定量行已另存于备份目录 historical-workbook-metrics.json。
- 15 项裁剪/背景对照通过；补齐 PYTHONHASHSEED=42 后，Hat、Frozen Olaf、School Bus 三个默认配置的 XYZ/掩码与本轮 P0 逐元素一致。启动脚本、恢复子进程与任务日志现显式记录哈希种子；不将此检查扩大为对全部跨 GPU 数值一致性的声明。
- Pixal 克隆修复：tqdm、pluggy、zstandard、certifi、idna、requests、urllib3、charset-normalizer 的新 pip metadata 与旧 Conda 模块混存；charset_normalizer 导入报 COMMON_CJK_CHARACTERS 缺失。compare_methods/pixal3d/reconcile_clone.py 备份旧文件、移除重复安装记录、按 clone-python.lock.json / clone-python-repair.txt 离线重装 8 个固定 wheel。缓存 wheel 的包文件与基础环境一致；修复后 192 个安装文件逐项校验、真实字符编码识别及 pip check 通过，再次通过六组 CUDA 验证。此步骤已纳入 setup.sh prepare/check。
- 修复前完整的 10 项 Pixal P0、评价和检查图、原 env.sh / requirements.lock.txt 均归档于 recovery/20261105T044019Z/p0-pixal-before-clone-repair，未计为最终恢复结果。修复后 P0 的 10/10 Pixal 推理、评价与审计均已完成，预处理图和 decoded PLY 与归档首轮 10/10 相同，评价最大差为 0；GLB 字节不要求相同。P0 全部 50 项两视图检查完成，R1 正在执行，之后是纹理种子和 R2，任务失败即停止。已完成的 crop-ablation 会跳过。
- NATTEN SM80 wheel：27899725 字节，SHA-256 69be4bdeb5831cac07dedd49abef6e7dcd3a84cc41fccbf54b4ccc59474b2a8b；源包 SHA-256 810aaf179e1a6fdb0a9279d7858d00412a0d3f045e546cada415205215ccd539，记录于 compare_methods/pixal3d/natten-sm80.lock.json。基础和 Pixal 的实际 pip 清单均已刷新。
- R2 前吞吐测试：用户新增要求后，仅向主协调器 bash PID 628834 发送 SIGSTOP；R1 baseline 子任务继续运行。暂停说明为 .runtime/recovery-r2-benchmark-hold.json。single-gpu-batch-benchmark 专用 tmux 已启动，当前 run_task/子进程为 1143717/1143720，等待 R1 验收后独占 GPU；复核基准前不允许 R2 启动。固定输入、候选与验收标准见 docs/20261105_single-gpu-batch-review.md。首个仅处于等待状态的基准启动在脚本审查补齐后已重启，记录归档于活动日志 attempts/benchmark-before-final-review，未执行候选推理。
- 当前 P0 和裁剪/背景对照已验收，R1/R2 与纹理种子尚未全部完成；工作簿仍保留旧版，等待最终验收后发布。旧机 screen、GPU 编号、路径及结果保留在以下历史记录中，仅作追溯；不得直接运行旧的多卡恢复脚本。

### 2026-11-06 单卡吞吐复核与队列恢复（阶段历史）

- R1 baseline 120/120 项已于 2026-11-06 00:44（Asia/Shanghai）通过；首轮基准于 01:50 完成，按样本均衡分配复测于 10:44 完成。单卡 WT 保持 batch=1；mesh / Pixal 采用 2 个独立进程，测试收益与一致性见 [专项复核](docs/20261105_single-gpu-batch-review.md)。
- scripts/run_parallel_recovery.py 的 11 项相关回归通过；config/source/input 身份校验、单写者锁、分片不重叠、失败归档后串行重试均检查。核心 wt 源码和已验收的 Pixal 环境锁未改变。
- 决策与证据摘要保存在输出 validation/single-gpu-batch-20261105/decision.json，R2 启动门槛强制核对。旧暂停协调器仅负责等待，归档后以更新队列替换，已通过阶段会跳过；本地 logs/20261105-recovery.json 记录新 PID。
- 正式运行的 2 进程会合计使用同一张 GPU，不是张量 batch=2。执行记录保存实测总耗时、内存、退出码与串行回退；不得把两个样本的速度保证为全量 R2 加速比。

- R1 Pixal 正式 30/30 推理完成，两个工作进程退出码均为 0，无资源门槛触发或串行重试。工作进程阶段（含各自初始化/加载与导出）97.17 分钟，峰值显存 37.45 GiB，实例工作集 104.32 GiB。该耗时不含父进程前置校验与后置产物审计，且没有同一 R1 工作负载的串行对照，不能据此报告实际加速倍数。

- R1 全部 150 项产物审计及 10 页两视图检查完成；纹理种子 6/6 完成并逐视图复核，条件与导出前几何固定，纹理 RNG 独立重置。review.json 绑定已查看图像的 manifest SHA。至此 221/621 项验收；R2 于 2026-11-06 12:51（Asia/Shanghai）通过性能决策门槛后启动，入口 PID 与日志见本地任务记录。

- 与恢复前源码归档逐文件比较 108 个核心、评价和查看器 Python 文件：104 个字节不变；三处改动分别为新路径、OSS 兼容 NPZ 写入替换、工作簿历史说明，另新增 wt/artifacts.py。源码与改动复核记录为 validation/recovery-20261105/source-review.json / .diff，最终发布核对当前 SHA 仍一致。此记录不等同于跨服务器数值逐位复现。

- R2 首轮已完成 200 份 WT 缓存和 100 个 WT 结果；05:29 UTC 父进程的一次 nvidia-smi 查询超时未被处理，提前停止两个网格工作进程。未观察到 OOM 或模型异常，GPU 后续查询健康。原日志和 200 个未完成网格尝试已归档，未覆盖已完成 WT。v2 容忍暂时查询失败、连续三次失败才停止，CPU 压力保护始终有效；串行重试前要求资源查询恢复。14 项回归通过，决策/脚本已锁定新 SHA，旧 v1 和 R1 验收记录仍按原 SHA 复核。续跑复用缓存，详见专项复核的 v2 章节。

### 2026-11-06 R2 两项显存修复（阶段历史）

- 双进程完成 198/200 个网格，另有 100/100 个 WT 输出；Pokémon 双游戏盒与 3M 防滑胶带两个 hybrid 在并行和原方案串行重试中都 OOM。原 v2 阶段失败日志与退出码归档于 logs/recovery-20261105/attempts/r2-serial-oom/；两个原失败目录在本轮 R2 验证目录 retries/serial-original-v2/，逐文件 SHA 已核验。
- scripts/recovery_memory.py 使用原历史 v6 的独立行 LayerNorm 分块、保持顺序的拓扑分块、仅推理时关闭解码器参数梯度、完成后邻域卷积缓存释放和 CuMesh 调用前清空未使用分配器缓存。原 wt 模块与已安装依赖不修改，数学参数保持原值。
- 算子验证 59 个 CUDA 案例及自动求导回退通过；validate_memory_pretrained.py 使用已封存的单进程两个 P0 hybrid 对照，解码 PLY 与导出前 vertices/faces/coords/attrs 精确相同。13 项文件保护测试覆盖完成/运行中/已评价结果、归档不符、越界和软链接目录。
- 内存策略决定 validation/recovery-20261105/20261013-R2-gso-quant-v1/memory-policy-decision.json 的 SHA-256 为 18072f4f1ff514e3ad01efc1e44f99ca8848ec60919e853a05e89480acf356a2。源码、单元验证及完整样本验证均按摘要封存；不改变 v1/v2 原并行决定。
- 2026-11-06 13:37 UTC 启动专用 tmux recovery-memory-repair：run_task PID 2063012、推理子进程 2063033；日志 r2-memory-repair.log。repair_recovery_memory.py 仅处理两个归档失败的 hybrid，保护其余 298 项。新增策略诚实进入 provenance，重新生成两份 WT 缓存并逐数组核对。当前状态以同名 status.json 为准。
- 复合执行报告区分原并行/串行失败与最终定点修复；后续恢复入口先验证完整保护证明，再做 R2 300 项评价和审计。正式原失败退出码保留，不将它们改写为成功。后续发布还须 R2 Pixal、全方法审计与图像复核通过。


### 2026-10-20 R2 四方法分析

完成 [R2 分析报告](docs/20261020_hybrid-baseline_20261013-R2-gso-quant-v1.md)：100 个固定 GSO 物体 × WT、TRELLIS.2、hybrid、Pixal3D，共 400 项。正文包含形状、深度与相机坐标汇总、论文 Table 1 对照和主要现象；附录记录全部 100 个样本的四方法数值、定性观察及图像链接。与论文的数据划分、视图、best-of-8 和未公开评价细节不同，不作同协议复现声明。

在 `wt-r2-*` 专用 screen 中完成只读数值复核与派生渲染：保存的评价点及配准矩阵复算 1,600 个形状值，与原值一致（容差 1e-10）；100 个原 GT 纹理重渲染与输入逐像素一致。逐一查看全部样本的配准后纹理和背侧几何，并对六个重点案例补查 decoder PLY / GLB。Pixal3D 的分析 native 视角按上游投影坐标撤销 GLB 导出旋转，避免把背面误作输入正面；未改变正式产物、配准或指标。

证据、统计、人工观察与复现脚本保存在 `/data1/LiuShuqi/output/world_tracing/validation/r2-analysis-20261020/`。完整形状均值顺序为 TRELLIS.2、Pixal3D、WT、hybrid；WT 与 hybrid 的共同有效深度集合为 81 个物体，WT 的 AbsRel 在 78 个上更低。工作簿只读核对既有 R2 记录，不覆盖人工内容；本次未重新推理、调整配准或安装依赖。

### 2026-10-20 P0 结果分析

按用户列出的 10 个样本核对 P0 四方法与 shared-WT，共 50 项。分析见 [P0 报告](docs/20261020_hybrid-baseline_20261013-P0-gso-pilot-v1.md)，派生图像、完整数值、来源 SHA-256 与复查脚本保存到 `/data1/LiuShuqi/output/world_tracing/validation/p0-analysis-20261020/`，不写回实验目录。

在 `wt-p0-analysis-20261020`、`wt-p0-details-20261020` 专用 screen 中运行：保存的评价点和配准矩阵复算四个形状指标，50/50 与原值一致（容差1e-10）；原始带纹理 GT 重渲染，10/10 与输入逐像素一致。补充 Hat/MEAT 的逐层点云与截面、Horse/Pixal3D、Bull/Hybrid、Flats/Hybrid、Olive/Pixal3D 的 decoded/GLB 去纹理对照。报告保留深度失败/不适用状态，未新增纹理/OCR 分数，未重新推理或配准。

该环境没有 matplotlib，截面诊断使用现有 NumPy/Pillow 输出等比例点图，未安装依赖。最终脚本与启动命令在上述证据目录的 `reproduction/`；一次性脚本归档后从代码仓库移除。

### 2026-10-20 Office Viewer 4.2.2 空白工作簿修复

`experiments.xlsx` 在 VS Code 中显示空白 `Sheet1`，但 ZIP 完整，openpyxl 可读取三个实际工作表。在专用 `wt-office-fix` screen 中提取已安装 Office Viewer 4.2.2 的原 ExcelJS 解析代码，复现 `Cannot read properties of undefined (reading 'comments')`。插件的 `WI()` 捕获解析错误并返回空白工作簿，因此 UI 没有显示真实异常。

根因是 ExcelJS 只识别 `xl/commentsN.xml`、`xl/drawings/vmlDrawingN.vml` 及对应相对引用，无法识别 openpyxl 的 `xl/comments/commentN.xml`、`xl/drawings/commentsDrawingN.vml`。新增 `evaluation/xlsx_compat.py`，仅重命名这两类 ZIP 部件并调整关系与 content types 引用；`evaluation/research_workbook.py` 保存临时 XLSX 后执行规范化，再沿用原读回核验和原子替换流程。未修改插件、VS Code 配置或环境。

原文件已在锁内备份至 `/data1/LiuShuqi/output/world_tracing/validation/office-viewer-20261020/experiments.before.xlsx`，完成并发版本检查后替换。核验报告同目录 `repair.json`，原错误日志 `parser.log`，修复后的插件解析日志 `office-viewer-parser.log`，回归日志 `tests.log`。三个工作表为实验总览（25×32）、P0_逐样本（55×32）、R2_逐样本（405×32）；12,479 个非空单元格、4,857 个数值、8,845 条批注、1,060 个链接、435 个合并区均保留，人工注释身份映射不变。除四个引用 XML 外，其余 16 个 ZIP 部件内容逐字节一致。

最小回归：`/home/LiuShuqi/.conda/envs/world_tracing/bin/python -m pytest tests/test_xlsx_compat.py -q`，2 项通过，覆盖批注/数值/链接/格式保留、幂等性与导出接入。已用插件原解析器成功加载修复后的文件；无法代替用户确认本地 VS Code Webview 的实际显示。关闭旧空白标签页（不保存），重新打开；若仍复用旧页面，执行 `Developer: Reload Window` 后重开。

### 2026-10-20 Pixal3D 批量完成复核

用户要求更新进度。读取协调器日志与退出码、三份产物验收报告、全部逐样本状态及工作簿，在专用 `wt-pixal3d-progress-20261020` screen 执行状态/指标汇总与旧索引摘要检查。复核退出码为 0，日志为输出目录 `logs/pixal3d-setup/progress-20261020.log`，报告为 `validation/pixal3d-progress-20261020.json`。本次没有重跑模型、配准、评价或网格重载验收；产物完整性依据原队列的验收报告。

| 阶段 | Pixal3D 推理 | 形状评价 | 产物验收时间（Asia/Shanghai） |
| --- | --- | --- | --- |
| P0 | 10/10 | 10/10 | 2026-10-19 17:15 |
| R1 | 30/30 | 无 GT，不适用 | 2026-10-19 17:45 |
| R2 | 100/100 | 100/100 | 2026-10-19 22:17 |

`pilot.exit=0`，`formal.exit=0`；正式队列于 2026-10-19 22:18:09 完成工作簿导出并正常退出。三份验收报告均 `passed`、errors 为空；今天复查 P0/R1/R2 原有 131/271/1001 条输入和结果索引摘要仍一致。140 个新增 run 均使用配置摘要 `3726c776a862c013344bb5605797e16c363ac677fab5152a7d14e329686fa4fc`，没有失败/待处理任务。

R2 四方法共同成功样本数为 100，沿用 `gso-shape-sim3-v1`、seed 42；前三方法为 `defaults-v1`，Pixal3D 为 `resolution1024-v1`。以下为逐物体指标的均值，CD 使用归一化 GT 对角线单位：

| 方法 | CD-L1 ↓ | CD-L2（平方）↓ | F@0.01 ↑ | F@0.05 ↑ |
| --- | --- | --- | --- | --- |
| TRELLIS.2 | 0.009319 | 0.000205870 | 0.707579 | 0.985641 |
| Pixal3D | 0.011763 | 0.000361585 | 0.642681 | 0.971770 |
| WT | 0.012963 | 0.000397708 | 0.592672 | 0.964008 |
| WT + TRELLIS.2 | 0.017255 | 0.000759948 | 0.453610 | 0.919674 |

结果仅代表当前冻结样本、单 seed 和项目配准协议，不作论文数值复现声明。Pixal3D 原视图尺度映射尚未验证，native-camera 与 SSI-depth 仍为 N/A，未用 GT 相机补齐。

根目录 `experiments.xlsx` 于 10 月 19 日 22:18 更新；`FourMethodShape` 共 32 条记录，覆盖 P0/R2 × 四方法 × 四个形状指标。本任务的推理 screen 均已自然退出；没有中断其他任务。复查时 `/data1` 剩余约 63 GiB，没有存储阻塞。

### 2026-10-19 Pixal3D 第二阶段（历史执行记录，现已完成）

用户明确继续执行。新增 `wt/baselines/pixal3d.py`、`pixal3d_batch.py` 和 `examples/infer_pixal3d_batch.py`；读取已有实验的 `input.json`，只追加 `pixal3d/resolution1024-v1/seed-0042`。整批预检先校验原图、身份和配置/源码摘要，成功产物按哈希跳过，首次模型错误停止并保留失败日志；多 GPU 分片不重叠，由主进程持有同一实验写锁。模型权重和推理包均来自独立环境及已固定来源。

模型锁：Pixal3D `b0cb2e1b794cab9aa0ac38a95d794a4d9337437f`、MoGe-2 `39c4d5e957afe587e04eec59dc2bcc3be5ecd968`、DINOv3 `3c276edd87d6f6e569ff0c4400e086807d0f3881`；NAF 官方 release checkpoint SHA-256 `c096c1ab2217a5c3ac136365f721685e2201379cb69d509cfb0261183847c98f`。完整逐文件摘要在 `compare_methods/pixal3d/weights.lock.json`。镜像最初 DNS 失败/HTTP 429，重试后恢复；没有使用代理。下载仅选单视图模型，按 SHA-256 验证后复用旧 decoder/DINO 文件，不依据文件名推断等价。

原环境中 `tests/test_pixal3d_batch.py tests/test_batch.py tests/test_experiment_records.py tests/test_gso_evaluation.py tests/test_experiment_identifier.py` 共 38 项通过；随后 GPU 分片补充验证共 7 项通过。日志在 `logs/pixal3d-setup/integration-tests.log`、`shard-tests.log`，对应 exit 均为 0。独立环境入口帮助与编译检查通过。旧 R1/P0/R2 输入/索引分别 271/131/1001 条摘要写入 `validation/pixal3d-existing-results-before.json`；源码初始快照为 `validation/pixal3d-source-20261019`。

第二阶段 screen：`wt-pixal3d-download` 下载权重，`wt-pixal3d-single` 等待下载成功后在 GPU 0 执行 R1 的 `obj014_leather_briefcase`。命令等价于在新环境 source `compare_methods/pixal3d/env.sh` 后运行 `python examples/infer_pixal3d_batch.py --experiment /data1/LiuShuqi/output/world_tracing/experiments/20261013-R1-object-qual-v1 --sample-ids obj014_leather_briefcase`。`download.log`、`single.log` 和退出码在同一日志目录，逐样本详细日志保存在结果目录 `inference.log`。此条记录时预训练单样本尚未开始，后续结果以下方更新为准。

查看器识别 `pixal3d_yup`；其 decoder 到官方 GLB 的轴变换为 `diag(-1,1,-1)`（右手旋转）。评价仅追加 `--methods pixal3d`，不重算旧三方法。形状指标沿用原配准/采样/归一化协议；FoV 来自 MoGe，距离来自归一化立方体，不用 GT FoV/相机补齐缺失坐标。当前 native-camera 与 SSI-depth 标 N/A。Excel 新增 `FourMethodShape`，显式配对三个 `defaults-v1` 与一个 `resolution1024-v1`，原三方法共同成功样本口径不变。

第二阶段运行更新（2026-10-19 16:48）：全部权重已校验，`download.exit=0`，新增文件约 22 GiB。NAF release 直连一度停滞，官方 assets API 下载得到同一 SHA-256，随后原通道重试也成功；没有代理、没有替换权重。`single.exit=0`，briefcase 生成成功：3064343 个 decoder 顶点、6331244 个三角面，GLB 约 38 MiB。`validation/pixal3d-single.json` 验收通过，包含原生 Stage 1 日志、产物摘要/重载、旧 R1 271 条记录未变。

单样本加载耗时 185.622 s；预处理和 MoGe 为 2.693 s，生成含首次 FlexGEMM 调优为 178.658 s，导出为 336.540 s，后两阶段加预处理共 517.891 s。PyTorch allocator 峰值 allocated/reserved 为 15267276288/15950938112 bytes；nvidia-smi 曾观测整卡约 29 GiB（含扩展分配及其他常驻进程），两者统计范围不同。该冷启动样本不可作为批量平均速度或最终质量结论。

P0 已启动，GPU 0/1 各 3 个、GPU 2/3 各 2 个样本，四个 worker 配置摘要均为 `3726c776a862c013344bb5605797e16c363ac677fab5152a7d14e329686fa4fc`。日志在 P0 根目录 `pixal3d-gpu*.log` 及逐样本 `inference.log`；协调器日志/退出码为 `logs/pixal3d-setup/pilot.log` / `pilot.exit`。P0 完成后用原环境 `evaluate_gso.py --methods pixal3d --workers 2` 评价，再运行 `audit_results.py`，只有全部通过才允许下一阶段。

`wt-pixal3d-formal` 等待 P0 退出码为 0，之后按 R1→R2 顺序执行（GPU 0–5，保留 6/7），各自验收；R2 仅评价新增 Pixal3D，最后更新根目录 `experiments.xlsx`，先备份旧工作簿至 `validation/pixal3d-experiments-before.xlsx`。启动前分别检查至少 50/40 GiB 剩余空间。任一步失败即停止，日志/退出码为 `formal.log` / `formal.exit`。此条记录时正式队列尚在等待 P0，不能视为 R1/R2 已完成。

查看器的 20 项现有回归也已通过，`viewer-tests.exit=0`，没有启动或中断用户已有 viewer 服务。当前任务保留的活动 screen 为 `wt-pixal3d-pilot` 和 `wt-pixal3d-formal`；用户原 `46232.wt` 未操作。精确启动脚本副本保存在 `logs/pixal3d-setup/pixal-{single,pilot,formal,download}.sh`。

16:51 实际续跑预检通过：`resume-check.exit=0`，同一 briefcase 的 selected/queued/skipped 为 1/0/1，配置摘要不变。P0 四个 GPU worker 均已进入第一样本推理，当前 4 running / 6 planned；尚无新增 P0 完成结果，正式 R1/R2 队列仍等待 P0 验收。

### 权重下载与离线使用

以下命令在项目专用 screen 中执行，先激活 Conda 环境并 `source scripts/env.sh`。凭据通过进程环境 `HF_TOKEN` 提供，仅向官方 Hugging Face 发送；公开镜像和 ModelScope 使用匿名下载。

```bash
## 公开 TRELLIS 权重：先尝试镜像
HF_ENDPOINT=https://hf-mirror.com HF_HUB_DOWNLOAD_TIMEOUT=60 \
  python scripts/fetch_weights.py --public --models trellis2 structure_decoder
## 若镜像只返回 308 跳转，改用官方文件端点
HF_ENDPOINT=https://hf-mirror.com HF_HUB_DOWNLOAD_TIMEOUT=60 \
  python scripts/fetch_weights.py --public --models trellis2 structure_decoder \
  --download-endpoint https://huggingface.co

## 已获授权的 WT object；固定 revision，断流后可重新运行续传
python scripts/download_object.py
## DINOv3、RMBG-2.0：默认直连 ModelScope，无需 SDK
python scripts/fetch_modelscope_aux.py
## 生成引用本地权重的 TRELLIS.2 配置
python scripts/prepare_trellis2_local.py

HF_HUB_OFFLINE=1 python scripts/verify_weights.py --models object trellis2 structure_decoder
CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 python scripts/validate_pretrained_stage2.py
CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python scripts/validate_aux_models.py
```

`fetch_weights.py --inspect --public --models ...` 仅检查远端元数据。HF 与 ModelScope 下载清单分别位于 `weights/download-manifest.json`、`weights/modelscope/download-manifest.json`，保存文件 revision、大小和哈希。需要刷新 object 清单时，用官方 `HF_ENDPOINT=https://huggingface.co` 执行 `python scripts/fetch_weights.py --models object`。

单连接反复断流时，先停止同一文件的旧下载，再使用 `python scripts/download_weight_aria2.py --repo haoz19/object-model-6layer --filename model.pt --revision e9da924a0e00bb46569cc5e351bddb9d020b927f` 续传。该工具使用输出目录 `tmp/aria2/`，校验 SHA-256 成功后写回 Hub 缓存。直连失败再按项目网络规则使用当前任务代理；ModelScope 工具支持 `--proxy http://127.0.0.1:8888`，不修改全局设置。

独立加载完整上游 pipeline 时，将 `$WT_WEIGHTS_ROOT/local-pipelines/TRELLIS.2` 传给 `Trellis2ImageTo3DPipeline.from_pretrained(...)`；纹理 pipeline 对应同目录的 `texturing_pipeline.json`。辅助模型也可分别将 `weights/modelscope/facebook/dinov3-vitl16-pretrain-lvd1689m` 和 `weights/modelscope/briaai/RMBG-2.0` 的绝对路径传给 `DinoV3FeatureExtractor(model_name=...)`、`BiRefNet(model_name=...)`。移动权重目录后重新生成本地配置；完整 pipeline 的验收状态见 PROGRESS。

### 2026-10-12：项目初始化

- 仓库：<https://github.com/Sukkkkkkey/world-tracing_forked>。
- 本地路径：`/data1/LiuShuqi/code/world_tracing`。
- 已创建独立基础环境：`/home/LiuShuqi/.conda/envs/world_tracing`，Python 3.11.17，含 pip。
- 上游环境要求见 `pyproject.toml` 与 README；运行依赖、GPU/CUDA 兼容性及推理尚未验证。
- 未单独下载模型权重或实验数据，未运行实验；上游仓库自带的示例与资源保持原样。
- 本地补充 README、RUNBOOK、PROGRESS，无提交或推送。

### 后续实验记录格式

每次实验记录日期、代码提交、环境及依赖版本、GPU/CUDA、模型和输入路径、完整命令、随机种子、输出及日志路径、结果与异常。原始数据目录禁止写入。

### 2026-10-12：环境、存储路径与独立模块调试

- 沿用专用 Conda 环境，Python 3.11.17；PyTorch 2.6.0+cu124 / torchvision 0.21.0+cu124，CUDA Toolkit 12.4，驱动 580.178.04。
- 沙箱内 `nvidia-smi` 不能访问驱动，沙箱外确认 8 张 RTX 4090（每卡报告 49140 MiB）；所有代码与构建均在本任务专用 screen 中执行。
- 数据根目录改为已有 `/data1/LiuShuqi/data/world_tracing`，输出使用已有 `/data1/LiuShuqi/output/world_tracing`。`raw/`、`processed/` 原样保留，未写入数据；权重、缓存、临时文件、日志都放在输出根目录下。
- 外部代码来源与精确提交见 `dependencies.lock`。TRELLIS.2 的 Eigen 固定 `21e4582d1739107337a03460c81412981130373e`；CuMesh/cubvh 的 Eigen 固定 `e63d9f6ccb7f6f29f31241b87c542f3f0ab3112b`。
- GitLab 直连及临时 `http://127.0.0.1:8888` 代理均 TLS 失败，改用 `eigen-mirror/eigen` GitHub 镜像并核对原提交；没有修改全局 Git / Shell 配置。
- PyTorch 由官方 cu124 index 安装；普通 PyPI 包下载速度约 160 KB/s，切换清华镜像后约 20 MB/s。原安装在下载阶段停止，随后重试；日志保留两次尝试。
- FlashAttention 使用 2.7.3；FlexGEMM 安装脚本补丁仅调整缓存路径，补丁保存在 `scripts/patches/flexgemm-cache.patch`。
- utils3d 的 plyfile 依赖升级了 NumPy，新增 `constraints.txt` 固定兼容版本，最终验收使用统一环境。
- WT 首轮验证（GPU 1、种子 42、无权重下载）通过：Euler 数值积分、已知内参恢复、canonical 往返、体素化、真实随机初始化 MoGe + 缩小 DiT 前向，输出 `[1,2,28,28,3]`；路径测试 3 项通过。
- object-model：镜像匿名下载返回 401；官方站点使用用户提供的 token，whoami 确认账号 `Sukeyyy`、read token，但 `main` 与 revision `e9da924a0e00bb46569cc5e351bddb9d020b927f` 都返回 403 GatedRepoError。没有下载权重或运行预训练物体推理；token 只在进程环境中使用，没有保存到文件。

日志位于 `/data1/LiuShuqi/output/world_tracing/logs/`：`setup-base.log`（初次慢速下载）、`setup-base-mirror.log`、`setup-native.log`、`smoke-wt.log`、`paths-tests.log`、`object-validation.log`、`hf-access.log`、`final-validation.log`。最终验收结果在下方补记。

WT 扩展验证已通过：同一脚本运行 r75b 风格物体、r69l 风格场景归一化及 r76 风格两帧时间注意力路径，均使用随机权重、28×28 输入、2 个几何层、缩小 DiT。物体/场景输出 `[1,2,28,28,3]`，动态输出 `[1,2,2,28,28,3]`，数值全部有限。合成 Rerun 文件为 `validation/synthetic_wt.rrd`（约 66 KiB），这是逻辑验证产物，不是预训练模型生成结果。

依赖调试补记：

- O-Voxel 的 pyproject 将 CuMesh/FlexGEMM 声明为直接 Git URL，常规 pip 安装会重新克隆并再次触发 GitLab 子模块失败。改为先按 `dependencies.lock` 安装两项，再以 `--no-deps --no-build-isolation` 安装 O-Voxel；其他声明依赖均已配置，最后通过 `pip check` 核验。
- 补充 nvdiffrec `renderutils` 分支，服务 TRELLIS.2 官方示例的 PBR 环境光路径。
- PyArrow 26 的运行时实际要求 NumPy ≥2，元数据检查未提前报出，导致固定 NumPy 1.26 后 Rerun 导入失败。固定 `pyarrow==19.0.1` 后，WT 三模式和 Rerun 再次通过。约束已写入 `constraints.txt`。
- CUDA 编译设置为 `CUDA_HOME=/usr/local/cuda-12.4`、`TORCH_CUDA_ARCH_LIST=8.9`、`MAX_JOBS=4`；缓存目录均为本项目输出目录。首次 FlexGEMM 调用需要生成 Triton 编译/调优缓存。

#### 最终验收：2026-10-12 17:52（Asia/Shanghai）

专用 screen 中执行 `bash scripts/final_validate.sh`，退出码 **0**：

- `python -m pip check`：No broken requirements found。
- `python -m pytest tests/test_paths.py -q`：3 passed。
- `CUDA_VISIBLE_DEVICES=1 HF_HUB_OFFLINE=1 python scripts/smoke_wt.py`：WT 物体/场景/动态随机权重前向、几何数值与 Rerun 导出通过。
- `CUDA_VISIBLE_DEVICES=1 HF_HUB_OFFLINE=1 python scripts/smoke_trellis2.py`：FlashAttention vs SDPA、Morton/Hilbert 往返、FlexGEMM vs 稠密卷积、独立 shape/texture SLat Euler 采样（各 64×8）、CuMesh、nvdiffrast、nvdiffrec 与 pipeline 导入通过。测试遵循上游 FP32 输入/输出投影、内部低精度块的混合精度约定。
- `infer_rgba.py`、`infer_scene.py`、`infer_video.py`、`infer_textured_mesh.py`、`check_reproduction.py` 的 `--help` 入口全部通过；这不代表对未下载权重执行了推理。
- 完整 Python 包清单已导出到 `requirements.lock.txt`；源码版本见 `dependencies.lock`，核心约束见 `constraints.txt`，基础 Conda 声明见 `environment.yml`。
- `git diff --check` 与各 Shell 脚本语法检查通过。

验收文件：`/data1/LiuShuqi/output/world_tracing/validation/wt-smoke.json`、`trellis2-smoke.json`、`synthetic_wt.rrd`。本次没有生成真实模型 GLB，没有实现 WT → TRELLIS.2 新衔接代码。原始数据和缺失权重清单见 PROGRESS。所有下载鉴权仅用于官方 Hugging Face；仓库中没有保存 token。没有 Git 提交或推送。

### 2026-10-12：更新 token、下载权重与预训练验证

用户更新 token 后，官方 object 文件访问成功，之前的 403 问题解除。凭据只保存在短期进程环境，没有写入仓库、缓存登录文件或日志；镜像匿名访问，鉴权只发往官方 Hugging Face。

网络与下载过程：

- 优先检查 `hf-mirror.com`。TRELLIS.2 文件的 `main` 和固定 revision 都返回 308 跳转官方，Hub 0.36.2 无法从该响应取得完整下载元数据，报 `LocalEntryNotFoundError`。随后改用官方文件端点。
- TRELLIS.2-4B 和 TRELLIS-image-large 的结构解码器无需授权，均匿名下载。官方 Xet 下载成功；配置文件、模型版本和文件哈希记录于 `weights/download-manifest.json`。
- 直连 CDN 超时；当前任务进程沿用本机 `127.0.0.1:8888` 代理，未修改全局网络配置。
- object 单连接传输多次 `ChunkedEncodingError`，保留断点后切换本机 aria2。修正 `--input-file` 模式必须使用每条 URL 的 `out=` 选项的问题，最终对原 5.2 GB 断点续传剩余部分，71.3 秒内完成传输与哈希核验。失败尝试产生的重复临时文件在完成后清理。
- 固定版本和大小：object `e9da924a0e00bb46569cc5e351bddb9d020b927f`，6.21 GB；TRELLIS.2 `af44b45f2e35a493886929c6d786e563ec68364d`，16.24 GB；结构解码器 `25e0d31ffbebe4b5a97464dd851910efc3002d96`，0.148 GB。权重位于 `/data1/LiuShuqi/output/world_tracing/weights/huggingface/hub/`。

在激活项目 Conda 环境并 `source scripts/env.sh` 的专用 screen 中执行验收：

```bash
HF_HUB_OFFLINE=1 python scripts/verify_weights.py --models object trellis2 structure_decoder
CUDA_VISIBLE_DEVICES=1 HF_HUB_OFFLINE=1 python scripts/validate_pretrained_stage2.py

object_ckpt="$HF_HOME/hub/models--haoz19--object-model-6layer/snapshots/e9da924a0e00bb46569cc5e351bddb9d020b927f/model.pt"
CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 python examples/infer_rgba.py \
  --image examples/test_images/object/obj014_leather_briefcase.png \
  --ckpt "$object_ckpt" --config r75b --seed 42 \
  --out "$WT_OUTPUT_ROOT/validation/object_seed42.rrd"
```

结果：

- `weights-integrity.json`：26 个文件大小全部正确，11 个大权重 SHA-256 均与官方 LFS 元数据一致。
- `trellis2-pretrained-stage2.json`：512/1024 版本的 shape、texture 四个真实 flow 模型均 `strict=True` 加载成功；随机图像条件、64 个稀疏点、各 2 步 Euler 采样，输出 `[64,32]` 且全部有限。串行加载模型时峰值 GPU 张量内存约 2.66 GB。没有使用 DINOv3、RMBG 或 WT 衔接。
- WT r75b：1705.0M 参数，504×504 输入，seed 42，完整 20 步推理成功，未打印缺失或不匹配权重键；求得水平视角 45.5°，生成 `validation/object_seed42.rrd`。
- 新增下载与校验脚本语法检查通过；本轮没有更改 Conda 依赖版本。

主要日志：`logs/public-weights-finalize.log`、`object-aria2-final.log`、`weights-integrity.log`、`trellis2-pretrained-stage2.log`、`object-pretrained-validation.log`。失败与断点续传日志保留用于排障；均不含 HF token。

仍缺失：原始/处理数据、WT 场景和动态权重、DAVIS 参考数据。DINOv3 与 RMBG-2.0 在官方站点匿名请求返回 401，使用新 token 返回 403，辅助权重未下载；完整图像 pipeline 和真实纹理 GLB 尚未验收。未新增 WT → TRELLIS.2 衔接实现，未提交或推送。

### 2026-10-12：ModelScope 辅助权重下载与离线验证

用户指定尝试 ModelScope 后，匿名访问同名 `facebook/dinov3-vitl16-pretrain-lvd1689m`、`briaai/RMBG-2.0` 成功。服务器直连两次 ConnectTimeout，告知用户后仅在本任务中使用 `http://127.0.0.1:8888` 代理。未向 ModelScope 发送 HF token，未安装额外 SDK 或更改 Conda 依赖。

- 新增 `scripts/fetch_modelscope_aux.py`：查询文件元数据、按文件固定 revision 下载、断点续传并核对 SHA-256。仅获取推理需要的 safetensors、配置、模型 Python 代码、README 和提供的许可证，共 11 个文件、约 2.10 GB。
- DINOv3 权重 SHA-256：`dcb2e45127cccbf1601e5f42fef165eea275c8e5213197e8dcf3f48822718179`；RMBG 权重 SHA-256：`566ed80c3d95f87ada6864d4cbe2290a1c5eb1c7bb0b123e984f60f76b02c3a7`。两者均与此前 HF 官方元数据一致，其余文件亦通过 ModelScope 的 SHA-256 校验。
- 本地目录分别为 `/data1/LiuShuqi/output/world_tracing/weights/modelscope/facebook/dinov3-vitl16-pretrain-lvd1689m` 和 `.../briaai/RMBG-2.0`。文件 revision、大小、哈希和验证状态记录于同一 `modelscope/` 根目录的 `download-manifest.json`；原 HF 清单保留历史访问失败记录。
- 检查 RMBG 自定义模型代码和配置：`bb_pretrained=false`，不会额外下载骨干权重。通过 TRELLIS.2 原有 BiRefNet 包装器从本地目录加载；模型代码保存在权重目录，未修改。
- 新增 `scripts/prepare_trellis2_local.py`，在 `weights/local-pipelines/TRELLIS.2/` 生成 `pipeline.json`、`texturing_pipeline.json`，所有权重和辅助模型指向本地绝对路径；检查每个被引用的 checkpoint/config 文件存在。原始下载配置不变，没有 WT 衔接代码。

复现命令（先激活环境并 `source scripts/env.sh`，在专用 screen 中执行）：

```bash
python scripts/fetch_modelscope_aux.py --proxy http://127.0.0.1:8888
python scripts/prepare_trellis2_local.py
CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/validate_aux_models.py
```

下载和验证退出码均为 **0**。使用同一张仓库 briefcase 图像、seed 42，DINOv3 在 512×512 输入上输出 `[1,1029,1024]` 特征，数值有限，标准差约 1.0；RMBG 输出 `[1,1,1024,1024]` 有限 logits，导出 1376×768 RGBA，alpha 范围 0–255。输出：`validation/modelscope-aux-smoke.json`、`validation/rmbg-object.png`。模型内 timm 旧导入路径给出两条 FutureWarning，不影响本次推理。

日志：`logs/modelscope-inspect.log`、`modelscope-inspect-proxy.log`、`modelscope-download.log`、`modelscope-validation.log`。新增三个脚本语法检查通过；没有重跑无关环境测试。本轮不再缺少这两个辅助权重，完整纹理 GLB 生成与 WT 衔接仍留待后续。

### 2026-10-12：按四项任务复核进度

专用 `wt-progress-audit` screen 中运行当前环境的 `python -m pip check` 和只读状态检查，退出码 0；会话执行完毕自动退出。当前 Python 3.11.17、PyTorch 2.6.0+cu124、CUDA 可用，未发现依赖冲突。6 个源码仓库 HEAD 与 `dependencies.lock` 一致，递归子模块均已按对应提交检出。

检查已校验清单中的 37 个模型相关文件，均存在且大小匹配；两份本地 pipeline 配置的权重、配置和辅助模型引用全部存在。复核此前验证退出码均为 0，未重复执行模型推理或大文件哈希计算。原始和处理数据目录仍为空，WT 场景/动态权重与 DAVIS 参考数据仍缺失；TRELLIS.2 完整纹理网格生成、论文指标及计划后续的 WT 衔接尚未验收。README 已覆盖环境、路径、下载和验证命令，与当前状态一致。

记录：`logs/progress-audit.log`、`logs/progress-audit.exit`、`validation/progress-audit.json`。Git 改动保持未提交、未推送。

### 2026-10-13：仓库清理与文档整理

- README 恢复项目说明书定位，补回 package layout、模型配置、推理用法、输入输出约定、引用与许可；下载操作集中到本文件，实验状态和缺失项保留在 PROGRESS。同步修正示例说明中的失效链接、视频参数和输出目录。
- 清理 54 个自动生成目录、337 个文件，共 37,948,397 字节（约 36.2 MiB）：Python / pytest 缓存、6 项依赖的 build 和 egg-info。删除前逐项确认未被对应 Git 仓库跟踪，并确认扩展实际安装在 Conda 的 site-packages；保留 WT editable 安装所需的根目录 `wt.egg-info`。没有发现额外备份文件。
- 清理后 WT 与 6 项依赖导入正常，`pip check` 无冲突；文档本地链接、Shell 代码块及示例输入路径检查通过。原始数据、权重、示例输入、有效实验结果与既有源码改动均保留，未重跑模型推理。

清理明细与环境检查记录：输出目录下 `logs/wt-repo-cleanup.json`、`logs/wt-repo-cleanup.log`、`logs/wt-repo-cleanup.exit`。检查在本任务专用 screen 中执行，会话完成后自动退出；未提交或推送。

### 2026-10-13：TRELLIS hybrid 衔接调试

在锁定的 TRELLIS.2 提交上对照 `Trellis2ImageTo3DPipeline.run` 调试现有桥接，未改动第三方源码或依赖版本。

- 修正示例默认网格：512、1024_cascade、1536_cascade 都从 32³ 坐标开始；只有直接 1024 使用 64³。显式传入冲突的 `--ss-res` 会在加载模型前报错。
- 补充坐标维度、整型、边界、唯一性和单批次检查；插值前排除非有限点，空前景/空几何明确报错。RGBA 经 TRELLIS 裁剪和黑底合成；跳过裁剪时仍合成 alpha，避免隐藏 RGB 污染 DINO 条件。
- 默认使用准备好的本地配置，按模式加载 shape/texture 模型，跳过被替代的 Stage 1 权重。WT 推理后移到 CPU，为解码与烘焙释放显存；支持 shape/texture 步数和 cascade token 参数。
- 输出同名 JSON 记录坐标变换与采样参数。上游 O-Voxel 导出会将 Z-up 转成 glTF Y-up，恢复相机坐标须先应用 `glb_to_canonical`，再执行 `canon_inverse`。首轮运行在元数据注释修正前已启动，输出检查时已同步其 JSON；GLB 几何未改写。

在专用 screen、离线环境中执行：

```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
python -m pytest tests/test_hybrid.py tests/test_paths.py -q -p no:cacheprovider
CUDA_VISIBLE_DEVICES=0 python scripts/smoke_hybrid.py

object_ckpt="$(python scripts/download_object.py)"
CUDA_VISIBLE_DEVICES=1 python examples/infer_textured_mesh.py \
  --image examples/test_images/object/obj014_leather_briefcase.png \
  --ckpt "$object_ckpt" --seed 42 --pipeline-type 512 \
  --texture-size 512 --decimation-target 100000 \
  --out "$WT_OUTPUT_ROOT/validation/hybrid-512/briefcase.glb"
## 默认 cascade：同样参数，改为 --pipeline-type 1024_cascade，
## 输出为 validation/hybrid-cascade/briefcase.glb（本次使用 GPU 0）。
```

25 项测试通过，覆盖四种模式路由、cascade 实际返回分辨率、采样参数、无效输入、本地模型选择与坐标往返。随机 GPU 验证将三层 12×12 点图转换为体素，每种模式保留 64 个点，经缩小的随机权重真实 shape/texture flow 各采样 2 步，512 和直接 1024 均输出有限的 `[64,8]` 特征。此脚本使用随机图像条件，mesh decoder 仅作断言边界；不能作为真实解码或生成质量证明。

真实输入使用仓库自带 briefcase 图像与本地预训练权重，WT 20 步输出 `[6,504,504,3]`，有效比例 18.32%，生成 4,638 个体素，无随机截断。512 链路的 shape/texture 各 12 步、解码和 GLB 导出成功；重新加载后为 81,358 个顶点、96,434 个面，512×512 PBR 纹理，文件 3,862,328 字节；顶点/UV、面索引及坐标往返检查通过。

默认 1024_cascade 同样通过：低/高分辨率 shape 各 12 步、texture 12 步，解码和 GLB 导出退出码 0。重载文件为 88,183 个顶点、95,980 个面，512×512 PBR 纹理，文件 4,086,248 字节；几何/UV 数值、面索引和坐标往返均通过。复核日志 `logs/hybrid-cascade-check.log`，报告 `validation/hybrid-cascade/check.json`。直接 1024 的完整预训练导出、1536_cascade 的真实模型运行、多样本质量及论文指标尚未验证；本次未新增数据或权重缺失项。

记录：`logs/hybrid-final-check.log`、`logs/hybrid-smoke.log`、`logs/hybrid-real-512.log`、`logs/hybrid-real-cascade.log` 及各自 `.exit`；随机报告 `validation/hybrid-smoke.json`，GLB 同目录的 `check.json` 保存导出文件复核结果。README 仅更新用法。本次没有下载或修改原始数据，没有提交或推送。

### 2026-10-13：极简网页查看器

新增根目录 `viewer.py`，复用已安装的 Rerun 0.22.1 与 trimesh，不新增依赖、不运行模型。输入图像和预测点云为必选，`--mesh`、`--gt`、`--trellis` 为可选独立面板；RRD 显示指定点实体的最新快照，支持 NumPy/PLY 点云及常见 mesh 文件。GLB 的 WebP 纹理在内存中转为 PNG，原文件保持不变。

在专用 screen 中执行 `python -m pytest tests/test_viewer.py -q -p no:cacheprovider`，6 项通过，覆盖 NPZ 层掩码与颜色、静态/时序 RRD、无效坐标、确定性采样、五面板数据传递及临时录制清理。实际网页测试使用自带 briefcase 输入、`object_seed42.rrd`、512 mesh 与 cascade GLB；真值面板使用 `synthetic_wt.rrd` 作为测试占位，没有真实 GT 或独立 TRELLIS baseline 数据。

原 Python `serve_web` 的全网卡监听被自动审批拒绝，改用原生 CLI `--bind 127.0.0.1`；空服务和实际五面板服务均确认 HTTP/WebSocket 只在本机监听。HTTP 返回 200、WebSocket 握手 101 且收到二进制录制数据。测试未覆盖浏览器 GPU 画面的人工视觉检查。运行时临时 RRD 放在输出目录 `tmp/viewer-*`，正常退出自动清理；正式用法和双端口 SSH 转发见 README。

最终日志：`logs/viewer-final-check.log`、`logs/viewer-web-final.log`。没有修改权重、输入或现有推理结果，没有提交或推送。

### 2026-10-13：推理结构与坐标约定复查

新增维护文档 `docs/CODE_STRUCTURE.md`，按入口、预处理、模型内部采样、反归一化、原生可视化和 hybrid 生成的顺序串起 class/function，并记录张量形状、相机/canonical/GLB 变换、体素分辨率与尺度边界。README 仅新增文档入口并校正输入输出说明。

- 修复外部 K 在单图/视频裁剪后未减裁剪原点的问题；统一深度反投影与内参拟合的 `+0.5` 像素中心约定。发布 XYZ 模型不走深度反投影分支。
- canonical 变换改用全部有限前景点拟合，避免抽样遗漏极值导致体素化丢点；验证正尺度和中心，支持从 JSON 列表重载，集中维护 GLB 逆轴变换及 `glb_to_camera`。
- 内参拟合过滤非有限点、秩不足和非正焦距。默认相机→canonical 与 canonical→GLB 都是行列式 +1 的旋转，原轴方向无须更改；GLB 逆变换恢复的是 WT 预测尺度，并不恢复未知的场景绝对尺寸。
- 修复权重工具 `--inspect` 覆盖已有下载清单的问题，避免查询新的远端 revision 后破坏本地 descriptor 的来源记录；测试使用模拟元数据，不发起下载。统一验证脚本尊重调用者指定的 GPU。

专用 `wt-coordinate-review`、`wt-coordinate-gpu`、`wt-structure-review` screen 均执行完成后退出。最终 `pytest tests -q -p no:cacheprovider` 为 **47 passed**，其中 42 项属于路径、hybrid、几何与权重工具，另外 5 项来自工作期间新增的 viewer 测试；本轮未修改 `viewer.py` 或其测试。GPU 0 随机点图→体素→真实 CUDA shape/texture flow 验证通过，不运行预训练 mesh decoder。

检查 README/结构文档的 39 个本地链接、Shell 代码块，并实际执行文档中的 GLB 坐标恢复示例。只读重载既有 512 / 1024_cascade GLB，先应用 scene-node 变换，再恢复相机坐标并检查轴转换往返；分别检查 81,358 / 88,183 个顶点。没有重新运行完整预训练生成，也没有改写既有 GLB。

记录：输出目录下 `logs/coordinate-review.log`、`logs/coordinate-hybrid-smoke.log`、`logs/structure-review.log` 及各自 `.exit` 均为 0；报告 `validation/coordinate-review.json`，随机报告更新于 `validation/hybrid-smoke.json`。没有新增数据或权重缺失项，没有修改第三方依赖，没有提交或推送。

### 2026-10-13：网页查看器迁移到 Viser

用户报告 Rerun WebSocket 9877 绑定失败，并选择改用 Viser。服务器检查发现原生 Rerun 进程 PID 699235 同时监听 127.0.0.1:8080/9877，PPID 为 1；另有上一轮测试遗留进程 PID 695768 监听 18080/19877。代码复核确认 `python -m rerun` 包装层又调用原生程序，旧 viewer 只终止包装层，可能留下原生子进程。这也补正上一轮验收的不足：临时文件清理、包装进程退出不能证明原生服务已停止。已清理本任务旧测试进程，保留用户的 8080/9877 服务；无法还原截图瞬间的端口状态。

`viewer.py` 现在直接使用 Viser，不再启动 Rerun 服务或生成临时 RRD。图像在侧栏显示，点云和 mesh 可并排或单项查看，保留 GT/TRELLIS 可选输入、RRD 实体选择、点数限制与文件格式兼容。展示时将 RDF 点云旋转为 Y-up，各结果居中后平移，保留尺度，不进行配准。单端口仅绑定 127.0.0.1，支持 `--port 0`；端口冲突时打印实际使用端口。SIGINT/SIGTERM/SIGHUP 均停止服务。

在专用 screen 中从官方 PyPI 安装 Viser 1.1.1；仅新增 viser、websockets、msgspec、rich、markdown-it-py、mdurl，未升级原有模型依赖。同步 `pyproject.toml`、`constraints.txt`、安装元数据和 `requirements.lock.txt`，`pip check` 通过。

`python -m pytest tests/test_viewer.py -q -p no:cacheprovider`：**9 passed**。覆盖点云掩码/颜色、静态/时序 RRD、非法输入、确定性采样、坐标旋转与 mesh scene-node 变换，以及三种退出信号下的真实 HTTP/WebSocket、五类输入、GUI 结果切换和端口释放。测试使用合成 GT/TRELLIS 输入；没有真实 GT 或独立 TRELLIS baseline 文件。

真实示例在 `wt-viewer-viser` screen 中运行，使用自带 briefcase 图像、`validation/object_seed42.rrd` 和 `validation/hybrid-cascade/briefcase.glb`。8080 被旧服务占用后自动使用 **8081**；HTTP 页面/JS 资源返回 200，同端口 WebSocket 完整收到输入图、200,000 个有限点及 4,791,532 字节 GLB（内存中重编码 PNG 纹理后的大小）。没有覆盖浏览器 GPU 渲染的人工视觉检查。停止该预览可执行 `screen -S wt-viewer-viser -X stuff $'\003'`。

日志：`logs/viewer-viser-install.log`、`viewer-viser-metadata.log`、`viewer-viser-check.log`、`viewer-viser-probe.log` 及相应 `.exit` 均为 0；持续运行的预览日志为 `logs/viewer-viser-web.log`。README 只维护使用说明。没有修改输入、权重或已有推理结果，没有提交或推送。

### 2026-10-13：模型复用批量入口与实验目录查看器

新增 `examples/infer_batch.py`、`wt.batch` 和 `wt.experiment`。按模型阶段运行：WT 只加载一次，缓存全部输入/预处理/步数/seed 的 NPZ 与 RGBA；释放 WT 后，只加载一次 TRELLIS 所需模型并集，原生和 hybrid 共用该实例。默认参数沿用各自单图入口；shared-WT 配置通过相同 WT 参数命中缓存。Stage 1 仅在批次包含原生 TRELLIS 时加载，原有单图 hybrid 行为保留。

输出按 `samples/<sample>/<method>/<config>/seed-0042/` 组织，`run.json` 原子写入状态和产物，配置/输入/来源变化阻止覆盖旧结果；单 writer 文件锁，失败或产物缺失可续跑，已完成任务跳过模型加载。缓存另核对 NPZ/RGBA 内容哈希。当前仅实现推理与产物协议，未实现 GSO 渲染、定量指标或 Excel 汇总。

`viewer.py --experiment` 支持样本/方法/配置/seed 筛选、前后样本、刷新、GT、导出 GLB/decoder mesh。只读取选中几何（最多 12 个 run），切换时移除旧场景；未完成/失败/损坏结果显示状态。批量模式按 frame 元数据转换轴，hybrid 可恢复到自己的 WT 框架，原生 TRELLIS 不套用该逆变换；面板仍居中并排，不作 GT 配准。旧单样本入口与用户已有服务未中断。

专用 screen 中运行 `pytest tests/test_batch.py tests/test_viewer.py tests/test_hybrid.py -q -p no:cacheprovider`：**44 passed**。覆盖两张不同输入、多 seed、多配置的模型初始化次数、默认/受控 WT 缓存隔离、续跑不加载、失败重跑、WT 初始化失败不阻断原生 TRELLIS、合成预测经过真实 WT 预处理/NPZ 导出接口、Stage 1 加载选择、GLB scene-node 与 hybrid 恢复，以及真实 HTTP/WebSocket 的样本切换、清空旧场景和完成后刷新。测试使用合成点图/几何与模拟模型后端，没有运行批量预训练推理；CLI help 和 diff 格式检查通过。

主测试日志为输出目录下 `logs/batch-viewer-review.log`，CLI 为 `logs/batch-viewer-cli.log`；最终针对性检查为 `logs/batch-viewer-final.log`，各配套 `.exit` 为 0。实验方案同步实际文件协议；遵循 `docs/AGENTS.md` 的本地保留规则，将 `/docs/` 加入忽略范围，并沿用现有日期前缀的结构文档文件名。未下载 GSO，未启动两轮正式实验，未提交或推送。

### 2026-10-13：方案复查与首轮基线启动

`docs/20261013_hybrid-baseline.md` 正文精简为实验规模、三方法/单因素配置、形状/相机/深度协议、随机性与复现；公式、采样规则、批量契约及工作簿字段归入附录。复查明确：默认 WT 与 hybrid 预处理不同，另列 shared-WT；形状按 GT 资产空间对角线统一单位，不按旋转后的 AABB 再缩放；decoder mesh 恢复相机框架时不重复撤销 GLB 轴旋转；评价 K 来自渲染相机；深度覆盖不足 95% 或正尺度拟合失败不能进入成功均值。

批量入口每样本重置 Python/NumPy/Torch/CUDA RNG，推理 seed=42、`PYTHONHASHSEED=42`，并记录版本、GPU、精度和确定性开关。相关测试 34 项通过；固定 1030→10/100/920 划分、用途独立种子、工作簿保留/空值/字符串安全与 ZIP 路径检查 3 项通过。项目环境新增 openpyxl 3.1.5 / et-xmlfile 2.0.0，更新锁定文件，`pip check` 通过。

已启动以下持续任务，不能将本节视为最终成绩：

| screen | 工作 | 日志/状态（相对于输出根目录） |
| --- | --- | --- |
| `wt-R1-baseline` | GPU 0，30 张 object ×（三方法默认 + shared-WT）=120 个结果，先完成 60 份独立 WT 缓存，再生成 90 个 mesh | `experiments/20261013-R1-object-qual-v1/batch.log`；结束时 `batch.exit` |
| `wt-trellis-native-preflight` | GPU 1，briefcase 原生 Stage 1→2，1024_cascade、4096 纹理/100 万面默认导出；单独验证，不并入正式结果 | `validation/trellis-native-default-preflight/batch.log`、run.log、`batch.exit` |
| `wt-gso-download` | 下载用户给定 ZIP；直连超时后使用本次任务代理；服务未正确响应分段 Range，当前单连接继续 | `datasets/gso/source/download.log`；成功后 SHA-256 与 `download.complete` |
| `wt-gso-ingest` | 等待完整下载；校验 ZIP 成员 CRC，检查空间，只解压 models_orig 副本，核验 OBJ/纹理后冻结 inventory/split | `datasets/gso/ingest.log`、`ingest.exit`；清单位于 `experiments/datasets/gso-v1/` |
| `wt-baseline-workbook` | 每分钟重建仓库根目录 `experiments.xlsx`，R1 批量结束后退出 | `logs/baseline-workbook.log` |

ZIP 的 HTTP Content-Length 为 24,977,819,586 字节（约 23.3 GiB）；任务启动时 /data1 可用约 249 GiB，解压前另检查 models_orig 成员总大小并保留 20 GiB 空间。原始 `data/world_tracing/raw/` 未写入。完整 GSO 尚未到达，不能宣称已核验 1030 个资产或冻结了实际 split；下载后入库可能因损坏/布局异常停止，日志会记录原因，不擅自换样本。

R1 的 `reproduction/` 保存完整 wt/examples 源码和输入快照、SHA-256、Git HEAD/工作区 diff、依赖锁/pip freeze、GPU 信息、权重下载清单、输入清单、解析前配置和实际启动脚本。正式批次以快照 PYTHONPATH 运行。`plan.md` 为启动时版本，`reviewed-plan.md` 补充了最终坐标/覆盖率说明；各 run 的 `config.json` 为实际参数与运行环境。

工作簿已登记 R1 运行中、P0/R2 待执行，120 个首批任务记录完整；R1 没有 GT，数值指标为 N/A。原文件为 0 字节占位，现已初始化为有效工作簿；更新保留无关实验与自定义 sheet。GSO 渲染/评价尚未实现和验收，正式 100 物体不自动越过 P0；参数扫描尚未启动。当前 runtime 记录总推理/mesh 时间，尚不提供独立后处理计时与精确峰值显存，不将缺失字段当测量值。

手动刷新记录（激活项目环境，在专用 screen 内）：

```bash
python examples/export_experiments.py --experiments "$WT_OUTPUT_ROOT/experiments" --out experiments.xlsx
python viewer.py --experiment "$WT_OUTPUT_ROOT/experiments/20261013-R1-object-qual-v1"
```

续跑 R1 使用其 `reproduction/launch.sh`，保持快照和配置不变；已有任务运行时不要并发启动相同根目录 writer。未提交或推送。

本次交接检查：R1 的 60 份 WT 缓存全部完成，30 个 WT 基线 run 已 complete，90 个 TRELLIS/hybrid/shared-WT mesh 作业进入后续阶段。原生 TRELLIS 独立预检 `batch.exit=0`，mesh 生成与导出总计 410.22 秒（不含模型冷启动），GLB 和 decoder PLY 均重载为非空、有限三角网格；报告 `validation/trellis-native-default-preflight/artifact-check.json`。该预检 screen 已自然退出，不占用后续 GPU。工作簿最终复验通过，并继续随 R1 更新；GSO 仍在下载中。

### 2026-10-13：GSO 完整原件入库与 pilot 准备

原站 24,977,819,586 字节 ZIP 在约 13 GiB 处 TLS 中断，当前通道不支持 Range 续传。保留未完成文件和 CRC 正确的局部成员索引于 `datasets/gso/source/`，从原清单的 944 个 valid 与 86 个 invalid ID 恢复 1030 个资产全集；原作者的 invalid 分类不作为本实验自动排除规则。另一个 Roldbach 镜像仅含渲染数据，未用于原始资产入库。

采用 `suvadityamuk/google-scanned-objects-raw` 固定 revision `6139aa33f6163a9f1c7352dd386760f40691ce0d`，严格按原始 1030 ID 筛选，排除镜像额外 16 项。用户指定目录 `/home/LiuShuqi/Workspace/data/world_tracing/raw/gso/` 内保存 ZIP、未改动的解压内容、逐文件完整性记录与来源；1030/1030 ZIP SHA-256、成员 CRC 和必要文件检查通过，`COMPLETE.json` 已生成，输出目录 `datasets/gso/raw-ready.exit=0`。ZIP 合计约 8.07 GiB。全量原站 ZIP 未完成，因此不声称所有文件均与 MegaPose 包逐字节比较；已抽查 20 个重叠资产 OBJ 字节和 RGB 纹理像素一致，派生入库继续比较全部可用重叠成员。

按用户要求，原件完整前曾暂停派生入库；完成标记生成后才恢复。`verify_gso_raw.require_complete()` 是 GSO 派生导入、渲染、评测入口的前置检查。raw 原件此后只读；`datasets/gso/assets/models_orig/` 是输出目录内的派生副本，只在该副本中增加兼容 MTL 相对引用的 RGB 纹理。清单与 seed=20261013 的 10/100/reserve 划分写入 `experiments/datasets/gso-v1/`。

新增 `evaluation/` 与 GSO 渲染、评测入口，记录 Z-up→世界坐标→RDF 相机变换、AABB 对角线单位、像素中心、裁剪 K、正 Sim(3) 和深度覆盖率。真实 GPU 数学/渲染测试 5 项通过；合成资产经过渲染、三方法评价与结果记录的 4 项检查通过（775 秒）；数据完整门槛与汇总记录 5 项通过。合成指标仅用于验证协议实现，不进入真实实验成绩。修正评测入口：发生逐样本评价异常时返回非零退出码。

| screen | 工作 | 输出根目录下的日志/状态 |
| --- | --- | --- |
| `wt-gso-import` | 完整原件→派生兼容副本→几何/纹理检查→冻结划分 | `datasets/gso/import-mirror.log`、`import-mirror.exit` |
| `wt-gso-pilot-queue` | 入库成功后 GPU 1 渲染 10 个 pilot；批量运行三方法默认与 shared-WT，共 40 项；随后评价 | `experiments/20261013-P0-gso-pilot-v1/queue.log`、`batch.log`、`evaluation.log` 与对应 `.exit` |
| `wt-R1-baseline` | GPU 0 继续首轮 object 定性实验 | `experiments/20261013-R1-object-qual-v1/batch.log` |

P0 的 `reproduction/` 保存 raw 完成标记哈希、配置、实际启动/入库脚本和源码校验；WT 推理源码沿用 R1 冻结版本，seed=42、batch=1。评测的 24 初值配准较耗 CPU，独立记录其日志；正式 100 个物体和参数扫描尚未启动，必须先检查 pilot。工作簿新增 `MetricSummary`，按资产汇总指标均值/标准差、失败率和共同成功集合，缺失指标保持空值。

19:35 检查：`import-mirror.exit=0`，1030 个派生资产全部 valid，排除 0 个；全部 320 个可比较原站资产的 OBJ 字节与 RGB 纹理像素一致。冻结 `10 pilot / 100 eval100 / 920 reserve`，独立验证全集一致、三组互斥及固定种子精确重放，证据 `datasets/gso/split-audit.json`。10 张 pilot RGBA 与 GT 渲染完成，抽看直升机与公牛输入，朝向、纹理与画面边界正常；GPU 1 已进入 P0 推理。`wt-gso-workbook` 每分钟更新工作簿直到 pilot 队列退出；测试日志持久保存到 `datasets/gso/protocol-checks/`。R1 此时已完成 63/120 项，无失败，仍持续运行。

### 2026-10-14：覆盖错误基线、重评与结果汇总

发现批量调度对原生 TRELLIS 也传入了参数匹配的 WT 缓存，导致 40 个原生标签实际执行 hybrid，网格与对应 hybrid 完全相同。修复调度与 backend 方法/parent 一致性检查，并在评价入口拒绝有 WT parent 的原生结果。40 项原生推理按固定 seed=42、原默认参数重跑，直接覆盖错误目录；有效 WT/hybrid 推理未重跑。采用 GPU 分片、每进程模型常驻；长尾组的未开始样本转至空闲 GPU，分配记录保存在 correction 的 worker JSON 中。

P0 旧评价曾完成 23/40，余下 17 项受超大 mesh 单次 CUDA 光栅化错误影响。在原 26,031,912 面失败网格复现后，改用每批最多 100 万面、最近 Z 合并，保留所有三角面与原相机。每个 run 使用独立评价进程，避免 CUDA 状态污染。最终 40/40 评价执行成功；两个原成功样本的 15 项指标最大差约 3.9e-9。9 项批量、5 项数学/渲染、1 项进程隔离回归通过，所有 40 个修正原生结果的 Stage 1 日志与 GLB 容器通过验收。

实际深度质量仍有失败：默认 hybrid 的 MEAT_SET、Schleich_Hereford_Bull，以及 shared-WT 的 MEAT_SET 覆盖率不足 95%。相应深度误差留空，不丢弃样本；另在共同有效的 8 个资产上比较深度。此类质量失败与程序执行失败分开记录。

当前 R1 为 120/120 完成，P0 为 40/40 推理与评价完成。结果分析见 `docs/20261014_hybrid-baseline_results.md`，机器可读汇总为输出目录 `experiments/20261014-baseline-summary.json`；仓库根目录 `experiments.xlsx` 包含 MetricSummary、PaperComparison、PairedDepth。论文参考为 Table 1 的 100 个 held-out objects / best-of-8，本轮为项目自定 GSO pilot 10 / 单 seed / GT 辅助 Sim(3)，不作直接达标或超越判断。正式 R2 与参数扫描尚未运行。

实际修正源码、启动脚本、验证和清理记录位于两实验的 `reproduction/correction-20261014/`；原 `reproduction/source` 保留用于有效 WT/hybrid 产物的来源追溯，原启动脚本不是修正后的全方法续跑入口。用户授权覆盖错误输出，未保留错误网格备份；清理原站中断 ZIP、未采用镜像及临时审计文件，raw GSO、源清单/对照证据、有效结果、GT 和 WT 缓存保持完整。清理明细为 P0 correction 下 `cleanup.json`。未提交或推送。

### 2026-10-15：补齐 R2 正式 100 物体实验

用户确认补齐正式 R2，并更正结果文档。沿用已冻结的 `gso-v1/split.json` 中 `eval100`，与 P0 独立；三方法默认配置、推理 seed=42、每资产单视图。运行前重放 PCG64(20261013) 划分，核对 raw COMPLETE 哈希及 1030 个资产存在性。原始数据只读。

专用 screen `wt-R2-baseline`，启动入口 `scripts/run_r2_20261015.sh`，快照与实际启动记录保存至 R2 `reproduction/`。8 个 GPU 各处理固定分片，每进程先批量 WT、再复用 TRELLIS 模型；同一资产的三方法均写至 R2 `samples/<asset>/`。worker 的 samples 和 cache 只是指向统一产物目录的链接，不复制结果。分片完成推理后，以独立子进程逐项评测；工作簿按实验 ID 刷新。

初次渲染在第 18 个资产 `Pokémon_Omega_Ruby_Alpha_Sapphire_Dual_Pack_Nintendo_3DS` 被 ASCII ID 校验拒绝；没有模型推理开始。修复 `wt.experiment.identifier` 允许 Unicode 字母/数字，仍拒绝斜杠、反斜杠、空白、控制字符和点路径，加入回归检查。保留原 ID、固定视图、抽样清单和已完成的 17 份渲染；修复不改变模型或评价算法。原失败日志保存在 `reproduction/unicode-preflight-error.log`。

最终 300/300 推理与评价执行完成。26 项预检通过，100 个原生结果确认真实 Stage 1 且无 WT parent，200 个 GLB 容器完整；全部输入哈希、固定 split、默认配置、parent 哈希、评价版本及 source_run_hash 校验通过。评价源码与修正 P0 一致。深度质量失败 WT 1/100、hybrid 18/100；共同有效集合 81 个，空值与原因保留，未换样本。

正式数值与逐项失败见 R2 summary.json，验收见 reproduction/validation.json。docs/20261014_hybrid-baseline_results.md 正文覆盖为 R2，P0 保留在附录；experiments.xlsx 的 PaperComparison 与 PairedDepth 增加 experiment_id，明确两批数据。R1/P0 既有产物与原始数据未改动，参数扫描未运行。未提交或推送。

首次队列中两个 hybrid 在 shape decoder LayerNorm 触发 OOM：`Pokémon_Omega_Ruby_Alpha_Sapphire_Dual_Pack_Nintendo_3DS` 请求 12.00 GiB，设备容量 47.37 GiB、空闲 5.28 GiB，PyTorch 已分配 29.10 GiB、另保留未分配 12.50 GiB；`3M_Antislip_Surfacing_Light_Duty_White` 请求 13.91 GiB，空闲 12.19 GiB、已分配 30.35 GiB、保留未分配 4.33 GiB。队列继续其他资产；`wt-R2-retry` 等对应分片的原始推理与评测结束后，用原 GPU、原输入/参数/seed 的独立进程重试，设置 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`。不降低分辨率、换 seed 或换样本；首次错误和重试记录保存在 worker/retry-1/。

仅在上述重试仍 OOM 时，`wt-R2-fallback` 才启用 decoder LayerNorm32 的独立行分块：完整保留特征维的原始归一化函数、精度、参数与 epsilon。36 组随机张量（FP16/BF16/FP32、6 种通道数、连续/非连续布局）及 1,048,576×64 大张量验证逐元素一致，后者额外显存从 640 MiB 降至 288 MiB；开启梯度时回退原函数。验证见 R2 reproduction/layernorm-check.json。实际使用时归档失败产物到 retry-*/，新 provenance 记录 helper/adapter/验证 SHA，重新计算 WT 缓存，逐样本保存实际分块次数；不重新标记旧缓存。Pokémon 的 retry-2 仅覆盖 shape decoder，形状解码成功后在 texture decoder LayerNorm 的 FP32→FP16 转换请求 6 GiB 时 OOM；retry-3 扩展为 shape/texture 两种 decoder，保留 retry-2 的原始代码与日志。报告汇总全部恢复尝试，仅在推理和评测通过来源核验后发布；ExecutionRetries 保留各次错误，最终成功情况以验收为准。

#### 2026-10-18 恢复与最终验收

R2 有 2 项首次运行失败，经原 GPU、原参数、seed=42 的独立进程重试成功。独立进程启用 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`。其中 2 项仍 OOM，随后对 decoder 的 LayerNorm32 按独立行分块；特征维归一化、精度、权重和 epsilon 不变。36 组张量及大张量均验证逐元素一致，测试额外显存从 640 MiB 降至 288 MiB；新运行记录额外源码哈希及实际分块次数，并重新计算 WT 缓存。其中 2 项进一步关闭 decoder 参数梯度，避免 FlexGEMM 在 no_grad 下仍生成反向邻接缓存；6 组实际稀疏卷积验证前向逐元素一致，模型参数值与采样配置不变。其中 2 项在解码完成后释放已用完的卷积邻接缓存，并在 CuMesh 前归还空闲显存；另 6 组测试确认坐标、特征、布局及再次卷积结果不变，实际释放量记录在 memory-policy.json。服务器重启后确认仍缺 2 项：前次分别失败于形状网格拓扑和 GLB 重网格化。最终将邻接查询与三角化按原顺序分块，并提前释放已用完的 shape 卷积缓存；10 组 CUDA 测试确认顶点及面索引逐元素一致，不修改分辨率、重网格化或三角面选择规则。额外 helper、上游源码与验证哈希均写入逐样本配置；两项重算 WT 缓存的坐标、掩码、RGB 和内参与前次逐元素一致。Pokémon 在重网格化后又触发 CuMesh 简化 OOM，最终在原生初始化/简化之前归还 PyTorch 空闲缓存；未改简化算法或目标面数，逐阶段显存记录随 memory-policy.json 保存。 错误、日志、命令与运行策略保存在 reproduction/workers/gpu-*/retry-*/。恢复验收以 reproduction/finalize.exit 和 validation.json 为准；首次 queue/retry 退出码保留，不覆盖失败证据。

### 2026-10-15：实验查看器按选择加载与准备进度

用户反馈 `--experiment` 加载慢，要求解释参数，并明确保留比较数量与默认 GT。旧实现虽已筛选当前样本，但启动时自动加载首样本；同步依次解析多个 mesh、完整重打包纹理后才显示，缺少进度且回调可能排队。真实 MEAT_SET hybrid 的导出 GLB 约 37 MiB，decoder PLY 约 124 MiB，限制点数不能约束 mesh 负载。

当前启动只扫描 JSON 索引，Sample 初始为待选择；选择后读取当前样本全部匹配的 complete 结果与 GT，取消原先 12 项限制。后台单 worker 处理最新选择，切换时清空旧显示，在文件读取块、阶段边界检查取消，旧任务不提交场景；第三方解析/编码调用在返回后才能响应取消。输入图像先显示。准备预览按路径、大小、mtime、坐标与质量参数缓存，总预算 64 MiB；源产物不改写。

新增进度条、阶段和耗时。总体百分比按图像、每个结果、GT、场景提交的工作单元，以及读取/解析/编码阶段加权；文件读取阶段按实际字节更新。它是服务器准备进度，不是浏览器下载百分比，100% 后浏览器仍可能传输/渲染。fast/balanced/full 分别提供 2 万/5 万/20 万点；前两档的 mesh 面阈值为 5 万/20 万，超过阈值用保留颜色和节点变换的顶点预览，明确标注，避免随机删面造成假网格；纹理边长为 512/1024 px，full 保留完整 mesh/纹理。GT 始终默认开启，预算不减少匹配项数量。

命令行按实验、单文件、RRD 实体、质量、服务分组；拒绝实验模式混入单文件实体参数，以及非 RRD 文件使用实体选择器。README 维护用途与默认值，不记录实验日志。

专用 screen 验证：

- `python -m pytest tests/test_viewer.py -q -p no:cacheprovider`：14 passed，覆盖启动零几何读取、选择后加载、13 个 run + GT 无截断、预览颜色/节点变换/纹理尺寸/源文件不变、HTTP/WebSocket 交互和退出释放端口。随后扩展同一懒加载用例并单独重跑通过：慢的 b 请求被 a 取代后，不加载其余 b 结果，也不覆盖 a；缓存回访不重复解析。
- 只读测量 P0 索引：10 样本、40 run，约 0.004 秒。MEAT_SET 默认 hybrid 共 984,621 面，balanced 准备约 2.702 秒、缓存数组 1,350,000 字节（50,000 个点，变换后的 float64 坐标与颜色）；full 准备约 30.446 秒、PNG 重编码后的 GLB 66,998,208 字节。该对比包括解析和打包，不包含浏览器渲染；单次测量不是稳定性能保证。
- 真实 localhost WebSocket 检查：初次连接无图像/几何；选择 MEAT_SET 后三方法与 GT 共 4 份几何，约 3.835 秒收到完成状态，累计传输 2,717,850 字节，观察到 16/17/25/33/46/59/66/100% 更新。未人工检查浏览器 GPU 画面。检查结束关闭 viewer 与 screen，无新增长期服务。

日志均在输出根目录 `logs/`：`viewer-progress-check.log`、`viewer-progress-cancel.log`、`viewer-progress-benchmark.log`、`viewer-lazy-web-check.log`，对应 `.exit` 均为 0。没有安装依赖，没有运行模型、修改原始数据/产物或干扰 R2 作业；未提交或推送。

### 2026-10-15：控制栏与画布分区

`viewer.py` 使用 Viser `main_panel.dock_right()`，控制栏初始宽 420 px，可拖动分隔线；停靠区域从三维画布宽度中扣除，避免浮动面板遮挡可视化。单文件和实验模式共用该布局，README 同步说明。

专用 `wt-viewer-layout-check` screen 中复用两项已有 HTTP/WebSocket/退出测试，2 passed；日志 `logs/viewer-layout-check.log`，退出码 0。未修改第三方前端或安装依赖，未人工验收浏览器渲染。正在运行的旧 viewer 需重启后刷新页面。

### 2026-10-15：画布角落视角按钮

画布左上角新增独立小面板，提供缩放 −/＋、平移与旋转四方向按钮。按钮只操作当前浏览器的相机，围绕当前 look_at 缩放/旋转，平移按屏幕坐标；旋转步长 15°。每个客户端拥有独立控件，点击回调按事件循环顺序执行，切换样本/重建场景保留按钮。右侧主控制栏继续停靠。修正 Reset view 的相机赋值顺序：Viser 设置 position 时会同时平移 look_at，因此应先设置 position，再恢复目标中心。

专用 screen `wt-viewer-camera-final` 通过两个真实 localhost WebSocket 客户端检查：缩放、四方向平移/旋转、连续 24 次俯仰旋转后的距离/中心/姿态、不同客户端隔离、scene reset 后按钮仍可用、Reset view 目标中心一致。复用单文件和实验模式网页回归，2 passed。日志 `logs/viewer-camera-final.log`，退出码 0；测试服务已退出，未人工验收浏览器画面。无新依赖，不改模型/数据/产物；原 viewer 进程需重启并刷新页面。

### 2026-10-18：WT 颜色来源、深度显示与 balanced mesh 拓扑

依据 `docs/20261015_hybrid-baseline_20261013-R1-object-qual-v1.md` 的 2.4 节，修复 viewer 将 `[H,W,3]` 输入 RGB 广播到全部 WT 层的问题。`gray` 是默认模式，WT 全灰，已有 mesh 纹理/顶点颜色保留，无颜色填灰；`surface` 使用 NPZ 中与预测像素对齐的预处理 RGB，仅映射 layer-0，其余层灰色。扁平 RRD/PLY 缺少层/像素对应时不猜测对应关系，显示灰色并标注。`depth` 覆盖原表面颜色，使用恢复坐标后、并排平移前的显示 `−Z`，各结果独立归一化，近蓝远红；GLB/PLY mesh 使用无光照深度材质，不代表跨结果共享度量距离，也不随观察相机旋转变化。

balanced 改为完整 mesh + 最长边 1024 px 纹理 + 每份 50,000 点。新增 `viewer_glb.py`，对普通静态 GLB 直接复制原顶点、索引、UV 和法线缓冲，通过父节点实现坐标恢复，仅重编码需缩小的纹理或附加深度颜色。其他格式和不支持的 GLB 布局交给 trimesh。fast 仍可显示明确标注的顶点预览；full 改为全部有效点和原始 mesh/纹理，`--max-points 0` 也表示不限点数。只并行加载当前选中样本的两份结果，不限制比较数量，不预加载其他样本；GT 默认开启。缓存提高到 256 MiB，非 WT 的灰色/表面颜色共用缓存。

专用 screen `wt-viewer-colors-regression`：`python -m pytest tests/test_viewer.py -q -p no:cacheprovider`，**20 passed**，退出码 0。覆盖层掩码与颜色对应、隐藏层不复制输入 RGB、无层对应的安全回退、深度范围不随点采样改变、共享 mesh 多实例的深度和坐标恢复、GLB 几何缓冲逐字节不变、WebP 缩图与透明度、GT PLY 深度材质、13 个 run + GT 不截断、过期任务取消、两种入口的真实 HTTP/WebSocket 颜色切换及退出端口释放。源文件不变检查通过。

真实性能检查使用 R1 的 `obj025_cartoon_dino`、`obj069_pixar_dwarf`、`obj083_chibi_swordsman`、`obj149_hand_painted_kokeshi_set`，以及 P0 的 `MEAT_SET`，均为 defaults-v1 / seed 42 / balanced。R1 每样本三方法（两个完整 mesh 和 WT 点云），P0 另含真实 GT mesh。每次清空已准备结果缓存，不清空操作系统文件缓存；测量从选择样本到本机 WebSocket 接收完成状态和同批几何数据，不包含浏览器 GPU 渲染、SSH 链路或应用启动。

| 显示模式 | 5 个样本的本机接收耗时 |
| --- | --- |
| 灰色（默认） | 3.441–4.620 s |
| 表面颜色 | 3.355–5.251 s |
| 深度 | 1.753–2.897 s |

15 次服务器准备时间为 0.5–3.5 s；本机接收 14/15 次低于 5 s，一次表面颜色冷准备为 5.251 s。完整 mesh 传输量约 48–58 MB；不同网络、更多比较项、大型 decoder mesh 或 full 不保证 5 s。与此前顶点预览的 2.7 MB 测量不是同一显示质量。

日志/测量：输出根目录 `logs/viewer-colors-regression.log`、`viewer-colors-benchmark-final.log`、`viewer-colors-benchmark.json`。测试服务与 screen 已退出，无新增长期服务。曾尝试 Firefox 渲染验收，但 Snap 包装启动失败，直接调用现有驱动又因系统缺少其要求的 GLIBC_2.39 而失败；未安装浏览器或修改系统配置，因此未声称通过浏览器画面验收。对应日志 `viewer-browser-check.log`、`viewer-browser-native.log`。未运行推理、修改数据/权重/已有产物或中断其他实验；未提交或推送。原 viewer 需重启并刷新页面。

### 2026-10-18：结果网格排布

查看器按结果数量生成接近方形的网格：4 项为 2×2，6 项为 2 行×3 列，9 项为 3×3。按最大几何宽高设置统一单元尺寸与间距，末行不足时居中；保留原尺度，整体和单项视角继续根据可见结果自动取景。单文件与实验模式共用此布局。

专用 screen `wt-viewer-grid-check` 复用 HTTP/WebSocket 单文件与实验浏览回归：2 passed（其余 18 项未运行），日志 `logs/viewer-grid-check.log`，退出码 0。检查结束服务退出；未验收浏览器 GPU 画面。README 已同步使用说明，原 viewer 需重启后刷新页面。

### 2026-10-19：Pixal3D 独立源码与隔离环境

用户确认采用独立仓库 + `compare_methods` 软链接，按阶段推进。第一阶段只准备源码、环境及无权重 CUDA 验证，不下载模型权重、不运行 R1/R2。

源码布局：

- `/data1/LiuShuqi/code/Pixal3D`：官方仓库，detached HEAD `f7cf38429b0bd264f1995f0f8743a88b1c728b94`，无本地源码修改。
- `compare_methods/Pixal3D -> ../../Pixal3D`：相对链接，在 Workspace 和真实路径访问时均指向同一仓库。
- `dependencies/MoGe2`：`b942f00bdc2a2a23ebb474fbe034d487e6dcceec`；`dependencies/NAF`：`37f2dfc180f2de53d98bd601109c0da0dd6b0f43`。
- 新增来源锁在 `compare_methods/pixal3d/sources.lock`。旧 `scripts/clone_dependencies.sh` 只识别原有依赖名，因此没有向根目录 `dependencies.lock` 填入无法被旧脚本解析的新项目。

从 `/home/LiuShuqi/.conda/envs/world_tracing` 离线复制到 `/home/LiuShuqi/.conda/envs/world_tracing_pixal3d`，保留 PyTorch 2.6.0+cu124 / NumPy 1.26.4 及既有 TRELLIS 原生扩展。首次 Conda 命令被默认 channel 的 ToS 检查拦截；改用当前命令的 `--override-channels --channel conda-forge --offline` 后成功，没有修改全局配置或接受条款。首次 prepare 在复制和 pip check 成功后遇到脚本 EOF（执行期间编辑了脚本），已重新做 `bash -n` 和完整 prepare 校验；保留原失败日志，后续执行期间固定入口脚本。

新环境增加 diffusers 0.37.1、accelerate 1.13.0、NATTEN 0.21.0 及必要 Python 依赖；MoGe-2 从固定源码导入，不安装其训练/demo distribution。Pixal3D 官方 utils3d wheel 与原环境版本号同为 0.0.2，但提供 MoGe-2 所需 `pt` 和深度反投影接口，只有新环境安装该 wheel。文件校验、环境变量和安装操作固化在 `compare_methods/pixal3d/setup.sh`。

NATTEN 使用 CUDA 12.4、`NATTEN_CUDA_ARCH=8.9` 编译；其 setup.py 会将小数架构乘以十，实际生成 `compute_89/sm_89`。初始四个 worker 编译较慢；确认本机 128 核、约 476 GiB 可用内存后，只停止本任务的编译/等待检查 screen，保留源码和对象文件，改用 16 个 worker 在原 CMake 目录离线续建。编译参数保存为日志目录中的 `natten-CMakeCache.txt` 和 `natten-flags.make`。utils3d 第二次下载超时后，复用本任务先前已下载的相同 wheel 并重新校验 SHA-256，未使用代理或改换包来源。

本阶段 screen：`wt-pixal3d-setup`、`wt-pixal3d-prepare`、`wt-pixal3d-install`、`wt-pixal3d-install-retry`；短时下载/审计使用独立 screen。日志根目录 `/data1/LiuShuqi/output/world_tracing/logs/pixal3d-setup/`：

- `bootstrap.log` / `bootstrap.exit`：初始克隆和默认 Conda channel 失败记录。
- `prepare.log` / `prepare.exit`：环境复制及首次脚本错误记录；`prepare-verified.log` 为重跑通过的校验。
- `install.log` / `install.exit`：首次安装与重复下载超时；`install-retry.log` 为复用已校验 wheel 后的四 worker 编译，因主动切换并行度而中断，不作为成功记录。
- `build-16.log` / `build-16.exit`：screen `wt-pixal3d-build16` 的续建、安装与 CUDA 检查；`natten-wheel.sha256` 记录本机构建 wheel 哈希，wheel 保存在 `cache/pixal3d/wheels/`。
- `base-before.txt` / `base-after.txt` / `base-diff.txt`：原环境包清单对比；`base-check.log` / `base-audit.exit`：原环境 pip check。

第一阶段验收通过，`build-16.exit=0`，新环境 `pip check` 通过。离线检查结果保存至 `/data1/LiuShuqi/output/world_tracing/validation/pixal3d-environment.json`，完整输出为 `check.log`，包含六组检查：推理类导入；NATTEN CUTLASS/FlashAttention 对照 SDPA；NAF FP32、1024 通道常量特征上采样；MoGe 焦距/平移恢复与 utils3d 相机 API；Pixal3D FlexGEMM 对照 dense Conv3d 及 O-Voxel 编解码；CuMesh/nvdiffrast GPU 几何与光栅化。没有使用预训练权重，不能据此认定模型生成质量或 R1/R2 完成。

新环境保留 PyTorch 2.6.0+cu124、Transformers 4.57.6、NumPy 1.26.4；NATTEN 0.21.0、diffusers 0.37.1、accelerate 1.13.0 已安装。原环境审计退出码为 0，包清单一致、pip check 通过，原 utils3d 的入口文件与原锁定源码逐字节相同。Pixal3D、MoGe-2、NAF 三个 checkout 均 clean，报告记录其真实模块来源与精确提交。

本机构建的 `natten-0.21.0-cp311-cp311-linux_x86_64.whl` 约 27 MiB，SHA-256 为 `1033ea88b138e73252a12128bc109cbde10b7a23d213d551d8360d991c6998fa`；安装快照在 `compare_methods/pixal3d/requirements.lock.txt`，包含两个本地 wheel 的哈希。安装脚本仅在相同 Python/PyTorch/架构配置下复用已验证 wheel，保留缺失时的源码编译路径。

最终脚本检查在 `wt-pixal3d-final-audit` 中完成，`final-audit.exit=0`：Shell 语法与 screen 防护检查通过，`PIP_NO_INDEX=1` 下缓存安装通过，原环境包清单再次与安装前逐字节一致、pip check 通过。`final-audit.log`、`install-cached.log` 保存证据；bootstrap、续建及最终审计脚本副本保存在同一日志目录。环境约 7.3 GiB，任务缓存约 120 MiB，保留的编译临时目录约 591 MiB；未清理用户其他缓存或 screen。

原始 GSO、模型权重及既有 R1/P0/R2 产物未修改；未提交或推送。下一阶段为独立 Pixal3D adapter、单样本预训练验证，再接入批量评价与查看器。

### 2026-10-20：多选筛选与默认显示模式

Method、Config、Seed 使用 Viser 公共 checkbox/folder API 实现多选，每组带全选/清空按钮和已选数量。选项来自实验索引，包含 Pixal3D 等已注册方法；Method、Config 默认全选，Seed 默认第一个。组内为 OR、组间为 AND；空选择意味着没有匹配 run，GT 仍由独立开关控制。刷新保留有效子集，原先全选的组自动包含新增选项；按需加载、取消过期请求与网格布局保留。

网页和 CLI 默认改为 full / surface（表面颜色），显式 `--quality` / `--color-mode` 仍可覆盖。未改变点云或 mesh 的文件处理算法。

专用 screen `wt-viewer-multiselect-check` 中复用并扩展相关回归：`python -m pytest tests/test_viewer.py -q -p no:cacheprovider -k "experiment_loads or parser or single_port"`，6 passed、14 deselected，退出码 0。覆盖真实多方法/配置/seed 的组合筛选、空选择保留 GT、刷新保留子集、无比较数量限制、过期请求取消、CLI 默认与覆盖，以及 HTTP/WebSocket 操作三组复选框、颜色切换与停止释放端口。日志 `logs/viewer-multiselect-check.log`；测试服务已退出。未安装依赖或修改其他实验；既有 viewer 需重启后刷新页面。

### 2026-10-20：带纹理 mesh 兼容与 GSO GT 来源

新增 `viewer_mesh.py`，读取 OBJ 多个 mtllib 和材质分组，按 MTL 所在目录解析 map_Kd（必要时兼容 OBJ 相对路径），允许明确引用的本地父目录资源，不按同名文件猜测贴图、不访问网络。GLTF/GLB 外部 BIN/图片支持 URI 编码路径；GLB 引用外部图片时转入通用加载并嵌入纹理。PLY 有面时自动按 mesh 读取，可保留顶点颜色及 TextureFile/UV，纯点云 PLY 与显式 WT --points 仍按点云处理。多材质 geometry 按实际面材质分组显示，不删除三角面。普通 map_Kd 路径受支持，带额外 MTL 贴图选项的声明会给出不支持提示。

外部材质/图片及缺失资源的状态纳入缓存校验；刷新后可以发现贴图修改或缺失文件补齐。缺失引用在页面状态中提示，仍可显示几何。导出使用局部 PIL 代理，能保留原 PNG/JPEG 编码时直接复用，否则使用快速无损 PNG 编码；不修改 Pillow/trimesh 全局行为或原始纹理，full 保留原分辨率。

GSO 的 input.json 原先将 GT 指向只含顶点和面的 gt_camera.ply。查看器现在只读 evaluation_dir 对应的 camera.json 和上层 inventory.jsonl，定位原始模型并应用 `display_RDF @ T_world_to_camera @ T_asset_to_world`。任何来源或变换缺失会报告原因，回退到已声明的评测几何；其他数据集继续使用自己的 ground_truth 文件。没有重新生成数据、改写评测文件、冻结清单或原始模型。

专用 screen `wt-viewer-mesh-export-check`：`python -m pytest tests/test_viewer.py tests/test_viewer_mesh.py -q -p no:cacheprovider`，**26 passed**，退出码 0。新增验证包括两个 OBJ 材质库/跨目录贴图、贴图更改后的缓存失效、缺失图片提示、GLTF 外部缓冲与图片、full GLB 外部图片嵌入、PLY 面/点/贴图识别、多材质面与节点变换，以及 GSO 来源选择/坐标/缺失回退；已有网页 HTTP/WebSocket 回归仍通过。

真实样本 Frozen_Olafs_In_Trouble_PopOMatic_Game 与 MEAT_SET 分别读取 4096×4096 原贴图并导出内存 GLB，full 准备约 **0.626 s / 0.856 s**。与 gt_camera.ply 对比，显示边界最大误差分别为 **3.65e-8 / 7.79e-8**。两例均无缺失纹理提示；原模型、GT PLY、清单和坐标文件 SHA-256 检查保持不变。时间只包含服务器准备，不含传输与浏览器 GPU 渲染；未做浏览器画面验收。

日志位于输出根目录 `logs/viewer-mesh-export-check.log`、`viewer-textured-gt-final.log`，对应退出码均为 0。测试服务与 screen 已退出，临时验证脚本已清理。README 仅更新格式和使用说明。未安装依赖、运行推理、提交或推送；已有 viewer 需重启并刷新页面。

### 2026-10-20：WT ablation 浏览与适配模块整理

`--experiment` 在标准 experiment.json 优先的前提下自动识别 `<sample>/<config>/prediction.npz` 或未完成配置的 metrics.json。专门适配仅针对 WT camera RDF 点图；索引不读取数组或图片，seed/裁剪比例/背景等来自各配置 metrics.json，未记录 seed 显示 unknown。缺失或损坏记录不会阻断其他配置；缺少 prediction.npz 的配置在页面报告。标准实验的目录契约与推理程序不变。

选中样本后按 Config 多选加载结果；所有配置使用自己的 NPZ RGB，仅给 layer-0 着色。`Input / configuration` 切换所选配置的输入图片和参数，不重新加载几何；清空配置时不显示某个未选配置的输入。full / surface 默认、GT 开关、按需加载、缓存和取消过期请求保持。可选 sample/input.json 声明 GT，引用路径相对该文件；未声明完整 GT 时明确提示，不把 gt_depth 当成完整模型。

`viewer_glb.py`、`viewer_mesh.py` 移至 `viewer_utils/glb.py`、`mesh.py`；GSO 来源解析独立为 `viewer_utils/gso.py`，WT 消融目录适配为 `ablation.py`，索引分发为 `experiments.py`。通用 GUI、加载调度和布局仍在 viewer.py；README 更新 package layout 和使用说明。

专用 screen `wt-viewer-ablation-check` 运行 `python -m pytest tests/test_viewer.py tests/test_viewer_mesh.py tests/test_viewer_ablation.py -q -p no:cacheprovider`，**28 passed**，退出码 0。新增覆盖无数组读取的索引、缺失/损坏元数据、未知 seed、可选 GT 相对路径、多配置懒加载、输入图/参数切换、空选择和缓存；原有 mesh、GT、HTTP/WebSocket 与退出释放端口回归通过。

专用 screen `wt-viewer-ablation-real` 只读验证 `validation/z-root-cause-20261020/inference`：Hat、Frozen Olaf、School Bus 共 3 样本 × baseline/black/crop50/crop80/whole 五配置，默认 full 全部成功，输入均为各配置的 504×504 图像；检查点坐标有限、存在表面颜色、仅按当前样本加载、本机 HTTP 200，文件大小与修改时间前后相同。该目录没有声明完整 GT，界面报告缺失。此验证未进行浏览器 GPU 画面验收。

日志与退出码存于输出根目录 `logs/wt-viewer-ablation-check.{log,exit}`、`logs/wt-viewer-ablation-real.{log,exit}`；两个退出码均为 0。测试服务与 screen 已结束，临时真实数据验证脚本已清理。未安装依赖、运行模型、改写实验数据、提交或推送。已有查看器需重启后刷新页面。
