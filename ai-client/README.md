# ai-client — 多后端 AI 桌面客户端

GTK3 多后端 AI 聊天桌面客户端，后端可在 **Ollama**（HTTP API）与 **AIM**（包装 `/bin/aim` CLI）间切换。
内置流式 Markdown 渲染（代码块/表格）、AI 生成代码一键运行、OCR、语音输入、联网搜索、会话保存/加载与工作区上下文注入。

## 架构

```
main.py                入口：Gtk.Application → MainWindow
config.py              配置读写 ~/.ai-assistant/config.json
ui/main_window.py      UI 全部逻辑（886 行）：内联实现 AIBackend / OllamaBackend / AimBackend
                       + render_markdown / ChatMessage / SettingsDialog / MainWindow
backends/              后端抽象包（base / ollama_backend / aim_backend）
                       ⚠️ 当前 UI 未 import 该包，内联版在 main_window.py 中
requirements.txt       锁文件（由 `pip-compile requirements.in` 生成）：requests、SpeechRecognition
```

## 核心运行流程

1. `python3 main.py` → `_init_backend()` 按配置选后端并刷新模型下拉。
2. 发送消息 → 后台线程 `backend.chat()` → 流式 chunk 重渲染消息气泡 Markdown。
3. 功能按钮：
   - **OCR**：`tesseract <图片>` 识别
   - **语音输入**：`arecord -d 5` 录音 + faster-whisper（`/usr/share/chinai2/models/tiny`）转写填入输入框
   - **联网搜索**：DuckDuckGo Instant Answer API，结果注入对话
   - **上传文件**：`backend.upload_file`（Ollama 附带分析请求 / AIM 把前 2000 字符塞进 newrun）
4. 新对话/保存/加载：`~/.ai-assistant/history/chat_<时间戳>.json`。

## 运行

```bash
# 系统依赖：apt install python3-gi gir1.2-gtk-3.0 portaudio19-dev
pip install -r requirements.txt
python3 main.py
```

## 配置

`~/.ai-assistant/config.json`：

| 字段 | 说明 |
|---|---|
| `backend` | `ollama` 或 `aim`（注意 config.py 默认 `ollama`，main_window.py 内 `DEFAULT_CONFIG` 默认 `aim`，二者不一致） |
| `ollama_url` | Ollama 服务地址 |
| `ollama_model` | 默认 `llama3` |
| `aim_model` | 默认 `opencode/deepseek-v4-flash-free` |
| `workspace` | 工作区目录（注入上下文） |
| `system_prompt` | 系统提示词 |
| `search_provider` | 搜索源 |

## 已知问题

- `backends/` 包与 `main_window.py` 内联版存在双份 backend 实现（重构残留）。
- `config.py` 与 `main_window.py` 的默认 `backend` 不一致。
- 语音模型路径硬编码 `/usr/share/chinai2/models/tiny`（旧安装路径）。
