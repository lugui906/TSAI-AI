"""TSAI-OS 隔空手势系统 Python 实现。

对标鸿蒙隔空手势能力，纯本地 CPU 离线推理，无网络、无云端依赖。

设计目标
--------
* 全离线本地推理：内置 INT8 量化手部模型（MediaPipe 风格 palm/landmark 双模型）。
* 双状态节能调度：休眠低帧率轻量推理，唤醒高帧率全量推理。
* 四状态严格状态机（SLEEP/WAKE/GESTURE/IDLE）：杜绝误触、手抖、环境干扰。
* 原生 Wayland 输出：媒体播放/暂停与状态通知走 DBus（MPRIS / 自定义信号）。
* 全参数可配置化 + 热重载；桌面顶栏状态提示 + GTK4 系统设置面板。
"""

__version__ = "1.0.0"
__author__ = "TSAI-OS"
__license__ = "Apache-2.0"

# 模型固定部署路径（与系统镜像约定一致）
MODEL_DIR = "/usr/share/tsai-airgestured/models"
# 全局配置文件路径
CONFIG_PATH = "/etc/tsai-airgestured.conf"
# DBus 自定义状态接口总线名
DBUS_NAME = "org.tsaios.airgesture"
DBUS_PATH = "/org/tsaios/airgesture"
DBUS_IFACE = "org.tsaios.airgesture"

# 主要运行时状态（供 UI / 日志引用）
STATE_SLEEP = "sleep"
STATE_WAKE = "wake"
STATE_GESTURE = "gesture"
STATE_IDLE = "idle"
