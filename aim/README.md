# AIM 2.0 — AI Intelligence Middleware

Chindows AI 底层核心基座，完全替代 Ollama，统一管控离线/云端大模型、系统自动化任务、内网远程 AI 服务。

## 架构

```
aim CLI → OpenCode 引擎 → AI Provider（云端/本地模型）
       → 内网远程服务（Token 鉴权）
       → 系统接口（硬件/进程/虚拟机）
```

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
