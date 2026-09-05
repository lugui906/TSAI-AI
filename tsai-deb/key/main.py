#!/usr/bin/env python3
"""AI 助手 — 后台常驻 + 全局快捷键（按原版逻辑）。

后台检测（strictly 沿原版 key GTK 行为）：
- Gtk.Application 常驻（持 application_id=com.local.AiAssistant, NON_UNIQUE）
- 通过 GNOME Shell D-Bus (accel.py GrabAccelerator) 注册全局快捷键
  Alt+S 唤醒 / Alt+T 截图 / Alt+D 界面上下文
- 窗口用 WebKit 显示 chinai3 风格 Flask 界面；close 仅隐藏不退出
- --hidden 后台启动（不显示窗口，仍常驻监听快捷键）
"""
import os
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for p in (BASE_DIR, "/usr/chindows"):
    if p not in sys.path:
        sys.path.insert(0, p)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("WebKit", "6.0")

from gi.repository import Gdk, Gio, GLib, Gtk, WebKit  # noqa: E402

import server  # noqa: E402
from accel import AcceleratorManager  # noqa: E402
from ipc import Client as IPCClient  # noqa: E402
from chindshell import shell as chshell  # noqa: E402


def _free_port():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class KeyWindow(Gtk.ApplicationWindow):
    def __init__(self, app, url):
        super().__init__(application=app, title="AI 助手")
        self.set_default_size(760, 560)
        self.set_size_request(600, 420)
        settings = WebKit.Settings()
        settings.set_javascript_can_open_windows_automatically(False)
        settings.set_enable_back_forward_navigation_gestures(False)
        web = WebKit.WebView(settings=settings)
        web.set_background_color(Gdk.RGBA(0, 0, 0, 0))

        def on_load(w, event):
            if event == WebKit.LoadEvent.FINISHED:
                w.evaluate_javascript(chshell.CTX_MENU_JS, -1, None, None, None, None, None)

        web.connect("load-changed", on_load)
        web.load_uri(url)
        self.set_child(web)


class KeyApp(Gtk.Application):
    def __init__(self, start_hidden=False, pending_cmd=None):
        super().__init__(application_id="com.local.AiAssistant",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.start_hidden = start_hidden
        self.pending_cmd = pending_cmd
        self.win = None
        self._accel = None
        self._accel_ids = {}
        self._port = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        # 启动 Flask server（独立线程）
        self._port = _free_port()
        t = threading.Thread(
            target=lambda: server.app.run(host="127.0.0.1", port=self._port, threaded=True),
            daemon=True,
        )
        t.start()
        time.sleep(0.9)
        print(f"[AI助手] 服务: http://127.0.0.1:{self._port}/", flush=True)

        # 主实例启动 IPC socket 服务（原版由窗口应用持有）
        try:
            server.start_ipc()
        except Exception as e:
            print(f"[AI助手] IPC 启动失败: {e}", flush=True)

        # 注入 wake 回调：wake 命令（含 gsettings Alt+S）-> 显示/前置窗口
        try:
            server.set_wake_callback(lambda: GLib.idle_add(self._show_window))
        except Exception as e:
            print(f"[AI助手] 注入 wake 回调失败: {e}", flush=True)

        # 全局快捷键（原版：GNOME Shell GrabAccelerator）
        self._accel = AcceleratorManager()
        if self._accel.is_available():
            self._accel.connect(self._on_accel_activated)
            for accel, cmd in (("<Alt>s", "wake"), ("<Alt>t", "screenshot"), ("<Alt>d", "context")):
                aid = self._accel.register(accel, cmd)
                if aid is not None:
                    self._accel_ids[aid] = cmd
            print(f"[AI助手] 快捷键已注册: {self._accel_ids}", flush=True)
        else:
            print("[AI助手] GNOME Shell 加速器不可用，依赖 gsettings", flush=True)

    def do_shutdown(self):
        if self._accel:
            self._accel.unregister_all()
            self._accel = None
        Gtk.Application.do_shutdown(self)

    def do_activate(self, *_a):
        if self.win is None:
            self.win = KeyWindow(self, f"http://127.0.0.1:{self._port}/")
            self.add_window(self.win)          # 注册到应用
            self.win.connect("close-request", self._on_close)
        # 应用无条件常驻：hold 使窗口关闭/隐藏都不退出，保证后台检测/快捷键持续
        self.hold()
        if self.start_hidden:
            self.win.hide()
        else:
            self.win.present()
        if self.pending_cmd:
            GLib.timeout_add(200, lambda: (self._run_pending() or False))

    def _on_close(self, *_a):
        self.win.hide()  # 仅隐藏窗口，不销毁（hold 保证应用常驻）
        return True

    def _on_accel_activated(self, aid):
        cmd = self._accel_ids.get(aid)
        if cmd:
            import threading as _th
            print(f"[AI助手] 快捷键: {cmd}", flush=True)
            if cmd == "wake":
                GLib.idle_add(self._show_window)
            else:
                _th.Thread(target=self._run_cmd, args=(cmd,), daemon=True).start()

    def _show_window(self):
        if self.win:
            self.win.present()
        return False

    def _run_pending(self):
        if self.win and self.pending_cmd:
            self._on_accel_activated_pending(self.pending_cmd)
            self.pending_cmd = None
        return False

    def _on_accel_activated_pending(self, cmd):
        # 冷启动命令（如 --screenshot）在窗口就绪后由主实例处理
        if cmd == "wake":
            self._show_window()
        else:
            import threading as _th
            _th.Thread(target=self._run_cmd, args=(cmd,), daemon=True).start()

    def _run_cmd(self, cmd):
        try:
            server._handle_ipc(cmd)
            print(f"[AI助手] 已处理命令: {cmd}", flush=True)
        except Exception as e:
            print(f"[AI助手] 处理命令失败 {cmd}: {e}", flush=True)


def main():
    args = sys.argv[1:]
    hidden = "--hidden" in args
    cmd = None
    for flag in ("--screenshot", "--wake", "--context"):
        if flag in args:
            cmd = flag.lstrip("-")
            break

    if cmd:
        try:
            if IPCClient.send(cmd):
                print(f"[AI助手] IPC 已发送命令: {cmd}", flush=True)
                return 0
        except Exception:
            pass
        print(f"[AI助手] 无后台实例，将启动后台检测并处理: {cmd}", flush=True)

    app = KeyApp(start_hidden=hidden, pending_cmd=cmd)
    gtk_argv = [sys.argv[0]]
    for a in sys.argv[1:]:
        if a.startswith("--gdk-") or a.startswith("--gtk-") or a in ("--help", "--version"):
            gtk_argv.append(a)
    code = app.run(gtk_argv)
    return code or 0


if __name__ == "__main__":
    sys.exit(main())
