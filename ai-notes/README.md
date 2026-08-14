# ai-notes — AI 笔记编辑器

基于 GTK4 的笔记编辑器：打开/保存 **Markdown、Word(docx)、Excel(xlsx)、TXT**，内嵌 AI 助手侧栏，
对选中文本或全文执行**改写/翻译/续写/总结**等操作，通过 `opencode run --format json` 流式调用 LLM，
结果可一键回填到文档中。

## 架构

```
main          入口：Gtk.Application → MainWindow
window.py     MainWindow：HeaderBar + 左侧文件浏览器 + 中间编辑器 + 右侧 AI 面板
              Ctrl+O/Ctrl+S、选区跟踪、接收 AI 面板的替换信号写回文档
editor.py     Document 抽象基类（按扩展名自动注册）
              MdDocument / TextDocument / DocxDocument / XlsxDocument
              EditorPane：TextView + 打开/保存
ai_panel.py   AiPanel：聊天消息流 + ACTION_PROMPTS 动作模板 + 快捷按钮
              自定义信号 insert-text / replace-text / replace-full-text
aim_engine.py AimSession：包装 `opencode run --format json`，解析 JSON 事件流
              捕获 sessionID 保持会话连续；会话持久化到 ~/.ainote/
page.py       ConversationPage：独立聊天页（备用/遗留，当前未启用）
```

## 核心运行流程

1. `./main` 启动 → 打开文件 → `EditorPane.open_file()` 按后缀选 Document 读入。
2. 编辑器选中文本 / 内容变化 → 同步推送给 `AiPanel` 作为上下文。
3. 点快捷按钮或发送消息 → 拼出「文档全文 + 指令」→ `AimSession.send()`。
4. 后台线程跑 `opencode run --format json`，解析逐行 JSON 事件流式更新 UI。
5. 完成后按模式 emit `replace-text`（替换选区）或 `replace-full-text`（替换全文）写回文档。

## 依赖

- Python：`PyGObject`(GTK4/GDK4/GLib/Gio/Pango)、`python-docx`（懒加载）、`openpyxl`（懒加载）
- 外部命令：`opencode`（LLM 后端）
- 数据目录：`~/.ainote`（启动自动创建，存放会话历史）

## 运行

```bash
./main        # 在 ai-notes/ 目录下，需 GTK4
```

## 说明

- AI 动作模板集中在 `ai_panel.py` 的 `ACTION_PROMPTS`（改写/翻译中英/续写/总结/扩写/简化）。
- `aim_engine.py` 从 `step_start` 事件捕获 `sessionID`，保证同一窗口内的多轮对话上下文连续。
