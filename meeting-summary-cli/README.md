# meeting-summary-cli — 会议概括（守护进程）

TSAI-OS「在线会议概括」AIM 中枢子系统的守护进程变体，与 `meeting-summary` **功能完全相同**：
PipeWire 采集 → 整段 wav → `aim newrun/run` → Markdown 纪要 + 桌面通知。
唯一功能性差异在**音频采集层**：本版本使用 **`pw-record`**（PipeWire 原生），
`meeting-summary` 使用 `parec`（PulseAudio）。

## 与 meeting-summary 的差异

| 差异点 | meeting-summary | meeting-summary-cli |
|---|---|---|
| 采集命令 | `parec`（PulseAudio） | `pw-record`（PipeWire 原生） |
| 参数 | `--format s16le` | `--format s16` + `--volume 1.0` |
| GTK 前端 | 录制前清理旧 wav/txt + 录制提示语 | 无清理/提示逻辑 |
| 其余模块 | 相同 | 相同（main/aim_client/scheduler/transcribe/vad/persistence/notify 逐字节一致） |

> 背景：本机 `pw-record` 的 `--target` 解析 `.monitor` 节点会错抓到麦克风。
> meeting-summary 用 parec 规避该问题；本版本改用 pw-record 并接受该行为。

## 架构

```
main.py             CLI 守护进程入口（--source internal|mic / --self-test）
app.py              GTK3 图形界面
aim_client/client.py AIM CLI 薄封装（newrun/run，超时 1800s）
meeting/
├── recorder.py     pw-record 采集（--format s16 --rate 16000 --channels 1）
├── vad.py          webrtcvad 语音分段（当前流程未启用）
├── scheduler.py    载荷组装：首段 newrun、后续 run 增量
├── transcribe.py   pywhispercpp 本地转写 + 音量归一化 + 并行分块
├── persistence.py  纪要落盘 .md
└── notify.py       notify-send 桌面通知（带节流）
```

## 运行

```bash
python3 main.py --source internal     # 采集系统内录，Ctrl+C 停止
python3 main.py --source mic          # 采集麦克风
python3 main.py --self-test           # 合成音频自检
python3 app.py                        # GTK 界面
```

## 依赖

`pip install -r requirements.txt`（numpy、webrtcvad；转写需另装 `pywhispercpp`）。
系统依赖：`pipewire`/`pw-record`、GTK3、`notify-send`、`aim` CLI、本地 whisper 模型。
