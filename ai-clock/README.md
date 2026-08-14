# ai-clock — AI 定时任务管理器

轻量级 AI 定时任务管理器：按 `daily` / `hourly` / `interval:N` 三种周期，到期把预设 prompt 发给
`aim newrun` 执行，记录执行结果。提供 CLI 与 GTK3 图形界面，带 pytest 单元测试。

## 架构

```
clockai/
├── models.py       Task dataclass + should_run(now) 调度判定逻辑
├── storage.py      JSON 持久化 ~/.config/clockai/tasks.json
├── scheduler.py    execute_task(aim newrun) / run_scheduler(30s 扫描) / run_once
├── cli.py          argparse：add/list/run/delete/enable/disable/start/gui
├── gui.py          GTK3 界面：任务表 + 增删改 + 调度器启停
└── tests/          pytest 单测（should_run 各周期/边界、执行逻辑 mock）
```

## 核心运行流程

1. `clockai add --time 08:00 --period daily --prompt "..."` → 写入 tasks.json。
2. `clockai start` → 每 30s 扫描到期任务 → `should_run(now)` 命中则标记 `last_run` →
   后台线程 `execute_task`（`aim newrun <prompt>`，超时 3600s）→ 结果写入 `last_result`。
3. `clockai gui`：GTK 侧用 `GLib.timeout_add_seconds(30)` 做同样到期检查，另有「立即执行」按钮。

## 周期规则

| 周期 | 判定 |
|---|---|
| `daily HH:MM` | 目标时刻前后 60s 窗口内，且当天未跑过 |
| `hourly MM` | 每小时指定分钟 |
| `interval:N` | 距上次运行 ≥ N 分钟 |

## 运行

```bash
pip install -e .                 # 或 python -m clockai.cli

clockai add -t 08:00 -p daily -m "生成今日待办"     # 添加任务
clockai list                                       # 查看
clockai start [--once]                            # 启动调度器（--once 仅执行一次）
clockai run "立即执行一次"                         # 即时执行
clockai gui                                       # 图形界面
clockai delete/enable/disable <id>                # 管理

# 测试
pytest tests/
```

## 数据

任务持久化在 `~/.config/clockai/tasks.json`（无其他配置文件）。
