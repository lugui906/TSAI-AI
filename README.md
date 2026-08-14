# TSAI-AI

TSAI-OS 相关 AI 项目集合，全部为独立子项目，统一采用 `kebab-case` 命名：

| 目录 | 说明 |
|------|------|
| `ai-voice` | 本地 Whisper 语音识别 |
| `ai-hub` | Go 编写的 AIM 中枢服务 |
| `ai-notes` | AI 笔记应用 |
| `ai-gui` | AI GUI 工具 |
| `ai-client` | 多后端 AI 客户端 |
| `ai-clock` | AI 时钟 |
| `gesture-control` | 隔空手势控制 |
| `meeting-summary` | 会议概括（GTK） |
| `meeting-summary-cli` | 会议概括（守护进程） |
| `ai-assistant` | AI 快捷助手 |
| `ai-pc-manager` | AI PC 管理器 |
| `ai-file-chat` | Nautilus AI 文件聊天 |
| `kde-phone` | KDE 手机连接 |
| `ai-desktop` | AI 桌面控制 |
| `model-manager` | 模型管理器 |
| `web-ai-server` | Web AI 服务器 |
| `aim-knowledge` | AIM 知识库 |

各子项目均为独立工程，详见对应目录内的 README 或源码。

> 注意：`ai-voice/share/models/` 下的本地模型文件（约 1.1GB）已被 `.gitignore` 排除，不随仓库分发。
