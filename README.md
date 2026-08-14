# TSAI-AI

TSAI-OS 相关 AI 项目集合，全部为独立子项目，统一采用 `kebab-case` 命名
（`APS` 为产品名，按原名保留）。

## 许可证

本项目采用 **GPL-3.0** 许可证，详见 [LICENSE](LICENSE)。

> 本项目原为 TSAI-OS 系统内部组件，现已开源。代码中的部署路径已改为动态解析
> （相对路径 / `shutil.which` / 环境变量），便于在任意环境运行。

## 工程化

- **CI**：`.github/workflows/ci.yml` —— ruff lint、gitleaks 全历史 secret 扫描、
  pip-audit 依赖审计、ai-hub Go test/vet/golangci-lint、Python 单元测试。
- **pre-commit**：`.pre-commit-config.yaml`（尾随空格/EOF/大文件/ruff 检查）。
- **贡献指南**：[CONTRIBUTING.md](CONTRIBUTING.md) + [行为准则](CODE_OF_CONDUCT.md)
  + [PR 模板](.github/PULL_REQUEST_TEMPLATE.md)。
- **依赖锁定**：有依赖的 Python 子项目用 `requirements.in` + `pip-compile` 生成锁文件
  `requirements.txt`（APS / ai-client / meeting-summary*）。
- **模型清单**：`model-manager/models.yaml` + `scripts/download_models.py`
  （下载/校验 sha256）。

## 整体架构

```
                    ┌─────────────────────────────────────┐
                    │           AI 中枢 ai-hub (Go)        │
                    │  aim CLI → opencode/openclaw 引擎    │
                    │   + 内网远程服务 / 系统接口 / 加密配置  │
                    └───────────┬─────────────────────────┘
                                │  aim newrun / aim run / aim fix / aim debug
        ┌───────────┬───────────┼────────────┬──────────────┬─────────────┐
        ▼           ▼           ▼            ▼              ▼             ▼
  桌面客户端    文档/办公     语音/音频      Web 服务      系统管理       外部依赖
  ai-client    APS          ai-voice     web-ai-server  ai-pc-manager  opencode
  ai-gui       ai-notes     ai-clock     (Flask+OCR)    (GTK4)        openclaw
  ai-desktop   ai-file-chat              aim-knowledge  model-manager  ollama(回退)
  ai-assistant                            gesture-control(tine/OCR 桌面驱动)
  gesture-control（独立，离线本地推理，不走 AIM）
```

**统一 AI 后端**：绝大多数项目通过系统命令 `aim`（由 `ai-hub` 构建）完成 AI 调用，
`aim newrun` 开启新对话、`aim run` 延续对话。业务层不直接引入大模型。
**唯一例外**：`gesture-control` 是纯本地离线推理（OpenCV + TFLite），不依赖 AIM。

## 子项目索引

| 目录 | 说明 | 技术栈 | 详细文档 |
|------|------|--------|----------|
| `ai-hub` | AIM 2.0 AI 智能中枢（`aim` CLI 来源，opencode/openclaw 双引擎） | Go 1.22 | [README](ai-hub/README.md) |
| `APS` | AI 原生办公套件（对标 WPS：文字/表格/演示/PDF + AI 操作文档） | Python/GTK4 | [README](APS/README.md) |
| `ai-voice` | 本地 Whisper 语音助手（录音→VAD→转写→AIM→TTS） | Python/GTK3 | [README](ai-voice/README.md) |
| `ai-notes` | AI 笔记编辑器（md/docx/xlsx + AI 改写/翻译/总结） | Python/GTK4 | [README](ai-notes/README.md) |
| `ai-gui` | AIM 智能体管理器（角色对话 CLI + GUI） | Python/GTK3 | [README](ai-gui/README.md) |
| `ai-client` | 多后端 AI 桌面客户端（Ollama/AIM + 流式 Markdown） | Python/GTK3 | [README](ai-client/README.md) |
| `ai-clock` | AI 定时任务管理器（daily/hourly/interval） | Python/GTK3 | [README](ai-clock/README.md) |
| `gesture-control` | 隔空手势系统（离线手部识别，Wayland/systemd） | Python/OpenCV/TFLite | [README](gesture-control/README.md) |
| `meeting-summary` | 会议概括（GTK，parec 采集） | Python/GTK3 | [README](meeting-summary/README.md) |
| `meeting-summary-cli` | 会议概括守护进程（pw-record 采集） | Python/GTK3 | [README](meeting-summary-cli/README.md) |
| `ai-assistant` | 快捷键 AI 助手（Alt+S/T/D，截图 OCR + 桌面上下文） | Python/GTK4 | [README](ai-assistant/README.md) |
| `ai-pc-manager` | AI 电脑管家（系统监控 + AI 运维） | Python/GTK4 | [README](ai-pc-manager/README.md) |
| `ai-file-chat` | Nautilus 文件聊天（右键附件对话） | Python/GTK3 | [README](ai-file-chat/README.md) |
| `ai-desktop` | AI 桌面控制（tine 驱动 GNOME Wayland） | Python/GTK3 | [README](ai-desktop/README.md) |
| `model-manager` | 模型管理器（opencode.jsonc 可视化配置） | Python/GTK3 | [README](model-manager/README.md) |
| `web-ai-server` | Web AI 服务器（Flask 局域网聊天 + OCR + 定时） | Python/Flask | [README](web-ai-server/README.md) |
| `aim-knowledge` | AIM 知识库客户端（目录内文件问答） | Python/GTK3 | [README](aim-knowledge/README.md) |

## 运行依赖

本仓库所有 AI 项目都通过 `aim` CLI 与 AI 引擎通信，**核心依赖 `opencode`**：

| 引擎 | 依赖级别 | 说明 |
|---|---|---|
| `opencode` | **必需** | 默认 AI 引擎，`aim` 的所有推理/执行委托给它，必须安装并在 PATH 中 |
| `openclaw` | **可选** | 备选引擎，`aim oc` 一键切换后替代 opencode（见 ai-hub 文档） |

```bash
# 必需：安装 opencode（默认引擎）
curl -fsSL https://opencode.ai/install | bash

# 可选：切换到 openclaw 引擎（需先安装 openclaw）
aim oc            # 切到 openclaw
aim oc default    # 切回 opencode
```

## 推荐：直接下载 TSAI-OS 操作系统

本仓库原为 TSAI-OS 操作系统内置组件。**建议直接下载 TSAI-OS 镜像**，即可获得
开箱即用的更先进 AI 体验——所有依赖（opencode、模型、手势、桌面控制等）均已预装配置：

👉 **https://lugui906.github.io/chin**

## 共享基础设施

| 二进制 | 用途 | 依赖它的项目 |
|---|---|---|
| `aim` | AIM 2.0 AI 中间件（newrun/run/fix/debug） | ai-voice、ai-client、ai-desktop、ai-assistant、ai-file-chat、ai-clock、meeting-summary*、web-ai-server、aim-knowledge、ai-gui、ai-pc-manager、APS |
| `opencode` / `openclaw` | AI 引擎（aim 内部委托） | ai-hub、ai-notes、model-manager |
| `ollama` | 本地模型回退后端 | ai-client、ai-pc-manager |
| `tine` | AI 桌面驱动（AT-SPI2 控件操作） | ai-desktop、ai-assistant |
| `tesseract` | OCR（chi_sim+eng） | ai-assistant、ai-client |
| whisper 模型 | 本地语音转写（`ai-voice/share/models/`） | ai-voice、meeting-summary* |

## 部署约定

- 各子项目独立运行，源码形态见各目录。`aim`/`opencode` 等外部命令均通过 `shutil.which`
  或 PATH 动态解析；模型路径优先环境变量（`AIM_MODEL_ROOT`、`TSAI_MODEL_DIR`），
  其次仓库内相对路径，最后回退到原 TSAI-OS 部署路径。
- `gesture-control` 安装为 systemd 用户服务（`install.sh`）。
- 本地模型文件（约 1.1GB，`ai-voice/share/models/`）已被 `.gitignore` 排除，不随仓库分发；
  可设置 `AIM_MODEL_ROOT` 指向已有模型目录。
