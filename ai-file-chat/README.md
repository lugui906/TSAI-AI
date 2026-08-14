# ai-file-chat — Nautilus 文件聊天

在 Nautilus 文件管理器中集成的 AI 对话工具：从**文件/文件夹右键菜单**启动一个停靠屏幕右侧的
「AI 对话」浮动窗，把选中的文件/目录路径作为**附件**随问题一并交给 `aim` 处理。
支持单实例（再次传路径时通过 Unix socket 把新路径追加为附件）。

## 架构

```
ai-file-chat.py          GTK3 应用本体
├── AIChatWindow         HeaderBar(+附件/新对话) + 附件 chip 列表 + 聊天区 + 输入框
│                        Ctrl+Enter 发送 / 停止按钮
├── _start_aim(prompt)   首条 aim newrun，后续 aim run；start_new_session 起进程
│                        双读线程(stdout/stderr) → queue → GLib 60ms 轮询流式渲染
│                        "停止"用 killpg(9) 杀整个进程组
└── 单实例               Unix socket /tmp/ai-file-chat.sock，新路径追加为附件 + 置顶

nautilus-ai-chat-ext.py  Nautilus 扩展（MenuProvider）
├── get_file_items()      文件右键 → "AI 对话（附带选中项）"
└── get_background_items() 目录空白右键 → "对当前目录 AI 对话"
```

## 核心运行流程

```
[Nautilus] 右键 → Popen ai-file-chat <paths...>
  → 已有实例则发路径 → 退出
  → 否则 AIChatWindow → 建 socket 监听 → 用户提问
  → _start_aim(): 首条 aim newrun / 之后 aim run
  → stdout 逐行入队列 → 流式写入聊天区
```

## 运行

```bash
python3 ai-file-chat.py [路径...]     # 直接启动（可带附件路径）
```

Nautilus 右键入口：

```bash
# 1) 把脚本链接为系统命令
sudo ln -s $(pwd)/ai-file-chat.py /usr/local/bin/ai-file-chat

# 2) 安装 Nautilus 扩展
cp nautilus-ai-chat-ext.py ~/.local/share/nautilus-python/extensions/
nautilus -q     # 重启 Nautilus
```

## 依赖

- `python3-gi` + `gir1.2-gtk-3.0`（GTK3）；Nautilus 扩展需 `python3-nautilus`
- 运行时依赖 `/usr/bin/aim`
