# ai-gui — AIM 智能体管理器

「智能体（角色扮演）对话」工具集，含两层：

1. **`aim` Python 包** — 独立可安装的 CLI/GTK3 程序：管理 AI 角色人设、维护对话记录、
   直连 OpenAI 兼容 API 聊天。
2. **`ai-gui.py`** — GTK3 聊天前端，调用系统 `/bin/aim`（Go 中间件）对话，复用 `aim` 包的智能体存储。

## 架构

```
setup.py             打包 aim 包（console_script: aim=aim.cli:main，仅依赖 httpx）
ai-gui.py            顶层 GTK3 应用：Notebook「角色」页 +「对话」页
                     对话交给 /bin/aim newrun/run，从 stdout 抓会话 ID
aim/
├── cli.py           CLI 分发：newrun / run / agent / list / config / gui
├── agent.py         智能体 JSON CRUD + build_system_prompt()
├── conversation.py  会话 JSON CRUD（uuid 短 id + add_message）
├── llm.py           httpx 调 OpenAI 兼容 /chat/completions，SSE 流式解析
├── config.py        配置目录 ~/.config/aim；环境变量覆盖 API Key/Base/Model
└── gui.py           GTK3 界面（角色/会话双 TreeView + 聊天区，流式上屏）
```

## 核心运行流程

- **CLI 新会话**：`aim newrun bob` → 建会话 → 组装 system prompt → `input()` 循环 → `chat()` 流式 → 每条消息落盘。
- **CLI 续聊**：`aim run <id>` → 回放历史 → 继续循环。
- **`ai-gui.py`**：角色页存人设 JSON → 对话页后台线程执行 `/bin/aim newrun/run` → 抓取 ID 续聊。

> ⚠️ 注意区分：`ai-gui.py` 用的是系统 Go `aim`（AIM 2.0 中间件，见 ai-hub），
> 而 `aim` Python 包自己的 `chat()` 走 OpenAI 兼容 HTTP——两条不同的 LLM 通路，
> 仅共享同一智能体存储目录 `~/.config/aim/agents/`。

## 运行

```bash
# 安装 CLI
pip install -e .                 # 生成 aim 命令

# CLI 用法
aim help
aim newrun <agent>               # 新会话
aim run [conv_id]                # 续聊
aim agent create <name>          # 创建角色
aim list                         # 列出会话
aim config [key val]             # 查看/设置配置

# GUI
aim gui                          # 或 python -m aim
python3 ai-gui.py                # 独立前端（用系统 /bin/aim）
```

## 配置

`~/.config/aim/config.json`：`api_key`、`api_base`、`model`
（可用 `aim config` 设置，环境变量 `AIM_API_KEY`/`AIM_API_BASE`/`AIM_MODEL` 覆盖）。
智能体 JSON 与会话 JSON 均存于该目录下。
