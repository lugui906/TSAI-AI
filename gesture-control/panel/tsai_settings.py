#!/usr/bin/env python3
"""TSAI-OS 隔空手势系统设置面板（GTK4 / PyGObject）。

功能（对应用户「7.2 系统设置面板」）：
  * 服务控制：启动 / 停止后台手势服务（默认不自启动）
  * 开机自启动开关（写入/删除 /etc/xdg/autostart 条目）
  * 总开关 + 单手势独立启停
  * 休眠超时滑块（1–5 秒）
  * 摄像头设备选择
  * 状态实时显示（监听 StateChanged DBus 信号）
  * 保存后写回全局配置

运行：``python3 panel/tsai-airgesture-settings.py``
"""

from __future__ import annotations

import configparser
import os
import signal
import sys
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GLib", "2.0")
try:
    gi.require_version("Gio", "2.0")
except Exception:
    pass
from gi.repository import Gtk, GLib, Gio

from tsai_airgestured import CONFIG_PATH

APP_ID = "org.tsaios.airgesture.settings"

# 安装根（本文件位于 <root>/panel/），由此定位守护进程入口，与安装位置无关
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON_CMD = [sys.executable or "python3", os.path.join(APP_ROOT, "tools", "tsai-airgestured")]
_RUN_DIR = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
PID_FILE = os.path.join(_RUN_DIR, "tsai-airgestured.pid")
LOG_FILE = os.path.join(_RUN_DIR, "tsai-airgestured.log")
AUTOSTART_FILE = "/etc/xdg/autostart/tsai-airgestured.desktop"


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app, config_path: str = CONFIG_PATH) -> None:
        super().__init__(application=app, title="隔空手势设置")
        self.set_default_size(520, 620)
        self.config_path = config_path
        self.cfg = configparser.ConfigParser()
        self.cfg.optionxform = str
        self.load()
        self._build_ui()

    # ------------------------------------------------------------------
    def load(self) -> None:
        if os.path.exists(self.config_path):
            self.cfg.read(self.config_path)

    def save(self) -> None:
        with open(self.config_path, "w") as f:
            self.cfg.write(f)

    def _get(self, sec, key, default=""):
        try:
            return self.cfg.get(sec, key, fallback=default)
        except Exception:
            return default

    def _set(self, sec, key, val):
        if not self.cfg.has_section(sec):
            self.cfg.add_section(sec)
        self.cfg.set(sec, key, str(val))

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(16); box.set_margin_end(16)

        # 服务控制
        box.append(self._label("服务控制"))
        row = self._titled_box("运行状态")
        self.service_status = Gtk.Label(label="未运行", xalign=0)
        row.append(self.service_status)
        box.append(row)

        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.start_btn = Gtk.Button(label="启动服务")
        self.start_btn.connect("clicked", self.on_start_service)
        self.stop_btn = Gtk.Button(label="停止服务")
        self.stop_btn.connect("clicked", self.on_stop_service)
        hb.append(self.start_btn); hb.append(self.stop_btn)
        box.append(hb)

        sw_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sw_row.append(Gtk.Label(label="开机自启动（登录时自动运行服务）"))
        self.autostart_sw = Gtk.Switch()
        self.autostart_sw.set_active(self._autostart_enabled())
        self.autostart_sw.connect("state-set", self.on_autostart_toggle)
        sw_row.append(self.autostart_sw)
        box.append(sw_row)

        # 总开关
        self.master = Gtk.Switch()
        self.master.set_active(self._get("general", "enable", "true").lower() in ("true", "1", "on", "yes"))
        row = self._titled_box("隔空手势")
        switch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        switch_box.append(Gtk.Label(label="启用"))
        switch_box.append(self.master)
        row.append(switch_box)
        box.append(row)

        # 休眠超时滑块
        box.append(self._label("休眠超时（秒）"))
        adj = Gtk.Adjustment(value=float(self._get("general", "sleep_timeout_sec", "3")),
                             lower=1, upper=5, step_increment=1)
        self.timeout_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        self.timeout_scale.set_digits(0)
        box.append(self.timeout_scale)

        # 手势开关
        box.append(self._label("手势开关"))
        self.gest_sw = {}
        self.gest_entries = [("scroll_up", "上滑（页面上滚）"),
                             ("scroll_down", "下滑（页面下滚）"),
                             ("playpause", "前推（播放/暂停）")]
        for key, label in self.gest_entries:
            sw = Gtk.Switch()
            sw.set_active(self._get("gestures", f"gesture_{key}", "true").lower() in ("true", "1", "on", "yes"))
            self.gest_sw[key] = sw
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hb.append(Gtk.Label(label=label)); hb.append(sw)
            box.append(hb)

        # 摄像头（自动探测 + 下拉选择）
        box.append(self._label("摄像头设备"))
        cam_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.camera_list = Gtk.StringList()
        self.camera_drop = Gtk.DropDown(model=self.camera_list)
        cam_row.append(self.camera_drop)
        refresh_btn = Gtk.Button(label="重新检测")
        refresh_btn.connect("clicked", self.on_rescan_camera)
        cam_row.append(refresh_btn)
        box.append(cam_row)
        self._rescan_cameras()

        # 状态显示
        box.append(self._label("实时状态"))
        self.status_label = Gtk.Label(label="未知", xalign=0)
        box.append(self.status_label)

        # 按钮
        save_btn = Gtk.Button(label="保存并应用")
        save_btn.connect("clicked", self.on_save)
        box.append(save_btn)

        self.set_child(box)
        self._refresh_service_ui()

    # ------------------------------------------------------------------
    # 摄像头自动探测
    # ------------------------------------------------------------------
    def _rescan_cameras(self) -> None:
        from tsai_airgestured.camera import Camera

        try:
            devices = Camera.list_cameras()
        except Exception:
            devices = []
        labels = [Camera.device_label(d) for d in devices] or ["（未检测到摄像头）"]
        while self.camera_list.get_n_items() > 0:
            self.camera_list.remove(0)
        for lab in labels:
            self.camera_list.append(lab)
        cur = self._get("camera", "device", "/dev/video0")
        sel = -1
        for i, d in enumerate(devices):
            if d == cur:
                sel = i
                break
        if sel < 0 and devices:
            sel = 0
        self.camera_drop.set_selected(sel if sel >= 0 else 0)
        if devices:
            self._cam_devices = devices
        else:
            self._cam_devices = []
            self.status_label.set_text("未检测到摄像头（可重新检测或检查 /dev 挂载）")

    def on_rescan_camera(self, _btn) -> None:
        self._rescan_cameras()
        self.status_label.set_text("已重新检测摄像头")

    def _selected_camera(self) -> str:
        """返回当前选择的 /dev/videoN 路径。"""
        devs = getattr(self, "_cam_devices", [])
        if devs:
            idx = self.camera_drop.get_selected()
            if 0 <= idx < len(devs):
                return devs[idx]
        # 无探测结果时回落配置值，避免覆盖
        return self._get("camera", "device", "/dev/video0")

    # ------------------------------------------------------------------
    # 服务控制
    # ------------------------------------------------------------------
    def _daemon_pid(self):
        """返回正在运行的服务 PID，未运行返回 None。"""
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)          # 探测进程是否存在
            return pid
        except Exception:
            return None

    def _autostart_enabled(self) -> bool:
        return os.path.exists(AUTOSTART_FILE)

    def _refresh_service_ui(self) -> None:
        pid = self._daemon_pid()
        running = pid is not None
        self.service_status.set_text("运行中（PID %s）" % pid if running else "未运行")
        self.start_btn.set_sensitive(not running)
        self.stop_btn.set_sensitive(running)

    def on_start_service(self, _btn) -> None:
        if self._daemon_pid() is not None:
            return
        try:
            with open(LOG_FILE, "ab") as log:
                proc = subprocess.Popen(
                    DAEMON_CMD, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=log, start_new_session=True)
            with open(PID_FILE, "w") as f:
                f.write(str(proc.pid))
        except Exception as exc:
            self.status_label.set_text("启动失败：%s" % exc)
            return
        self._refresh_service_ui()
        self.status_label.set_text("服务已启动（日志：%s）" % LOG_FILE)

    def on_stop_service(self, _btn) -> None:
        pid = self._daemon_pid()
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass
        self._refresh_service_ui()
        self.status_label.set_text("服务已停止")

    def on_autostart_toggle(self, sw, state) -> None:
        try:
            if state:
                with open(AUTOSTART_FILE, "w") as f:
                    f.write(
                        "[Desktop Entry]\n"
                        "Type=Application\n"
                        "Name=隔空手势服务\n"
                        "Comment=隔空手势后台服务（上下滑动滚动、前推播放/暂停）\n"
                        "Exec=python3 %s\n"
                        "Icon=video-display\n"
                        "Terminal=false\n"
                        "X-GNOME-Autostart-enabled=true\n"
                        % os.path.join(APP_ROOT, "tools", "tsai-airgestured"))
            else:
                if os.path.exists(AUTOSTART_FILE):
                    os.unlink(AUTOSTART_FILE)
        except Exception as exc:
            self.status_label.set_text("自启动设置失败：%s" % exc)
            sw.set_active(not state)
            return
        self.status_label.set_text("开机自启动已%s" % ("开启" if state else "关闭"))

    def _titled_box(self, title: str) -> Gtk.Box:
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        b.append(Gtk.Label(label=title, xalign=0))
        return b

    def _label(self, text: str) -> Gtk.Label:
        l = Gtk.Label(label=text, xalign=0)
        l.add_css_class("heading")
        return l

    # ------------------------------------------------------------------
    def on_save(self, _btn) -> None:
        self._set("general", "enable", "true" if self.master.get_active() else "false")
        self._set("general", "sleep_timeout_sec", int(self.timeout_scale.get_value()))
        for key, _ in self.gest_entries:
            self._set("gestures", f"gesture_{key}", "true" if self.gest_sw[key].get_active() else "false")
        self._set("camera", "device", self._selected_camera())
        self.save()
        self.status_label.set_text("已保存，配置文件已热重载")

    # 预留：接入 DBus 订阅 org.tsaios.airgesture StateChanged 更新状态
    def _init_state_listener(self) -> None:
        try:
            conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            conn.signal_subscribe("org.tsaios.airgesture", "org.tsaios.airgesture",
                                  "StateChanged", "/org/tsaios/airgesture",
                                  None, Gio.DBusSignalFlags.NONE,
                                  self._on_state, None)
        except Exception:
            pass

    def _on_state(self, conn, sender, obj, iface, sig, params, data) -> None:
        try:
            self.status_label.set_text(f"当前状态：{params.unpack()[0]}")
        except Exception:
            pass


def main() -> int:
    app = Gtk.Application(application_id=APP_ID)
    app.connect("activate", lambda a: SettingsWindow(a).present())
    return app.run()


if __name__ == "__main__":
    sys.exit(main())