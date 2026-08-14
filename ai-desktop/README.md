# ai-desktop — AI 桌面控制

GTK3 前端的 AI 桌面控制界面：输入指令 → 系统 `aim`（AIM 2.0 中间件）以**纯文本流**驱动 AI →
AI 通过 `tine`（AI 桌面驱动）在 GNOME Wayland 上操控桌面（读取 AT-SPI2 控件树、截图 OCR、点击控件、按键、剪贴板输入）。

## 架构

单文件 `main.py`（454 行）：

```
常量区        AIM_BIN=/usr/bin/aim、会话文件 /tmp/doubao-gtk-session.txt、超时常量
SYSTEM_PROMPT 强制铁律提示词（优先 tine tree 而非截图 / 合法控件 ID / 中文走 wl-copy+ctrl+v）
_run_opencode_plaintext()   aim newrun/run 子进程，逐字节流式读 stdout
send_message_plaintext()    封装回调
DoubaoWindow  GTK3 聊天视图 + 三色标签 + 自动滚动 + 新建/清屏/终止任务
_stall_monitor_callback()   5s 周期超时监控：无输出自动下发探测消息，再超时 killpg 终止
load/clear_session          会话持久化到 /tmp/doubao-gtk-session.txt
```

## 核心运行流程

```
用户输入 → _on_send()
  → 开 5s 超时监控定时器
  → 后台线程 send_message_plaintext():
      首条: aim newrun "SYSTEM_PROMPT + 指令"
      后续: aim run "指令"（读取会话 ID）
  → 逐字节流式 → GLib.idle_add 渲染
  → 超时无输出 → 下发【系统探测】→ 再超时 → killpg 终止进程组
```

AI 内部通过 `tine tree / screenshot --ocr / click / key` 完成桌面操作。

## 依赖

- Python：`PyGObject`（GTK3）
- 外部二进制：`aim`、`tine`（基于 AT-SPI2 的桌面驱动）、`wl-copy`（Wayland 剪贴板）、`setsid`

## 运行

```bash
sudo apt install python3-gi gir1.2-gtk-3.0
python3 main.py
```

需系统已安装 `aim` 与 `tine`。会话文件存于 `/tmp/doubao-gtk-session.txt`。
