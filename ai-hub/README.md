# AIM 2.0 — AI Intelligence Middleware

Chindows AI 底层核心基座，完全替代 Ollama，统一管控离线/云端大模型、系统自动化任务、内网远程 AI 服务。

## 架构

```
aim CLI → AI 引擎（OpenCode / OpenClaw）→ AI Provider（云端/本地模型）
       → 内网远程服务（Token 鉴权）
       → 系统接口（硬件/进程/虚拟机）
```

## 目录结构

```
main.go                       入口：仅调用 cmd.Execute()
cmd/
├── commands.go               CLI 命令注册与分发（run/newrun/model/serve/fix/debug/chat）
├── oc.go                     aim oc：切换默认 AI 引擎（opencode ↔ openclaw，持久化）
└── apikey.go                 aim apikey：管理 Provider API Key（加密存储）
internal/
├── backend/                  Backend 接口 + CloudBackend(OpenAI 兼容) + VLLMBackend
│   └── manager.go           多后端注册/切换（⚠️ 当前 CLI 未真正接线）
├── core/scheduler.go         TaskQueue + SessionPool + 并行 Scheduler（骨架）
├── opencode/
│   ├── engine.go             PlanAgent(只读) / BuildAgent(--auto 全权限) / EngineManager
│   └── adapter.go            双引擎命令/输出自动适配（opencode ↔ openclaw）
├── server/serve.go           内网 HTTP 服务（Token 鉴权）
├── storage/storage.go        AES-256-GCM 加密配置 + JSONL 操作日志
└── system/system.go          硬件信息 / 进程 / 虚拟机接口
scripts/
├── aim.service               systemd 单元
└── chindows-integrate.sh     安装/卸载/挂起/恢复钩子
```

## 命令

| 命令 | 功能 |
|---|---|
| `aim run` | 通过 AI 引擎执行系统自动化任务（同一对话延续） |
| `aim newrun` | 开启新对话 |
| `aim model list` | 列出可用模型 |
| `aim model switch` | 切换 AI Provider |
| `aim model set-backend` | 配置 Provider |
| `aim serve` | 启动内网远程 AI 服务 |
| `aim serve token` | 查看已保存的远程 Token |
| `aim fix` | AI 辅助系统修复 |
| `aim debug` | 系统诊断 + 操作日志查询 |
| `aim chat` | 交互式 AI 对话 |
| `aim oc` | 切换默认 AI 引擎为 OpenClaw（持久化） |
| `aim apikey` | 管理 Provider API Key |

## 核心运行流程

```
main.go → cmd.Execute()
  ├─ aim run "..."      → exec 引擎 run --auto --continue --format json → 流式输出
  ├─ aim newrun "..."   → 同上，但去掉 --continue（全新会话）
  ├─ aim model ...      → 透传引擎 models / providers
  ├─ aim serve          → storage.LoadConfig → HTTP 服务（/health /v1/chat /v1/models + Token）
  ├─ aim fix "问题"      → BuildAgent(fullAccess) → 引擎 run --auto
  ├─ aim debug [目标]   → 采集硬件信息 + PlanAgent 只读诊断 + 最近操作日志
  ├─ aim oc status      → 读取配置中的当前默认引擎
  ├─ aim apikey list    → 列出已配置的 Provider Key（掩码显示）
  └─ aim chat           → 交互式引擎 run（继承 stdin/stdout/stderr）
```

### aim run

`aim run` 是上层应用的统一调用入口，绑定的 Build 代理拥有**完整系统权限**，**无拦截、无弹窗、无二次确认**。

```bash
aim run "帮我修复这个报错"
aim run "检查系统磁盘使用情况"
aim run "记住我叫小明"
aim run "我叫什么"        # 同一对话，记得上文
```

### aim newrun

与 `aim run` 功能相同，但每次都开启**全新对话**，不共享上下文。

```bash
aim newrun "帮我分析这个问题"
```

### aim serve

启动内网远程 AI 服务，局域网其他设备可连接。**必须携带 Token 鉴权**。

```bash
# 启动（自动生成 token）
aim serve --port 21526

# 指定 token
aim serve --port 21526 --token my-secret-token

# 查看已保存的 token
aim serve token
```

远程设备连接：

```bash
curl -H "Authorization: Bearer <token>" http://<server-ip>:21526/v1/chat \
  -d '{"model":"default","prompt":"hello"}'
```

### aim oc

`aim oc` 将默认 AI 引擎从 `opencode` 切换到 `openclaw`，设置会持久化保存，
之后所有命令（`aim run`、`aim newrun`、`aim fix`、`aim debug`、`aim chat`、`aim model` 等）都自动改用 OpenClaw。

```bash
aim oc            # 切换默认引擎为 openclaw
aim oc status     # 查看当前默认引擎
aim oc default    # 恢复默认引擎为 opencode
```

两种引擎的命令与输出均自动适配：

- `aim run` / `aim newrun`：`opencode run` ↔ `openclaw agent --local`
- `aim fix` / `aim debug`：内部 Build/Plan 代理同样切换
- `aim chat`：`opencode run`（交互）↔ `openclaw chat`
- `aim model list` / `aim model switch`：分别映射到两引擎的模型命令

### aim apikey

管理各 AI Provider 的 API Key（以环境变量方式传给引擎，加密存储）：

```bash
aim apikey set <provider> <key>   # 设置某 Provider 的 Key
aim apikey list                   # 列出已配置的 Key（掩码显示）
aim apikey remove <provider>      # 删除某 Provider 的 Key
```

### aim model

模型管理委托给 AI 引擎：

```bash
aim model list                    # 列出所有可用模型
aim model switch                  # 切换 Provider（交互式）
```

### aim fix / aim debug

系统诊断与修复：

```bash
aim fix "系统风扇声音异常"
aim debug                         # 系统诊断 + 最近操作日志
aim debug "网络连接问题"
```

## 配置

配置文件 AES 加密存储在 `~/.config/aim/config.json.enc`：

- API 密钥
- 远程 Token
- 服务端口
- 默认 AI 引擎（opencode / openclaw）
- Provider API Keys

操作日志存储在 `~/.local/share/aim/aim.log.jsonl`（JSONL 格式）。

## 构建

```bash
make build      # 编译
make install    # 安装到 /usr/local/bin
make test       # 运行测试
```

依赖：Go 1.22+，无需其他外部依赖。

### 运行时依赖

- **必需：`opencode`** —— 默认 AI 引擎，`aim` 的所有推理/执行委托给它，必须安装并在 PATH 中：
  ```bash
  curl -fsSL https://opencode.ai/install | bash
  ```
- **可选：`openclaw`** —— 备选引擎，通过 `aim oc` 一键切换（见上文）。

### 推荐：直接下载 TSAI-OS

本仓库原为 TSAI-OS 操作系统内置组件，建议直接下载 **TSAI-OS 镜像**获得开箱即用的
AI 体验（依赖与模型均已预装）：👉 **https://lugui906.github.io/chin**

## 许可证

GPL-3.0，详见根目录 [LICENSE](../../LICENSE)。

## 已知半成品痕迹

- `internal/server` 的 `/v1/chat` 目前是 echo 桩，未真正对接后端推理。
- `internal/core` 的 scheduler worker 只置 running 状态，未实际执行任务。
- `internal/backend` 的 Manager 在 CLI 中未被使用（模型管理直接委托引擎）。
- systemd 单元的 `ExecStop` 指向不存在的 `aim serve --stop`。
