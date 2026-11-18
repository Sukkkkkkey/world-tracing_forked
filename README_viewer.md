# 查看器使用与端口维护

`viewer.py` 只读取已有结果，无需 GPU。所有启动、PID 和端口都以本次日志为准。

## 启动

在远程终端运行 OOD 正式集示例，保持该终端打开。需要断线后继续运行时使用专用 tmux 会话。

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing && source scripts/env.sh && \
python -uB viewer.py \
  --experiment "$WT_OUTPUT_ROOT/experiments/20261112-OOD-omni-v2-eval100" \
  --port 18094
```

启动日志给出 `Viewer` 地址、`Viewer PID` 和完整 `Remote access` 命令。**把 `Remote access` 命令复制到个人电脑的 PowerShell，保持运行，再打开打印的本机网址。**

该命令使用独立 SSH 连接，通过 `scripts/wait_viewer_exit.py --pid` 绑定当前查看器。结束查看器后，对应转发自动退出。每次重新启动都要使用新的 PID。可在 SSH 命令中增加 `-o ServerAliveInterval=15 -o ServerAliveCountMax=3`，便于连接失联后及时退出。

`--port` 默认 8080，0 表示自动选择。**指定端口被占用时会顺延，必须核对实际端口。**例如旧服务占用 18093，新进程可能实际监听 18094。关闭旧实例前先核对其 PID 和用途。

其他入口及 GSO R2、OOD 校准集的完整命令见 [主 README](README.md#评测指标)。

| 参数 | 用途 |
| --- | --- |
| `--experiment DIR` | 标准实验或 WT ablation 目录，按样本浏览 |
| `--evaluation DIR` | 显式关联评测目录，默认读取实验内 `baseline_evaluation.json` |
| `--evaluation-review DIR` | 合并通过版本和来源摘要核验的复核指标 |
| `--image FILE --points FILE` | 单样本模式，可加 `--mesh`、`--gt`、`--trellis`，与实验模式互斥 |
| `--quality full / balanced / fast` | 默认 full 保留全部点、网格和纹理；balanced 限制点数和纹理；fast 对大网格使用顶点预览 |

## 页面功能

- 公共控制区选择 Sample、方法、配置、seed 和 Exported GLB / Decoded mesh，支持上一张、下一张和 Refresh results。
- **三维查看**支持并排比较、单项 View、GT、旋转、平移、缩放和 Reset view。各结果保留自身尺度，仅居中排布，不进行 GT 配准。连接同一服务的浏览器共享样本选择。
- **表面颜色**保留模型贴图，WT 仅 layer-0 映射输入 RGB。深度模式覆盖表面颜色。GSO、OOD v1/v2 的 GT 从原始模型及材质加载纹理，资源缺失时提示并回退到评测几何。检查纹理用 full 或 balanced。
- **评测指标**按同一指标对比不同方法，显示本样本、同组数据集均值、差值和有效 n/N。分 Geometry、Visible depth、Input view & multi-view，支持 Surfel / Native、WT L0＋SSI 补充。均值按配置、seed、阶段及表示分别计算，运行中的分母仍取完整计划。
- **Refresh results**同步刷新结果索引及评测快照。Prepared 100% 表示服务器准备完成，浏览器传输和绘制可能仍在继续。

## 关闭

| 当前连接方式 | 完整关闭步骤 |
| --- | --- |
| 日志中的绑定 SSH 命令 | 点页面顶部 **退出可视化**，或在远程查看器终端按 Ctrl+C；SSH 随查看器退出，本机端口释放 |
| VS Code Ports | 先退出查看器，再在 Ports（端口）面板右键对应端口 → **Stop Forwarding Port**（停止转发端口） |
| 手动 `ssh -N -L ...` | 先退出查看器，再在运行该 SSH 的本机终端按 Ctrl+C |

关闭浏览器标签不会停止查看器。单独关闭转发也不会停止远程进程。页面按钮无法删除 VS Code 管理的转发记录，因此使用 VS Code 时需要上述第二步。若端口被自动恢复，检查该连接的自动转发设置，或改用独立的绑定 SSH 转发。

## 端口排查

先分别检查远程服务和本机转发。以下使用 18094，排查其他实例时替换为实际端口。

**远程服务，在个人电脑 PowerShell 执行**

```powershell
ssh ali-dsw 'cd /mnt/cpfs1/shuqiliu/code/world_tracing && ss -ltnp "sport = :18094"'
```

输出中的 `pid=...` 是实际监听进程。用查到的 PID 核对命令和工作目录。

```powershell
$viewerPid = Read-Host '输入 ss 查到的查看器 PID'
if ($viewerPid -notmatch "^[1-9][0-9]*$") { throw "PID 必须为正整数" }
ssh ali-dsw "cd /mnt/cpfs1/shuqiliu/code/world_tracing && ps -p $viewerPid -o pid,ppid,args && readlink /proc/$viewerPid/cwd"
```

页面无法打开时，在确认是本项目的目标 `viewer.py` 后单独执行以下关闭命令，再运行 `ss` 检查端口是否消失。

```powershell
ssh ali-dsw "cd /mnt/cpfs1/shuqiliu/code/world_tracing && kill -TERM $viewerPid"
```

**本机转发，在个人电脑 PowerShell 执行**

```powershell
$viewerListeners = Get-NetTCPConnection -State Listen -LocalPort 18094 -ErrorAction SilentlyContinue
$viewerListeners | Select-Object LocalAddress,LocalPort,OwningProcess
$viewerOwners = @($viewerListeners | Select-Object -ExpandProperty OwningProcess -Unique)
Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in $viewerOwners } |
  Select-Object ProcessId,Name,CommandLine | Format-List
```

- 远程无监听、本机仍监听：空转发，按上表关闭本机对应连接。
- 远程有监听、本机无监听：转发未建立，执行本次日志的 `Remote access` 命令。
- 本机归属 `Code.exe`：在 VS Code Ports 关闭该条目，保留编辑器进程。
- 本机归属 `ssh.exe`：核对命令确实转发目标端口后，在对应终端按 Ctrl+C。无终端时只停止这个已核对的 PID，避免结束其他 SSH 会话。
- 关闭完成的判据：远程 `ss` 无该端口条目，本机 `Get-NetTCPConnection` 无该监听。仅网页断开不能证明转发已释放。

完整参数可运行 `cd /mnt/cpfs1/shuqiliu/code/world_tracing && .venv/bin/python -B viewer.py --help`。
