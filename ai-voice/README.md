# ai-voice — 本地 Whisper 语音助手

全本地、CPU 运行的「语音版 AI 助手」：**录音 → VAD 端点检测 → 本地 Whisper 转写 → `aim run` 得到回复 → TTS 语音播报**。TTS 播放期间自动静音麦克风，防止回声进入下一次录音。

## 架构

单文件应用（`main.py`，约 520 行），内部模块划分：

```
main.py
├── 模型选择       在 small / faster-small / base 三个候选目录中找 model.bin，
│                  用 faster-whisper 加载（CPU + int8 + 仅本地文件）
├── MicrophoneManager   arecord 子进程采集 + WebRTC VAD 端点检测
│                       连续 6 语音帧判定"开始说话"，连续静音判定"结束"
├── mute_mic()      PipeWire(wpctl/pw-cli) → 回退 amixer 静音/恢复麦克风
├── speak()         后台线程：edge-tts(中文女声) → ffmpeg 转 wav → aplay 播放
│                  失败回退 espeak-ng；播放期间锁麦克风 + 冷却 2s
├── AimWindow       GTK3 只读窗口，queue + GLib 轮询流式显示 aim 输出
├── run_aim()       调用 `aim run <prompt>`，逐行流式写入窗口
└── audio_loop()    主循环：等待语音 → record() → transcribe(zh) → 过滤 → aim run
```

## 核心运行流程

```
Gtk.main() 期间后台线程持续循环：
  等待说话 → VAD 录音(≤30s) → faster-whisper 转写(中文, beam=5)
  → 过滤空文本 / 黑名单误识别词 / TTS 回声
  → aim run "<语音文本>"（期间麦克风锁定，流式显示）
  → edge-tts → aplay 播放 → 静默 2s → 解锁麦克风 → 回到等待
```

## 依赖

Python：`numpy`、`webrtcvad`、`faster-whisper`、`edge-tts`、`PyGObject`(GTK3)

系统命令：`arecord`/`aplay`（alsa-utils）、`ffmpeg`、`espeak-ng`、`pw-cli`/`wpctl`（或 `amixer`）、`aim`

模型文件（约 1.1GB，**已被 .gitignore 排除**，需按部署路径放置）：

- `share/models/faster-small/model.bin`（优先使用，484MB）
- `share/models/small/ggml-small.bin`（488MB）/ `base/ggml-base.bin`（148MB）

## 运行

```bash
# 仓库内直接运行（需先修正 MODEL_ROOT 指向本机模型目录）
python3 main.py
```

## 关键配置

无配置文件，全部为 `main.py` 顶部常量：

| 常量 | 说明 |
|---|---|
| `MODEL_ROOT` | 模型根目录（优先环境变量 `AIM_MODEL_ROOT` → 仓库内 `share/models` → 回退旧部署路径） |
| `SAMPLE_RATE / CHUNK` | 16000Hz / 960 字节块 |
| `VAD_MODE / 帧阈值` | VAD 灵敏度与起止判定帧数 |
| `MIN/MAX_RECORD_SEC` | 录音长度限制（0.8s–30s） |
| `TTS_COOLDOWN` | 播报后冷却 2s |
| `BLOCKED_PHRASES` | 误识别黑名单词过滤 |

> 提示：`bin/voice-assistant` 启动脚本已改为相对仓库根解析；模型路径支持
> 环境变量 `AIM_MODEL_ROOT` 覆盖，仓库内直接运行 `python3 main.py` 即可。
