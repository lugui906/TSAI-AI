# TSAI-OS 隔空手势系统（Python 实现）

对标鸿蒙笔记本隔空手势能力的桌面级系统，**纯本地、离线、无云端**推理。
基于 OpenCV 采帧 + 双 TFLite 手部模型（INT8），以 systemd 用户服务运行于
wlroots Wayland 桌面。当前只保留一个手势：**手掌前推 → 媒体播放/暂停**。

> GPL-3.0 许可，详见根目录 LICENSE。

## 核心特性

- 全离线本地推理：`palm_detection_lite` + `hand_landmark_lite` 双模型，
  运行零网络请求。
- 双状态节能调度：休眠低帧率（320×240 / 5fps）轻量推理，唤醒高帧率
  （640×480 / 30fps）全量推理，显著降低空载功耗。
- 四状态严格状态机：SLEEP / WAKE / GESTURE / IDLE，杜绝误触、手抖、干扰。
- 原生 Wayland 输出：媒体播放/暂停与状态通知走 DBus（MPRIS / 自定义信号）。
- 全参数可配置 + 热重载；GTK4 系统设置面板；桌面顶栏状态提示。
- 无模型/摄像头时的 **DemoBackend** 全链路自测模式。

## 目录结构

```
tsai-airgestured/
├── tsai_airgestured/       # 核心包
│   ├── config.py           # INI 配置 + 热重载
│   ├── camera.py           # OpenCV 采集层（设备抢占/释放/重试）
│   ├── demo_camera.py      # 无硬件测试源（脚本化轨迹）
│   ├── inference.py        # 推理后端抽象（OpenCV DNN / Demo）
│   ├── filter.py           # 卡尔曼滤波（21 点逐分量平滑）
│   ├── gesture.py          # 手势分类（滑动/握拳截屏/前推）
│   ├── state_machine.py    # 四状态状态机
│   ├── output.py           # 键盘模拟 + DBus(MPRIS/Portal/状态)
│   ├── driver.py           # 主循环（采集→推理→滤波→状态机→分类→输出）
│   └── demo_driver.py      # 自测驱动
├── etc/tsai-airgestured.conf   # 全局配置
├── systemd/                    # 用户服务单元
├── models/                      # 模型部署说明
├── scripts/deploy_models.sh     # 模型部署/校验脚本
├── panel/tsai_settings.py       # GTK4 设置面板
├── test/                        # 核心逻辑单测
└── install.sh                   # 安装脚本
```

## 运行

```bash
# 1) 安装依赖（重点服务器/桌面系统）
pip install --break-system-packages opencv-python numpy PyGObject dbus-python

# 2) 部署模型（离线放入 /usr/share/tsai-airgestured/models/，缺省回落 demo 模式）
bash scripts/deploy_models.sh           # 离线校验
bash scripts/deploy_models.sh --download # 联网下载

# 3) 自检
python -m tsai_airgestured --check

# 4) 无硬件/模型自测（全链路 demo）
python -m tsai_airgestured --demo push

# 5) 以守护进程运行
bash install.sh
systemctl --user enable --now tsai-airgestured

# 6) GTK4 设置面板
python3 panel/tsai_settings.py
```

## 配置

`/etc/tsai-airgestured.conf`（INI，支持热重载，保存即生效）：

```ini
[general]
enable = true
sleep_timeout_sec = 3

[gestures]
gesture_scroll_up = true
gesture_scroll_down = true
gesture_playpause = true

[camera]
device = /dev/video0
sleep_fps = 5
wake_fps = 30

[inference]
num_thread = 2
min_detect_conf = 0.5
min_track_conf = 0.6
cool_down_ms = 500
rearm_sec = 1.0
push_threshold = 0.01       # 前推阈值（尺寸增长率，越小越灵敏）
vertical_frac = 0.3         # 上下滑动位移阈值（Y位移/手宽，越小越灵敏）
```

## 手势不触发？用 `--monitor` 标定

真实模型的坐标单位与 demo 不同，默认阈值已改为**按手部宽度归一化**
（与模型单位/相机/距离无关）。运行时用监控观察实际量级再微调阈值：

```bash
python tools/tsai-airgestured --monitor
# 每 0.5s 打印: 中心 center、位移 move（手宽倍数）、手宽 handW、尺寸增长率 grow
# 若 grow 一直达不到阈值，相应调低 push_threshold
```

判定均为「归一化阈值」：前推看 `grow`（palm 尺寸增长率，轻轻前推即触发）。

## 手势清单

| 手势 | 系统行为 | 判定规则 |
|---|---|---|
| 手掌上滑 | 页面上滚（Page_Up） | 中心 Y 显著减小、轨迹单向 |
| 手掌下滑 | 页面下滚（Page_Down） | 中心 Y 显著增大、轨迹单向 |
| 手掌轻轻前推 | 播放/暂停（MPRIS PlayPause） | palm 尺寸小幅增长、横向位移小 |

## 测试

```bash
PYTHONPATH=. python3 test/test_gesture_core.py
# 覆盖：卡尔曼滤波、四状态状态机、前推播放/暂停
```
