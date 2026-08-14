# web-ai-server — Web AI 服务器

Flask 局域网 AI 聊天服务：浏览器访问即用（自动打开浏览器），每条消息通过 `aim newrun/run` 执行，
**NDJSON 流式**回传；带图片 OCR（RapidOCR）、定时发送（后台调度线程）、每会话独立工作目录。

## 架构

```
server.py            唯一后端
├── JSON 持久化      load_json/save_json（.tmp + os.replace 原子写，线程锁）
│                    data/sessions.json + data/schedules.json
├── 工作目录         session_workdir(sid) / get_workdir(sid)（data/workdir/，会话可覆盖）
├── OCR              RapidOCR 单例，POST 图片 → 文本
├── run_aim()        生成器：Popen aim → 逐行 yield NDJSON chunk
│                    超时 kill / 非零退出 / 异常 → error 事件
├── scheduler_loop() 每 5s 扫描 schedules，到点 aim newrun/run，结果回填会话
└── HTTP 路由        （见下表）
templates/chat.html  单页前端（内联 CSS/JS）：会话侧栏 + 聊天流 + OCR + 定时弹窗
```

## HTTP API

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/` | 渲染 `chat.html` |
| GET | `/api/sessions` | 会话列表 |
| GET | `/api/history?session_id=` | 单会话历史/工作目录 |
| DELETE | `/api/session?session_id=` | 删除会话 |
| PUT | `/api/session/workdir` | 设置/清除会话工作目录 |
| GET | `/api/schedules?session_id=` | 定时任务列表 |
| POST | `/api/schedule` | 创建定时任务 |
| DELETE | `/api/schedule?schedule_id=` | 删除定时任务 |
| POST | `/api/chat` | 延续会话，响应 NDJSON 流 |
| POST | `/api/new` | 新建会话，响应 NDJSON 流 |
| POST | `/api/ocr` | 图片 OCR（multipart `image`）→ `{text}` |

## 运行

```bash
pip install flask rapidocr
python3 server.py                 # 默认 0.0.0.0:5001，自动打开浏览器
python3 server.py 127.0.0.1 8080  # 指定 host/port
```

局域网其他设备访问 `http://<ip>:5001`。

## 依赖

- `flask`、`rapidocr`（含 onnxruntime 等传递依赖，缺装会启动失败）
- 运行时 `/usr/bin/aim`（`aim newrun`/`aim run`）
