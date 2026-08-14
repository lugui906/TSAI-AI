# TSAI-OS V12｜在线会议概括模块

Azure Alignment Manager (AIM) 中枢子系统 —— 在线会议概括。业务层仅负责数据采集、
预处理、载荷组装、结果落盘与 UI 通知；所有语音转写、说话人区分、摘要、行动点提取
均交由 AIM 中枢（`aim newrun` / `aim run`）执行，业务代码不引入任何大模型。

## 架构

```
PipeWire 采集 → VAD 分段 → AIM(newrun/run) → 纪要 .md + 桌面通知
```

- `app.py`        GTK3 图形界面入口
- `main.py`       终端守护进程入口（含 `--self-test` 自检）
- `aim_client/`   AIM CLI 交互层（NEWRUN/RUN 封装，会话由 AIM 管理）
- `meeting/`
  - `recorder.py`     PipeWire 音频采集（parec raw 16k 单声道，规避 pw-record 的 monitor 解析 bug）
  - `vad.py`          webrtcvad 语音分段 → 逐段 wav（当前流程未启用，整段连续录音）
  - `scheduler.py`    按 audio 片段组装载荷，首段 newrun、后续 run 增量；async_mode 后台线程
  - `transcribe.py`   pywhispercpp 本地转写：音量归一化、剥离爆音、≥120s 并行分块
  - `persistence.py`  纪要落盘 Markdown（知识库归档留 stub）
  - `notify.py`       notify-send 桌面通知（带节流）

## 核心运行流程

```
GUI(app.py):
  「开始录制」→ worker 线程写 full_{source}.wav(16k 单声道 16bit)
    → 用户「停止并生成纪要」→ Scheduler(async) → 后台线程
      → transcribe(wav→txt) → aim newrun(指令+文件路径) → on_result
      → GLib.idle_add 落盘 .md + 追加 UI + 桌面通知

CLI(main.py):
  recorder.start → 循环直到 SIGINT/SIGTERM → sink.close
    → scheduler.submit([full_path])（同步）→ notify + 日志
```

## 依赖

```bash
pip install -r requirements.txt   # numpy, webrtcvad
```
系统依赖：`pipewire` / `pw-record`、GTK3（`python3-gi`）、`notify-send`。

## 使用

### 图形界面（推荐）
```bash
python3 app.py [--out 纪要目录] [--seg 分段目录] [--timeout 1800]
```
- 「开始录制会议（系统内录）」录制电脑内部音频（远程会议/视频播放的声音）。
- 「开始录制会议（麦克风）」录制麦克风输入。
- 「停止并生成纪要」结束并落盘目录。

### 命令行守护
```bash
python3 main.py --source internal     # 实时采集系统内录，Ctrl+C 停止
python3 main.py --source mic          # 实时采集麦克风
python3 main.py --self-test           # 合成音频自检
```

> 同源变体见 `meeting-summary-cli/`：采集层改用 `pw-record`（PipeWire 原生），其余模块一致。

## 说明

- AIM 命令入参为 `aim newrun <载荷>`（新会话）、`aim run <载荷>`（接续会话）。
- 系统内录使用输出设备的 Monitor 源；麦克风使用默认输入源；`--target <节点>` 可覆盖。
- 转写优先使用本地较大模型（`ggml-small`，若存在），否则回退 `ggml-base`。
- 转写前自动归一化音量、去除开头瞬态爆音并做并行分块，避免长录音只识别开头几行。
- 真实 `aim` 调用可能因排队较慢，`--timeout` 默认 1800s。