# aim-knowledge — AIM 知识库客户端

**AIM 知识库 GTK 客户端**：把知识文件放进 `~/AI知识库` 目录，即可通过图形界面与 AIM 对话。
首次发送走 `aim newrun`（新对话），后续走 `aim run`（延续上下文），提示词自动注入知识库目录位置，
引导 AIM 先查阅目录内文件再作答。**纯前端客户端**，无任何推理逻辑，全部委托 `aim` CLI。

## 架构

单文件应用（`aim_kb.py`，301 行，可执行）：

```
常量区        KB_DIR=~/AI知识库、KB_PROMPT（知识库位置注入模板）、字体/颜色
run_aim()     Popen([aim, mode, prompt]) 启动 AIM CLI
stream_aim_output()  逐行读 stdout，回调逐行上屏
AimKbApp      主类：创建目录 → _build_ui → 刷新文件列表
  _build_ui    HeaderBar(新对话/刷新) + 左栏文件列表 + 右栏聊天区
  _on_send     worker 线程：拼接 KB_PROMPT+问题 → run_aim → GLib 流式上屏
               首次后模式自动切换 newrun → run
  _on_new_conversation  重置模式为 newrun
```

## 运行

```bash
python3 aim_kb.py          # 或 ./aim_kb.py（需 GTK3 + aim CLI）
```

首次启动自动创建 `~/AI知识库`，把知识文件放进去后点「刷新」即可。

## 依赖

- `python3-gi`（GTK3）
- `aim` CLI（AIM 2.0 中间件，见 ai-hub）
- 纯标准库，无需 pip 安装
