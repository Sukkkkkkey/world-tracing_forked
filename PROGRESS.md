# world_tracing 项目进度

更新日期为 2026-11-07（Asia/Shanghai）。

## 2026-11-07 新服务器恢复完成

- 已按历史样本、配置和 seed 重跑并验收 621 项，包括 P0 50、R1 150、R2 400、裁剪/背景 15、纹理种子 6。正式工作簿于 10:50（Asia/Shanghai）覆写为本轮数值。4 条人工结论、4 条实验目的和 11 条备注按实验身份保留。
- 最新结果、旧值差异与质量问题汇总在 [恢复结果报告](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_recovery-results.md)。工作簿为 [experiments.xlsx](/mnt/cpfs1/shuqiliu/code/world_tracing/experiments.xlsx)。总验收记录位于输出目录 `validation/recovery-20261105/final.json`。
- 代码和两个隔离环境位于 CPFS。Python 3.11 / PyTorch 2.6.0+cu124 / NumPy 1.26.4 与 A100 SM80 原生扩展已验证。环境安装、私有 C++ 运行库、OSS 顺序发布和 Pixal 克隆修复均进入代码与版本记录。完整回归 117 项、存储回归 14 项、Pixal 六组 CUDA 验证均通过。
- 权重下载与摘要校验完成。DINOv3/RMBG-2.0 使用 ModelScope，公开 HF 文件使用 hf-mirror，WT 授权模型从官方来源取得。GSO 1030 个原始 ZIP 完成 SHA/CRC 校验，派生资产 1030 个有效。PCG64(20261013) 重放的 10/100/920 划分与历史样本一致，110 份冻结输入及 GT 已重建。旧 MegaPose 整包缺失，数据来源限制详见恢复结果报告。
- R2 前完成单卡批量测试。WT batch=2/4 的 XYZ 出现差异，正式采用 batch=1。完整样本分配的 mesh / Pixal 双进程在固定小样本中分别获得 1.530 / 1.511 倍吞吐，解码几何与导出前纹理一致。配置和正式执行记录见 [单卡复核](/mnt/cpfs1/shuqiliu/code/world_tracing/docs/20261105_single-gpu-batch-review.md)。
- R2 首轮监控查询超时已修复并通过 14 项回归。两个 hybrid 经并行和原方案串行重试仍显存不足，采用经过 59 个 CUDA 算例、两个完整预训练对照及 13 项文件保护测试验证的历史分块/缓存释放方案完成。其余 298 项的 1,689 个文件摘要保持一致，两份重放 WT 缓存逐数组一致。
- R2 Pixal 100/100 完成，工作进程阶段耗时 425.25 分钟，显存峰值 36.22 GiB，实例工作集峰值 115.64 GiB，重试 0 项。Hefty 废纸篓单样本导出耗时 274.22 分钟。全量耗时与小样本加速测试各有独立记录。
- 形状评价的 R2 四方法均为 100/100 有效。SSI 深度保留 WT 1 项、hybrid 20 项质量失败，hybrid 有效数较旧记录由 82 变为 80。新旧数值差异及共同有效样本比较已公布，差异来源尚未定位。
- 图像检查覆盖 110 张冻结 GSO 输入、P0 全部 10 个样本、R1 全部 30 个样本、R2 固定选择的 10 个样本和两组对照。全部 621 项通过各自适用的自动产物/指标审计。最新报告记录几何缺损、朝向和纹理问题。
- 工作簿 ZIP、数值来源、人工备注、合并区、列宽、行高、冻结窗格和本地链接已检查。预览工具生成图像后异常退出，逐样本页有合并单元格遮挡，旧工作簿预览出现同样现象。原生 Excel 界面尚未验证，详细记录为 `validation/recovery-20261105/workbook-review.json`。
- 已归档并删除 31 个旧一次性脚本及失败环境副本，保留当前恢复入口所需内存辅助模块。清理证据为输出 `validation/recovery-20261105/cleanup.json`，最终归档入口为 `recovery/20261105T044019Z/final-20261107/manifest.json`。
- 迁移前源码、Git 状态和工作簿保存在输出 `recovery/20261105T044019Z/`。本次保留已有未提交改动，恢复操作与失败尝试详见 RUNBOOK。以下条目保留旧服务器研究历程。

## 2026-10-20 Ablation 浏览与查看器模块整理

- `viewer.py --experiment` 自动识别 WT `<样本>/<配置>/prediction.npz` 目录；支持配置多选并排、按样本加载，以及各配置输入图和参数切换，默认 full / 表面颜色。
- 通用交互留在 `viewer.py`；GLB、mesh 格式处理迁到 `viewer_utils/glb.py`、`mesh.py`，GSO 与 WT ablation 分别由 `gso.py`、`ablation.py` 适配。
- 28 项查看器回归通过；`validation/z-root-cause-20261020/inference` 的 3 个样本、15 份输出验证通过。此目录未声明完整 GT，页面明确提示；没有改写实验或原始数据。验证边界与日志见 RUNBOOK。

## 2026-10-20 R2 四方法与逐样本分析

- [R2 分析报告](docs/20261020_hybrid-baseline_20261013-R2-gso-quant-v1.md) 已覆盖全部 100 个正式物体、400 项结果，并增加论文 Table 1 的形状与深度对照；明确跨协议数值不能直接判定复现成败。
- 全部 1,600 个形状值复算一致，100 个 GT 重渲染与输入一致；完成全量逐图检查及六个重点案例的 decoder PLY / GLB 对照。形状均值为 TRELLIS.2 > Pixal3D > WT > hybrid；共同有效 81 个物体上 WT 的深度优于 hybrid。
- 分析证据存于 `validation/r2-analysis-20261020/`；修正了分析图中的 Pixal3D 原生观察方向。正式实验和工作簿成绩保持原样，未用新 seed、手调配准或替换样本改善分数。

## 2026-10-20 P0 逐样本分析

- 完成固定 10 个 pilot 样本、四方法及 shared-WT 对照共 50 项的指标复算与逐图核验；四个形状指标全部与保存值一致，10 个 GT 重渲染与输入逐像素一致。
- [P0 分析报告](docs/20261020_hybrid-baseline_20261013-P0-gso-pilot-v1.md) 区分形状、姿态和纹理，逐项核对用户观察，并定位 Hat 内腔额外点、Horse/Pixal3D 和 Bull/hybrid 导出前已有的几何缺陷。证据与复查脚本存于 `validation/p0-analysis-20261020/`。
- 本次只读分析既有实验，未重跑模型或覆盖原成绩；R2 不纳入该报告。

## 2026-10-20 带纹理 mesh 与 GT 显示

- 查看器支持 OBJ 多材质库与相对贴图路径、GLTF/GLB 外部资源、带面及 UV/TextureFile 的 PLY；有面的 PLY 自动按 mesh 显示。外部资源变更会使显示缓存失效，缺失材质/贴图在页面提示。
- GSO GT 优先使用 inventory 中的原始带纹理模型和 camera.json 保存的资产→世界→相机变换；缺失来源或变换时回退到原评测几何。评测文件、冻结清单与原始数据保持不变。
- 26 项查看器回归通过。Frozen Olaf 与 MEAT_SET 的 4096×4096 GT 贴图和坐标校验通过，边界最大误差小于 1e-7；full 服务器准备约 0.63/0.86 秒，不包含网络与浏览器渲染。使用说明见 README，验证日志见 RUNBOOK。

## 2026-10-20 Excel 预览兼容修复

- 修复 Office Viewer 4.2.2 因无法识别 openpyxl 批注部件而静默显示空白 Sheet1 的问题；当前工作簿及后续研究记录导出均使用兼容的内部部件路径。
- 原文件已备份，所有单元格、批注、链接、样式和合并区域核验保留；2 项回归及插件原解析器加载通过。本地 VS Code 需关闭旧标签页并重新打开，UI 尚未人工确认。路径、根因与核验记录见 RUNBOOK。

## 2026-10-20 Pixal3D R1/R2 完成复核

- 后台队列于 2026-10-19 22:18 正常结束，`pilot.exit=0`、`formal.exit=0`，本任务推理 screen 已自然退出。当前没有执行阻碍。
- P0：10/10 推理、形状评价及验收通过（10 月 19 日 17:15）；R1：30/30 推理与产物验收通过（17:45，无 GT 定量评价）；R2：100/100 推理、形状评价及验收通过（22:17）。无失败或待处理 Pixal3D run。
- 今天重新核对逐样本状态、既有验收报告和工作簿；旧 P0/R1/R2 的 131/271/1001 条输入及结果索引摘要均未改变。复核报告：`/data1/LiuShuqi/output/world_tracing/validation/pixal3d-progress-20261020.json`。本次没有重跑推理或评价，也没有重复逐网格哈希验收。
- R2 的四方法共同成功集合为全部 100 个物体。在当前 `gso-shape-sim3-v1`、seed 42、1024 配置下，CD-L1 和 F-score 排序均为 TRELLIS.2 > Pixal3D > WT > WT+TRELLIS.2 hybrid。Pixal3D CD-L1=0.011763，F@0.01=0.642681，F@0.05=0.971770；这是本项目协议结果，不是论文数值复现。
- 根目录 `experiments.xlsx` 已更新，`FourMethodShape` 包含 P0/R2 四方法比较。Pixal3D 的 native-camera 与 SSI-depth 仍为 N/A：原视图尺度变换尚未验证；本次完成范围为 R1 产物和 R2 形状评价，不含这些相机指标。

## 2026-10-20 查看器多选与显示默认值

- Method、Config、Seed 改为可折叠的多选勾选列表，提供全选/清空。Method 与 Config 默认全选，Seed 默认第一个；刷新保留有效选择，清空筛选不影响独立 GT 开关。
- 单文件与实验入口默认 full + 表面颜色，可继续通过命令行或页面覆盖。
- 6 项相关回归通过，覆盖多方法/配置/seed 组合筛选、空选择、刷新、过期加载取消及真实 HTTP/WebSocket 交互。使用说明见 README，验证日志见 RUNBOOK。

## 2026-10-19 Pixal3D 对比基线：第二阶段（已完成）

- 新增独立模型适配器和追加入口，复用现有 R1/P0/R2 冻结输入；原三方法推理范围保持原样。结果注册、查看器、形状评价和四方法共同成功统计已联动。
- 固定配置为 `resolution1024-v1`、seed 42、12/12/12 步、4096 纹理和官方 low-VRAM 模式；普通上游默认 1536，因此没有把 1024 配置称为官方默认。
- 38 项契约/评价/原入口回归通过；新增 GPU 分片后 7 项 Pixal3D 专项测试通过。旧实验输入与索引摘要保存在 `validation/pixal3d-existing-results-before.json`。
- 权重已全部下载并通过逐文件校验，清单为 `weights/pixal3d/manifest.json`，新增占用约 22 GiB。DINO 与 decoder 按校验摘要复用已有文件；NAF 从固定本地源码和显式 checkpoint 加载。
- briefcase 真实预训练单样本通过：模型加载 185.6 s，生成/导出 517.9 s；633 万面 decoder PLY 与约 38 MiB GLB 均通过重载和摘要检查，旧 R1 的 271 条索引未变。报告 `validation/pixal3d-single.json`。这是首次冷启动样本，不代表稳定批量速度。
- `wt-pixal3d-pilot`、`wt-pixal3d-formal` 已按单样本→P0→R1→R2 顺序完成推理、适用的形状评价、验收与工作簿更新，两个队列退出码均为 0；完成复核见上方 2026-10-20 记录。
- 形状使用原 `gso-shape-sim3-v1`；Pixal3D 归一化相机距离尚未验证到原始视图的真实尺度变换，native-camera / SSI-depth 标为 N/A，原因随结果保存。

## 2026-10-19 Pixal3D 对比基线：第一阶段

- 按用户确认的结构，独立克隆 `/data1/LiuShuqi/code/Pixal3D`，固定 `f7cf38429b0bd264f1995f0f8743a88b1c728b94`；`compare_methods/Pixal3D` 为相对软链接。
- 已复制专用环境 `/home/LiuShuqi/.conda/envs/world_tracing_pixal3d`；固定 MoGe-2/NAF 源码，新增环境准备、依赖约束和离线 CUDA 验证入口，说明见 `compare_methods/README.md`。
- 第一阶段已验收：新环境 `pip check` 和六组离线验证通过，包括真实 NATTEN/FlashAttention 数值对照、NAF FP32/1024 通道上采样、MoGe 相机 API、Pixal3D 稀疏卷积及网格算子。报告为输出目录 `validation/pixal3d-environment.json`，`build-16.exit=0`。
- 原 `world_tracing` 环境包清单前后相同，`pip check` 通过，原 utils3d 文件与锁定源码一致。新环境安装快照已保存；NATTEN wheel 与哈希已缓存，支持同配置复用。
- 未下载预训练权重、运行模型生成或追加 R1/R2；下一阶段为独立 adapter 与单样本接入。原始数据和既有实验产物保持不变。

## 2026-10-18 可视化颜色与 mesh 显示修正

- 按 R1 报告 2.4 修正输入 RGB 被广播到 WT 隐藏层的问题。新增灰色、表面颜色、深度模式：默认保留已有真实纹理，无纹理填灰；表面颜色仅用于 WT layer-0；深度覆盖所有结构的颜色。单文件和实验浏览均支持网页切换。
- balanced 保留完整 mesh 拓扑、法线及 UV，仅将纹理最长边限制为 1024 px，点云仍采样至 5 万点；full 不再限制点数。当前样本内最多并行两份结果，256 MiB 缓存；保持选中再加载、GT 默认开启和比较数量不限。
- 20 项 viewer 回归通过。文档中的 4 个 R1 样本及含 GT 的 P0 MEAT_SET，默认灰色 + balanced 的本机接收为 3.44–4.62 秒；三模式共 15 次测量中有一次表面颜色为 5.25 秒，其余低于 5 秒。浏览器渲染未验收（现有 Firefox 驱动无法在此系统启动）；详细测量边界见 RUNBOOK。

## 2026-10-15 网页加载改进

- 实验查看器启动仅扫描 JSON 索引，选中样本后才加载图像、全部匹配结果与 GT；GT 默认开启，取消原有 12 项限制。快速切换时只处理最新选择，旧结果不会覆盖新场景。
- 新增服务器准备进度条、阶段说明和耗时；默认 balanced 为每份 5 万点、20 万面预览阈值、1024 px 纹理，大 mesh 明确显示为顶点预览，full 保留原始 mesh/纹理。提供 64 MiB 预览缓存，不改写源文件。
- 14 项 viewer 测试通过，并扩展验证了过期加载取消。真实 P0 的 MEAT_SET：三方法与 GT 共 4 份几何约 3.8 秒准备完成，同端口 WebSocket 收到约 2.7 MB 和中间百分比。未做浏览器 GPU 画面的人工验收，测试服务已退出；命令与测量边界见 RUNBOOK。

## 2026-10-15 R2 正式实验（2026-10-18 验收完成）

- 固定 eval100 的 100 个 GSO × 三方法默认配置：300/300 推理与评价完成。seed=42、batch=1、1024_cascade；与 P0 独立，不含 shared-WT。
- 配准后 CD-L1 排序：TRELLIS.2 > WT > WT + TRELLIS.2 hybrid。共同有效深度集合 81 个物体；深度质量失败 WT 1/100、hybrid 18/100，错误指标留空，不换样本。
- R2 输出、summary.json、reproduction/validation.json 均位于 20261013-R2-gso-quant-v1；结果文档 docs/20261014_hybrid-baseline_results.md 已以 R2 为正文，P0 移至附录。experiments.xlsx 已按实验 ID 更新。
- 修复 Unicode 资产 ID 校验，26 项批量/几何/目录检查通过；100 个原生结果均确认 Stage 1、无 WT parent，200 个 GLB 容器完整，评价源码与修正后的 P0 一致。
- 2 项首次失败后以原 GPU、原配置和 seed 重试成功；2 项使用已验证的独立行 LayerNorm 显存优化。显存策略与失败记录保存在各 worker/retry-*/。
- R1 120 项、P0 40 项既有结果保留；参数扫描及 best-of-8 尚未运行。

## 2026-10-14 修正完成记录（历史）

- R1 120 项与 P0 40 项推理已完成。修复原生 TRELLIS 误用 WT 缓存的问题，40 个错误原生结果已重新推理并覆盖原目录；最终核验全部执行真实 Stage 1，且 GLB 容器完整、无 WT parent。
- 修复 26,031,912 面网格的 CUDA 光栅化错误：每批最多 100 万面、最近 Z 合并，不简化几何；逐 run 独立进程评价。P0 40/40 评价执行成功，旧错误指标已覆盖。默认 hybrid 有 2/10、shared-WT 有 1/10 深度覆盖率低于协议门槛，指标保留为空值；这属于实测质量问题而非执行故障。
- 9 项批量测试、5 项几何/渲染测试、1 项进程隔离测试通过。原失败大网格现可正常渲染；两个原成功真实样本的 15 项指标最大变化约 3.9e-9。最终核验报告在 P0 的 `reproduction/correction-20261014/validation.json`。
- 当前 10 个 pilot 的配准后形状精度排序为 TRELLIS.2 > WT > hybrid，与论文排序不同；数据、配准/归一化及单 seed 协议不同，不能直接视作论文数值复现。结果与完整协议边界见 `docs/20261014_hybrid-baseline_results.md`；`experiments.xlsx` 已更新，包含论文对照和共同有效资产上的深度对比。
- 已清理中断下载、未采用镜像及临时审计文件；完整 raw GSO、有效产物、WT 缓存与复现所需记录保留。
- 正式 R2 100 个物体与参数扫描仍未启动。

## 2026-10-13 启动与入库记录（历史）

- 实验方案已整理为核心正文 + 附录；默认对比、shared-WT、单因素扫描、独立 GSO 划分及形状/相机/深度协议已复查。固定推理 seed=42、划分 seed=20261013，补齐跨库 RNG 与环境记录。
- R1 正在运行：GPU 0、30 张示例、120 个默认/受控任务，从冻结源码和输入快照执行；60 份 WT 缓存已完成，30 个 WT 基线结果已完成，后续为 90 个 mesh 任务。原生 TRELLIS 默认完整预检已成功，GLB/decoder mesh 重载检查通过，预检结果不并入正式统计。
- 原站 GSO ZIP 下载在约 13 GiB 处 TLS 中断且不支持当前通道的 Range 续传。已从 CRC 正确的原清单确认 944+86=1030 个资产；改按此全集下载固定 revision 的原始 ZIP 镜像，额外 16 个镜像条目不采用。已抽查 20 个资产与原 ZIP 的 OBJ 字节、RGB 纹理像素一致。
- GSO 原始数据已完整保存到 `/home/LiuShuqi/Workspace/data/world_tracing/raw/gso/`（真实路径 `/data1/LiuShuqi/data/world_tracing/raw/gso/`）：1030/1030 个 ZIP 的 SHA-256、解压成员 CRC 与必要文件检查通过，`COMPLETE.json` 已生成，`datasets/gso/raw-ready.exit=0`。原始 ZIP 共 8.07 GiB，解压内容未修改。满足用户的数据前置条件后，已恢复输出目录下的派生入库与 P0 队列；raw 原件后续只读。
- 派生入库完成，1030 个资产全部通过网格/纹理检查，排除 0 个；与未完成原站 ZIP 中可读取的 320 个资产比较，OBJ 字节及 RGB 纹理像素均一致。10/100/920 划分已冻结，互斥性与 PCG64(20261013) 精确重放通过。P0 的 10 张输入和 GT 渲染完成，GPU 1 已启动 40 项默认/shared-WT 推理；正式 R2 尚未启动。
- `experiments.xlsx` 已创建并随首轮任务自动更新，登记 R1/P0/R2 状态、实际配置和逐任务记录；没有伪造定量成绩。相关最小验证为 34 + 3 项通过，`pip check` 通过。
- GSO 渲染与形状/相机/深度评价代码已补齐：5 项数学/真实 GPU 渲染测试及合成资产三方法端到端检查通过；真实物体渲染确认源 Z-up。新增工作簿 `MetricSummary`，报告逐资产均值、失败/待处理及共同成功集合。数据完整门槛与汇总/记录的 5 项测试通过；真实 GSO 评测还未执行。
- 待完成：R1 剩余 mesh 结果、P0 推理/评价与验收、正式 100 个物体定量实验、参数扫描与最终汇总。详细命令、screen、路径和进度边界见 RUNBOOK 最后一节。

## 已完成

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

## 最终验收

统一版本环境的独立 GPU 逻辑验收已通过。随机权重结果位于 `/data1/LiuShuqi/output/world_tracing/validation/wt-smoke.json`、`trellis2-smoke.json`；后续真实权重报告为 `weights-integrity.json`、`trellis2-pretrained-stage2.json`，WT 真实输入结果为 `object_seed42.rrd`。日志与命令见 RUNBOOK。TRELLIS.2 使用随机条件和 64 个稀疏点，仅验证兼容性与数值，不代表完整图像生成质量或论文指标复现。

2026-10-12 进度复核通过：`pip check` 无冲突、CUDA 可用，6 个依赖仓库 HEAD 及递归子模块与锁定版本一致；37 个模型相关文件存在且大小匹配，两份本地 pipeline 配置引用齐全。物体推理、Stage 2、权重校验和辅助模型验证退出码均为 0。辅助模型报告为 `modelscope-aux-smoke.json`；复核报告为 `validation/progress-audit.json`。该次复核没有重复运行模型推理或大文件 SHA-256 校验。

2026-10-13 衔接验证：`validation/hybrid-smoke.json` 检查合成点图、体素注入及随机权重 shape/texture flow，未运行 mesh decoder；四种模式的路由由接口测试覆盖。真实输入结果为 `validation/hybrid-512/briefcase.glb` 和 `validation/hybrid-cascade/briefcase.glb`，同目录 JSON 保存坐标和运行参数。完整命令与文件重载检查见 RUNBOOK。本次验证能说明链路可运行，不等同于论文质量或指标复现。

同日结构/坐标复查：工作区 47 项测试通过（包括另行新增的 5 项 viewer 测试），修复后的随机 GPU flow 通过；文档代码示例与两份既有 GLB 的坐标回转检查通过，报告 `validation/coordinate-review.json`。本轮没有重跑完整预训练生成；默认旋转保持右手系，恢复相机坐标时必须同时撤销 GLB 轴旋转和 canonical 平移/缩放。

## 缺失数据、权重与后续工作

2026-10-13 批量入口与查看器已实现：模型按阶段复用，WT 缓存、配置隔离、断点续跑及 schema v1 产物索引可用；Viser 支持批量选择、横向/纵向比较和刷新。44 项相关测试通过，验证使用合成输入和模拟模型后端；两轮正式实验、GSO 渲染评测与 experiments.xlsx 汇总尚未执行，不能将此状态当成批量预训练结果验收。

- 原始数据 `raw/` 和处理数据 `processed/` 当前为空；验证使用内存随机张量和仓库自带示例，输入文件保持原样。
- WT 场景与动态权重、动态复现参考输出未下载，未进行论文指标复现。
- TRELLIS.2 主权重、结构解码器、DINOv3、RMBG-2.0 均已下载并分别验证。辅助权重改从 ModelScope 获取，原 HF 403 不再阻塞本地运行；WT hybrid 的 512 / 1024_cascade 已产出 GLB。
- 直接 1024 仅验证随机张量 flow，1536_cascade 仅验证接口路由；尚未运行这两个模式的完整预训练 GLB、多样本质量评估、场景/动态衔接或论文指标。独立 TRELLIS Stage 1 完整图像生成流程不在本次 hybrid 验证范围内。
