# 2026-11-06 查看器恢复调试

> 本文记录 2026-11-06 的分支调试过程。2026-11-07 已将修复 `57565ee` 合入 main，生成 `089b8a0`。服务已迁到主项目，旧工作目录的运行记录已归档并完成移除。当前启动方式见 [运行手册](/mnt/cpfs1/shuqiliu/code/world_tracing/RUNBOOK.md#查看器服务与合入验收)。

2026-11-07 补充验收为全套测试 151 项通过、真实产物加载 112 项通过，覆盖 R2 内存修复样本与 3.06 GB 解码网格。报告位于输出 `validation/maintenance-20261107/viewer-geometry.json`。下文中的 90 项检查和旧工作目录命令保留当时的记录。

本次使用已恢复产物调试交互式查看器。实验推理与评价继续在原工作目录执行。

## 分支与合入边界

- 原工作目录：`/mnt/cpfs1/shuqiliu/code/world_tracing`，保留 `main` 和原有未提交改动。
- 独立工作目录：`/mnt/cpfs1/shuqiliu/code/world_tracing-viewer`。
- 分支：`fix/viewer-recovery`。
- 原始 HEAD：`b0327d0cec60a9ec8f7314186af9b3918abd7b16`。
- 现状基线：`7d76cc0681d07ad45a4b7353a4dd611168cf00a4`，纳入当时 18 个已跟踪文件改动及 169 个未跟踪源码/配置/文档文件。
- 基线与查看器修复分开提交。R2 恢复完成、恢复代码形成提交后，优先只 cherry-pick 基线之后的查看器修复提交；整体合并此分支时需审阅恢复脚本等快照文件的冲突。
- 本次提交使用本机已有 Git 署名，仅创建本地提交。

## 修复

1. 画布原先使用长字符串、左上锚点和固定屏幕字号，六组结果的名称重叠。改为居中、多行标签；字号随场景缩放，网格行距容纳标签高度。完整坐标及来源信息仍保留在 View 列表。
2. 默认取景原先只按包围盒对角线估计距离。现在使用当前客户端视场角、宽高比以及包含标签的显示边界，保留边缘余量；只调整展示相机与布局，原几何尺度不变。改变窗口大小后可用 Reset view 重新取景。
3. Previous/Next 回调由 Viser 线程池并发执行。原有读—递增—写操作未加锁；新增案例稳定复现两次 Next 只从 a 前进到 b。现与刷新共用锁，使两次前进得到 c。
4. 启动提示中的 SSH 命令改用已配置别名 `ali-dsw`。

## 验证

- 原有查看器测试：28 passed。
- 新增 6 组不同视场角/宽高比的投影边界检查，以及 1 项并发翻页回归；最终 35 passed（39.80 s）。
- 真实产物检查：90/90 passed，包括 P0 的 50 个 run 与 10 个带纹理 GT、R1 三个代表样本的当时可用 14 个 run、15 个裁剪/背景对照、1 个最大解码网格预览。
- 最大解码网格：677,513,177 bytes（646.1 MiB），fast 模式保留 20,000 个预览点，准备耗时 4.482 s；核验进程峰值 RSS 3592 MiB。
- 浏览器检查：P0 六组 full/表面颜色比较、连续样本切换、fast/深度显示、GT 开关；未观察到浏览器 error 日志。
- Viser 的窄窗口使用移动端折叠面板；桌面宽度下侧栏停靠和左上角视角按钮正常。这是所安装 Viser 的布局行为。
- R2 不在本次真实产物验收范围内；恢复完成后用同样入口追加检查。

核验报告：

```text
/mnt/oss1/lemonade_factory/SYNC/shuqiliu/output/world_tracing/validation/viewer-debug-20261106/20261106T030744Z/geometry-check.json
```

活动日志、核验脚本与 PID 位于新工作区 `.runtime/`；本机连接记录为 `logs/20261106-viewer-debug.json`。几何核验脚本读取已有产物，检查前后文件大小和修改时间一致；验证报告写入独立输出目录。

## 2026-11-06 的环境与启动记录

```bash
cd /mnt/cpfs1/shuqiliu/code/world_tracing-viewer
export WT_ENV_ROOT=/mnt/cpfs1/shuqiliu/code/world_tracing/.venv
export WT_TRELLIS2_ROOT=/mnt/cpfs1/shuqiliu/code/world_tracing/dependencies/TRELLIS.2
source scripts/env.sh
python -B -m pytest tests/test_viewer.py tests/test_viewer_mesh.py tests/test_viewer_ablation.py tests/test_viewer_layout.py -q
python viewer.py --experiment "$WT_OUTPUT_ROOT/experiments/20261013-P0-gso-pilot-v1" --port 18090
```

在本机通过 `ssh -N -L 127.0.0.1:18090:127.0.0.1:18090 ali-dsw` 转发后访问 `http://127.0.0.1:18090`。本次服务使用独立 tmux socket `wt-viewer-debug`、会话 `p0`。如已有服务，先核对本机记录与远程 PID，复用现有端口。
