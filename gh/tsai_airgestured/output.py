"""输出层（Wayland 原生 + DBus）。

对应用户「5. 输出层接口规范」：

* 滚动：``scroll_up`` -> Page_Up、``scroll_down`` -> Page_Down，优先经
  ``xdotool`` 模拟按键（失败回落 ``ydotool``）。
* 媒体播放/暂停：MPRIS ``org.mpris.MediaPlayer2.Player`` 的 ``PlayPause()``。
* 状态通知：``org.tsaios.airgesture`` 的 ``StateChanged(string)`` 信号。

DBus 使用 ``Gio.GDBusConnection`` 同步调用/发信号，无需额外主循环，
驱动线程可安全调用。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import DBUS_IFACE, DBUS_NAME, DBUS_PATH  # noqa: E402

logger = logging.getLogger("tsai.output")

__all__ = ["KeyOutcome", "OutputLayer"]


class KeyOutcome:
    """键盘执行结果（便于测试判断实际落到哪个后端）。"""
    SKIPPED = "skipped"
    XDOTOOL = "xdotool"
    YDOTOOL = "ydotool"
    DBUS = "dbus"


def _run(argv: list[str], timeout: float = 2.0) -> bool:
    """运行外部命令，捕获异常/超时，返回是否成功。"""
    try:
        subprocess.run(argv, check=False, timeout=timeout,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


class OutputLayer:
    """统一输出层：将 :class:`GestureType` 映射为系统操作。

    滚动使用 PageUp/PageDown 键（普通适用于页面/PPT），优先 xdotool；
    媒体播放/暂停走 MPRIS DBus。
    """

    # 手势 -> 按键/动作 映射
    KEYMAP = {
        "scroll_up": {"prefer": "xdotool", "keys": ["Page_Up"]},
        "scroll_down": {"prefer": "xdotool", "keys": ["Page_Down"]},
    }

    def __init__(self) -> None:
        self._bus: Optional[Gio.DBusConnection] = None
        self.has_dbus = False
        self.ydo = shutil.which("ydotool")
        self.xdo = shutil.which("xdotool")
        self._connect_dbus()

    # ------------------------------------------------------------------
    # DBus
    # ------------------------------------------------------------------
    def _connect_dbus(self) -> None:
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.has_dbus = True
        except Exception as exc:
            logger.warning("no DBus session: %s", exc)
            self.has_dbus = False

    def emit_state(self, state: str) -> None:
        """发出 ``StateChanged(string)`` 信号供桌面 UI 同步。"""
        if not self._bus:
            return
        try:
            variant = GLib.Variant("(s)", (state,))
            self._bus.emit_signal(None, DBUS_PATH, DBUS_IFACE,
                                  "StateChanged", variant)
        except Exception as exc:
            logger.warning("emit_state failed: %s", exc)

    def _call_sync(self, dest: str, path: str, iface: str, method: str,
                   params: Optional[GLib.Variant] = None,
                   reply_type: Optional[GLib.VariantType] = None) -> bool:
        """同步调用远端方法，成功返回 True。"""
        if not self._bus:
            return False
        try:
            self._bus.call_sync(dest, path, iface, method, params, reply_type,
                                0, -1, None)
            return True
        except Exception as exc:
            logger.debug("dbus call %s.%s failed: %s", iface, method, exc)
            return False

    # ------------------------------------------------------------------
    # MPRIS 媒体控制
    # ------------------------------------------------------------------
    def mpris_playpause(self) -> bool:
        """全局媒体播放/暂停（找第一个 MPRIS 播放器）。"""
        name = self._find_mpris_player()
        if not name:
            logger.info("no MPRIS player found")
            return False
        return self._call_sync(name, "/org/mpris/MediaPlayer2",
                               "org.mpris.MediaPlayer2.Player", "PlayPause")

    def _find_mpris_player(self) -> Optional[str]:
        if not self._bus:
            return None
        try:
            res = self._bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "ListNames", None,
                GLib.VariantType("(as)"), 0, 2000, None)
            names = res.unpack()[0] if res else []
            for n in names:
                if n.startswith("org.mpris.MediaPlayer2"):
                    return n
        except Exception as exc:
            logger.warning("ListNames failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # 键盘
    # ------------------------------------------------------------------
    def press_key(self, keys: list[str], prefer: str = "xdotool",
                  count: int = 1) -> KeyOutcome:
        """发送按键。优先 ``prefer`` 后端，失败自动回落另一后端。"""
        for _ in range(count):
            if prefer == "xdotool" and self.xdo:
                if _run([self.xdo, "key"] + keys):
                    return KeyOutcome.XDOTOOL
                # X11 走 XWayland 失败时回落 ydotool
                if self.ydo and _run([self.ydo, "key"] + keys):
                    return KeyOutcome.YDOTOOL
            else:
                if self.ydo and _run([self.ydo, "key"] + keys):
                    return KeyOutcome.YDOTOOL
                if self.xdo and _run([self.xdo, "key"] + keys):
                    return KeyOutcome.XDOTOOL
        return KeyOutcome.SKIPPED

    # ------------------------------------------------------------------
    # 顶层分派
    # ------------------------------------------------------------------
    def dispatch(self, gesture: str) -> str:
        """按手势名触发对应系统操作，返回执行概览（供日志/测试）。

        返回字符串：``"keyboard:scroll_up[xdotool]"``、``"dbus:playpause"``。
        """
        if gesture == "playpause":
            return "dbus:playpause" if self.mpris_playpause() else "skipped"
        if gesture in self.KEYMAP:
            entry = self.KEYMAP[gesture]
            out = self.press_key(entry["keys"], entry.get("prefer", "xdotool"))
            return f"keyboard:{gesture}[{out}]"
        return "skipped"