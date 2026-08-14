# ai-pc-manager — AI 电脑管家

基于 GTK4 的系统管理 + AI 优化桌面应用。把传统系统工具（进程管理、磁盘清理、启动项、网络/内存监控）
与 AI 自动运维能力（系统优化、故障诊断、性能分析、安全扫描、驱动更新、软件管理、磁盘整理、智能问答）
集成在一个侧边栏 GUI 中。AI 动作由 `aim` CLI 执行，命令不可用时自动回退本地 `ollama`（默认 `llama3`）。

## 架构

```
ai_pc_manager.py   全部核心代码（1968 行，三层）
main.py            入口：转调 ai_pc_manager.main()
start.sh           启动脚本
run_optimize.py    无 GUI 调试脚本（直接调用 ai_system_optimize）
requirements.txt   依赖清单

三层结构：
├── SystemInfo     纯静态方法封装 psutil：CPU/内存/磁盘/温度/进程/网络/用户信息
├── AIManager      AI 与命令执行层：
│                    run_aim_command / run_command_with_live_output
│                    _fallback_to_ollama（aim 缺失时自动改用 ollama llama3）
│                    10 个"AI xxx"运维动作（中文 prompt + 逐条 sudo 命令）
│                    问答/修复(aim fix)/诊断(aim debug)/清理磁盘(aim run)
│                    Ollama 模型管理（list/pull/run/delete）
└── GTK4 UI       12 个面板类：
                    Dashboard / SystemInfo / ProcessManager / DiskCleanup / Startup
                    NetworkMonitor / Memory / Interface / AIModel / Toolbox
                    AIFunctions / LogOutput + MainWindow 侧边栏
```

## 核心运行流程

```
start.sh → python3 main.py → Gtk.Application
  → MainWindow（侧边栏 + 面板容器）→ DashboardPanel（2s 刷新统计）
  → 用户点按钮 → AIManager.xxx(callback, log_callback)
  → 后台线程: aim run <prompt> / 逐条执行 sudo 命令序列
  → GLib.idle_add 回主线程 → 写入 AI 输出区 / 日志面板
```

## 运行

```bash
pip install -r requirements.txt      # psutil / pycairo / PyGObject(GTK4)
./start.sh                           # 或 python3 main.py
```

AI 功能依赖 `aim` CLI（否则回退 ollama llama3）；多数优化命令需要 root（`sudo`）。

## 已知问题

- `StartupPanel` 的启动项数据是硬编码示例列表，启/禁用按钮未接实际逻辑。
- `run_optimize.py` 硬编码了旧机器路径 `/home/show/mgr`，已过时。
