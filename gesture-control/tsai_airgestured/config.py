"""全局配置加载与热重载。

配置文件采用 ``INI`` 风格（``configparser``），与文档中的
``/etc/tsai-airgestured.conf`` 格式完全一致，支持自动热重载
（``mtime`` 变化检测，每次读取前检测是否已改）与变更回调。

字段说明索引（与开发文档一一对应）::

    [general]      enable / sleep_timeout_sec / sensitivity
    [gestures]     gesture_scroll_up / down / playpause
    [camera]       device / sleep_fps / wake_fps
    [inference]    num_thread / min_detect_conf / min_track_conf / cool_down_ms

"""

from __future__ import annotations

import configparser
import os
import threading
from typing import Any, Callable, Dict

from . import CONFIG_PATH

__all__ = ["Config"]


class Config:
    """INI 配置对象，带线程安全的热重载与变更回调。

    参数
    ----
    path:
        配置文件路径，默认 ``/etc/tsai-airgestured.conf``。
    auto_reload:
        每次读取前自动检测文件是否变化并重载。
    """

    def __init__(self, path: str = "", auto_reload: bool = True) -> None:
        self.path = path or CONFIG_PATH
        self.auto_reload = auto_reload
        self._parser = configparser.ConfigParser()
        self._mtime: float = -1.0
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []
        self._load()

    # ------------------------------------------------------------------ #
    # 加载 / 重载
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        """重新加载配置文件到内存，缺失的键在读取时回退默认值。"""
        p = configparser.ConfigParser()
        p.optionxform = str  # 保留键原始大小写（device、num_thread 等）
        try:
            if os.path.exists(self.path):
                p.read(self.path)
            self._mtime = os.path.getmtime(self.path) if os.path.exists(self.path) else -1.0
        except OSError:
            p = configparser.ConfigParser()  # 读取失败则用空配置
            self._mtime = -1.0
        self._parser = p

    def is_changed(self) -> bool:
        """检测配置文件相对上次加载是否被修改。"""
        if not os.path.exists(self.path):
            return False
        try:
            return os.path.getmtime(self.path) != self._mtime
        except OSError:
            return False

    def reload_if_changed(self) -> bool:
        """若文件有变化则重载并触发变更回调，返回是否发生重载。"""
        if not self.is_changed():
            return False
        with self._lock:
            self._load()
        for cb in list(self._callbacks):
            try:
                cb()
            except Exception:
                pass
        return True

    def reload(self) -> None:
        """强制重载（供设置面板保存后主动调用）。"""
        with self._lock:
            self._load()
        for cb in list(self._callbacks):
            try:
                cb()
            except Exception:
                pass

    def add_change_callback(self, fn: Callable[[], None]) -> None:
        """注册配置变更回调，文件变化重载后触发。"""
        self._callbacks.append(fn)

    # ------------------------------------------------------------------
    # 读取辅助
    # ------------------------------------------------------------------
    def _get(self, section: str, key: str, default: str) -> str:
        try:
            v = (self._parser.get(section, key) or "").strip()
            return v if v else default
        except (configparser.Error, KeyError):
            return default

    def _maybe_reload(self) -> None:
        if self.auto_reload:
            self.reload_if_changed()

    def get_str(self, section: str, key: str, default: str = "") -> str:
        self._maybe_reload()
        with self._lock:
            return self._get(section, key, default)

    def get_int(self, section: str, key: str, default: int) -> int:
        try:
            return int(self.get_str(section, key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_float(self, section: str, key: str, default: float) -> float:
        try:
            return float(self.get_str(section, key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_bool(self, section: str, key: str, default: bool) -> bool:
        v = self.get_str(section, key, "true" if default else "false").strip().lower()
        return v in {"1", "true", "yes", "on"}

    def get_enum(self, section: str, key: str, default: str, allowed) -> str:
        v = self.get_str(section, key, default).strip().lower()
        return v if v in allowed else default

    # ------------------------------------------------------------------
    # 语义化便捷方法
    # ------------------------------------------------------------------
    def gesture_enabled(self, name: str) -> bool:
        """查询某个手势的总开关。``name`` 可带或不带 ``gesture_`` 前缀。"""
        key = name if name.startswith("gesture_") else f"gesture_{name}"
        return self.get_bool("gestures", key, True)

    def export_dict(self) -> dict[str, Any]:
        """导出为字典，供 GTK4 设置面板读写时共享同一份语义。"""
        return {
            "general": {
                "enable": self.get_bool("general", "enable", True),
                "sleep_timeout_sec": self.get_int("general", "sleep_timeout_sec", 3),
                "sensitivity": self.get_enum(
                    "general", "sensitivity", "high", ("low", "medium", "high")
                ),
            },
            "gestures": {
                "scroll_up": self.gesture_enabled("gesture_scroll_up"),
                "scroll_down": self.gesture_enabled("gesture_scroll_down"),
                "playpause": self.gesture_enabled("gesture_playpause"),
            },
            "camera": {
                "device": self.get_str("camera", "device", "/dev/video0"),
                "sleep_fps": self.get_int("camera", "sleep_fps", 5),
                "wake_fps": self.get_int("camera", "wake_fps", 10),
            },
            "inference": {
                "num_thread": self.get_int("inference", "num_thread", 2),
                "min_detect_conf": self.get_float("inference", "min_detect_conf", 0.5),
                "min_track_conf": self.get_float("inference", "min_track_conf", 0.6),
                "cool_down_ms": self.get_int("inference", "cool_down_ms", 500),
                "rearm_sec": self.get_float("inference", "rearm_sec", 2.0),
                "push_threshold": self.get_float("inference", "push_threshold", 0.05),
                "vertical_frac": self.get_float("inference", "vertical_frac", 0.3),
            },
        }