# ai-assistant — 快捷键 AI 助手

常驻后台的 AI 快捷助手（GTK4）。注册全局快捷键，弹出/唤出窗口，支持**截图附件 + OCR**、
**读取桌面控件树作上下文**、与 `aim` 多轮对话。窗口关闭仅隐藏，保持后台驻留。

## 快捷键

| 快捷键 | 动作 |
|---|---|
| `Alt+S` | 唤醒 / 唤起窗口 |
| `Alt+T` | 区域截图并作为附件带入对话（自动 OCR） |
| `Alt+D` | 抓取当前桌面控件树（tine tree）作为上下文 |

## 架构

```
main.py       入口：解析 --hidden/--screenshot/--wake/--context
              命令优先走 Unix socket IPC 发给已驻留实例，失败才新起实例
ipc.py        AF_UNIX 单实例通信（XDG_RUNTIME_DIR → 回落 HOME/.cache → /tmp）
accel.py      GNOME Shell 全局快捷键（核心）：D-Bus GrabAccelerator + AcceleratorActivated
              技巧：RequestName 抢占 org.gnome.InitialSetup/Settings 白名单名绕过权限检查
backend.py    AimBackend：aim newrun/run 流式调用（支持 -f 附件），ANSI 剥离，忙碌互斥
capture.py    gnome-screenshot 区域截图 → tesseract(chi_sim+eng) OCR → 缓存目录
shortcuts.py  gsettings 备用注册方案 + /etc/xdg/autostart 自启动
ui.py         AssistantApp/AssistantWindow：GTK4 气泡聊天 + 附件缩略图 + 流式渲染
              do_context() 调 tine tree 抓无障碍树；handle_ipc() 分发命令
```

## 核心运行流程

```
main.py --screenshot/--wake/--context → 先 Client.send()（发给驻留实例）→ 成功即退出
  → 否则启动 AssistantApp
  do_startup: 若 org.gnome.Shell 存在 → 抢占白名单名 → 注册 <Alt>s/<Alt>t/<Alt>d
  快捷键触发 → _dispatch_ipc(cmd) → win.handle_ipc()
  聊天: AimBackend.send(prompt, files=[截图], new_conversation) → 流式渲染
```

## 运行

```bash
python3 main.py --hidden        # 后台驻留
python3 main.py --screenshot    # 快捷键动作（IPC 触发）
python3 main.py --wake
python3 main.py --context
python3 shortcuts.py /path/to/main.py   # gsettings 注册快捷键 + 自启动
```

## 依赖

- Python：`PyGObject`（GTK4/Gdk4/Gio/GLib）
- 外部二进制：`aim`、`tine`（`tine tree`）、`tesseract`（chi_sim+eng）、`gnome-screenshot`、`gsettings`
- 需 GNOME Shell（D-Bus Accelerator 接口）或 gsettings media-keys
