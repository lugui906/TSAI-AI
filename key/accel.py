"""GNOME Shell Accelerator — 通过桌面环境官方 D-Bus 接口注册全局快捷键。

使用 org.gnome.Shell 的 GrabAccelerator / UngrabAccelerator 方法，
监听 AcceleratorActivated 信号。

GNOME Shell 会校验调用者的会话总线名（见 misc/util.js 的
DBusSenderChecker）：仅允许 settings / portal 等系统进程调用
GrabAccelerator。因此本模块先抢占一个当前未被占用的白名单总线名
（如 org.gnome.InitialSetup / org.gnome.Settings），再发起注册。
"""
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib

# DBusSenderChecker 允许调用的白名单总线名（见 shellDBus.js）
_ALLOWED_NAMES = [
    "org.gnome.InitialSetup",
    "org.gnome.Settings",
]

# RequestName 返回值（PRIMARY_OWNER / EXISTS）
_PRIMARY_OWNER = 1

# RequestName flags：不排队，避免被卡在等待队列
_DO_NOT_QUEUE = 4

# Shell.ActionMode 位掩码（见 shell-enum-types.h），
# 与 gnome-shell 自家截图快捷键一致：
#   ALL & ~LOGIN_SCREEN —— 所有界面模式下生效，但不含登录屏
#   NORMAL=1, OVERVIEW=2, LOCK_SCREEN=4, UNLOCK_SCREEN=8,
#   LOGIN_SCREEN=16, SYSTEM_MODAL=32, LOOKING_GLASS=64, POPUP=128
_ACTION_MODES = 0xFF & ~0x10  # 239


class AcceleratorManager:
    def __init__(self, bus=None):
        self._bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION)
        self._ids = {}  # id -> cmd
        self._signal_id = None
        self._enabled = False
        self._owned_name = None

    def _acquire_allowlisted_name(self):
        """抢占一个未占用的白名单总线名，成功返回 True"""
        if self._owned_name:
            return True
        for name in _ALLOWED_NAMES:
            try:
                result = self._bus.call_sync(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "RequestName",
                    GLib.Variant("(su)", (name, _DO_NOT_QUEUE)),
                    GLib.VariantType("(u)"),
                    Gio.DBusCallFlags.NONE,
                    500,
                    None,
                )
            except Exception as e:
                print(f"[Accel] 请求总线名失败: {name} -> {e}", flush=True)
                continue
            if result is not None and result[0] == _PRIMARY_OWNER:
                self._owned_name = name
                print(f"[Accel] 已取得白名单总线名: {name}", flush=True)
                return True
            print(f"[Accel] 总线名被占用: {name}", flush=True)
        return False

    def _release_allowlisted_name(self):
        if not self._owned_name:
            return
        try:
            self._bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "ReleaseName",
                GLib.Variant("(s)", (self._owned_name,)),
                GLib.VariantType("(u)"),
                Gio.DBusCallFlags.NONE,
                500,
                None,
            )
            print(f"[Accel] 已释放总线名: {self._owned_name}", flush=True)
        except Exception as e:
            print(f"[Accel] 释放总线名失败: {e}", flush=True)
        self._owned_name = None

    def is_available(self):
        """检查 GNOME Shell D-Bus 服务是否在运行"""
        try:
            result = self._bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "NameHasOwner",
                GLib.Variant("(s)", ("org.gnome.Shell",)),
                GLib.VariantType("(b)"),
                Gio.DBusCallFlags.NONE,
                500,
                None,
            )
            available = result and result[0]
            print(f"[Accel] org.gnome.Shell 存在: {available}", flush=True)
            return bool(available)
        except Exception as e:
            print(f"[Accel] D-Bus 检查失败: {e}", flush=True)
            return False

    def register(self, accelerator, cmd):
        """注册一个全局快捷键，返回 ID 或 None"""
        acquired = self._acquire_allowlisted_name()
        # 抢占名字后 shell 的名字监听器更新白名单有一小段延迟，
        # 若被 AccessDenied 拒绝则短暂重试
        attempts = 10 if acquired else 1
        for attempt in range(attempts):
            try:
                result = self._bus.call_sync(
                    "org.gnome.Shell",
                    "/org/gnome/Shell",
                    "org.gnome.Shell",
                    "GrabAccelerator",
                    GLib.Variant("(suu)", (accelerator, _ACTION_MODES, 0)),
                    GLib.VariantType("(u)"),
                    Gio.DBusCallFlags.NONE,
                    1000,
                    None,
                )
            except Exception as e:
                print(f"[Accel] 注册失败: {accelerator} -> {e}", flush=True)
                if acquired and "AccessDenied" in str(e) and attempt < attempts - 1:
                    time.sleep(0.15)
                    continue
                return None
            aid = result[0] if result is not None else 0
            if aid:
                self._ids[aid] = cmd
                print(f"[Accel] 注册成功: {accelerator} -> {cmd} (id={aid})", flush=True)
                return aid
            print(f"[Accel] 注册失败: {accelerator} 被 shell 拒绝", flush=True)
            return None
        return None

    def unregister(self, aid):
        """注销一个快捷键"""
        try:
            self._bus.call_sync(
                "org.gnome.Shell",
                "/org/gnome/Shell",
                "org.gnome.Shell",
                "UngrabAccelerator",
                GLib.Variant("(u)", (aid,)),
                GLib.VariantType("(b)"),
                Gio.DBusCallFlags.NONE,
                500,
                None,
            )
            print(f"[Accel] 注销: id={aid}", flush=True)
        except Exception as e:
            print(f"[Accel] 注销失败: {e}", flush=True)
        self._ids.pop(aid, None)

    def unregister_all(self):
        for aid in list(self._ids.keys()):
            self.unregister(aid)
        self._ids.clear()
        if self._signal_id is not None:
            self._bus.signal_unsubscribe(self._signal_id)
            self._signal_id = None
        self._enabled = False
        self._release_allowlisted_name()

    def connect(self, on_activated):
        """连接 AcceleratorActivated 信号，on_activated(id) 回调"""
        if self._enabled:
            return
        self._signal_id = self._bus.signal_subscribe(
            "org.gnome.Shell",
            "org.gnome.Shell",
            "AcceleratorActivated",
            "/org/gnome/Shell",
            None,
            Gio.DBusSignalFlags.NONE,
            lambda connection, sender, obj_path, iface, signal, params: (
                on_activated(params[0])
            ),
        )
        self._enabled = True
        print("[Accel] 已连接 AcceleratorActivated 信号", flush=True)

    def get_command(self, aid):
        return self._ids.get(aid)
