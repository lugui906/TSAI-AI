# AIM 2.0 — AI Intelligence Middleware

Chindows AI 底层核心基座，完全替代 Ollama，统一管控离线/云端大模型、系统自动化任务、内网远程 AI 服务。

## 架构

```
aim CLI → OpenCode 引擎 → AI Provider（云端/本地模型）
       → 内网远程服务（Token 鉴权）
       → 系统接口（硬件/进程/虚拟机）
```

## 目录结构

```
main.go                       入口：仅调用 cmd.Execute()
cmd/commands.go               CLI 命令注册与分发（run/newrun/model/serve/fix/debug/chat）
internal/
├── backend/                  Backend 接口 + CloudBackend(OpenAI 兼容) + VLLMBackend
│   └── manager.go          多后端注册/切换（⚠️ 当前 CLI 未真正接线）
├── core/scheduler.go         TaskQueue + SessionPool + 并行 Scheduler（骨架）
├── opencode/engine.go        PlanAgent(只读) / BuildAgent(--auto 全权限) / EngineManager
├── server/serve.go           内网 HTTP 服务（Token 鉴权）
├── storage/storage.go        AES-256-GCM 加密配置 + JSONL 操作日志
└── system/system.go          硬件信息 / 进程 / 虚拟机接口
scripts/
├── aim.service               systemd 单元
└── chindows-integrate.sh     安装/卸载/挂起/恢复钩子
```

## 核心运行流程

```
main.go → cmd.Execute()
  ├─ aim run "..."      → exec opencode run --auto --continue --format json → 流式输出
  ├─ aim newrun "..."   → 同上，但去掉 --continue（全新会话）
  ├─ aim model ...      → 透传 opencode models / providers
  ├─ aim serve          → storage.LoadConfig → HTTP 服务（/health /v1/chat /v1/models + Token）
  ├─ aim fix "问题"      → BuildAgent(fullAccess) → opencode run --auto
  ├─ aim debug [目标]   → 采集硬件信息 + PlanAgent 只读诊断 + 最近操作日志
  └─ aim chat           → 交互式 opencode run（继承 stdin/stdout/stderr）
```

## 已知半成品痕迹

- `internal/server` 的 `/v1/chat` 目前是 echo 桩，未真正对接后端推理。
- `internal/core` 的 scheduler worker 只置 running 状态，未实际执行任务。
- `internal/backend` 的 Manager 在 CLI 中未被使用（模型管理直接委托 opencode）。
- systemd 单元的 `ExecStop` 指向不存在的 `aim serve --stop`。

## 命令

| 命令 | 功能 |
|---|---|
| `aim run` | 通过 OpenCode 执行系统自动化任务（同一对话延续） |
| `aim newrun` | 开启新对话 |
| `aim model list` | 列出可用模型 |
| `aim model switch` | 切换 AI Provider（委托 `opencode providers`） |
| `aim model set-backend` | 配置 Provider |
| `aim serve` | 启动内网远程 AI 服务 |
| `aim serve token` | 查看已保存的远程 Token |
| `aim fix` | AI 辅助系统修复 |
| `aim debug` | 系统诊断 + 操作日志查询 |
| `aim chat` | 交互式 AI 对话（委托 OpenCode） |

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

### aim model

模型管理委托给 OpenCode：

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

操作日志存储在 `~/.local/share/aim/aim.log.jsonl`（JSONL 格式）。

## 构建

```bash
make build      # 编译
make install    # 安装到 /usr/local/bin
make test       # 运行测试
```

依赖：Go 1.22+，无需其他外部依赖。运行时依赖 `opencode` CLI。
