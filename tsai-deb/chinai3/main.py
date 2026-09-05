import os
import random
import socket
import sys
import threading
import time

import gi

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if "/usr/chindows" not in sys.path:
    sys.path.insert(0, "/usr/chindows")

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("WebKit", "6.0")

from gi.repository import Gdk, GLib, Gtk, WebKit  # noqa: E402

import server  # noqa: E402
from chindows_theme import style as chstyle  # noqa: E402
from chindshell import shell as _cshell  # noqa: E402


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _rand_gradient(dark=False):
    """随机生成 天蓝 → 粉色 渐变。

    浅色：比较浅的天蓝→粉；暗色：暗蓝→暗紫（与主题深色设计一致）。
    """
    if dark:
        sky = f"hsl({random.randint(210, 235)}, {random.randint(35, 55)}%, {random.randint(24, 32)}%)"
        pink = f"hsl({random.randint(315, 345)}, {random.randint(35, 55)}%, {random.randint(26, 34)}%)"
    else:
        sky = f"hsl({random.randint(185, 210)}, {random.randint(30, 48)}%, {random.randint(88, 94)}%)"
        pink = f"hsl({random.randint(325, 350)}, {random.randint(34, 52)}%, {random.randint(92, 97)}%)"
    angle = random.randint(0, 359)
    return (sky, pink), angle


class ChinAI3Window(Gtk.Window):
    def __init__(self, url):
        super().__init__(title="ChinAI3")
        self.set_default_size(980, 680)
        self.set_size_request(760, 500)

        settings = WebKit.Settings()
        settings.set_javascript_can_open_windows_automatically(False)
        settings.set_enable_back_forward_navigation_gestures(False)

        web = WebKit.WebView(settings=settings)
        web.set_background_color(Gdk.RGBA(0, 0, 0, 0))

        def on_load(w, event):
            if event == WebKit.LoadEvent.FINISHED:
                w.evaluate_javascript(_cshell.CTX_MENU_JS, -1, None, None, None, None, None)

        web.connect("load-changed", on_load)
        web.load_uri(url)
        self.set_child(web)


def main():
    port = _free_port()
    # 支持 --msg "..."：打开窗口后自动开启新对话并发送该消息
    msg = ""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a in ("--msg", "-m") and i + 1 < len(argv):
            msg = argv[i + 1]
            break
    if msg:
        import urllib.parse as _up
        url = f"http://127.0.0.1:{port}/?auto=1&msg={_up.quote(msg)}"
    else:
        url = f"http://127.0.0.1:{port}/"

    GLib.set_prgname("com.tsai.chinai3")
    Gtk.Window.set_default_icon_name("chinai3")

    t = threading.Thread(
        target=lambda: server.app.run(host="127.0.0.1", port=port, threaded=True),
        daemon=True,
    )
    t.start()
    time.sleep(0.8)

    chstyle.apply_gtk4()
    try:
        dark = chstyle.detect_dark_mode()
    except Exception:
        dark = False
    colors, angle = _rand_gradient(dark=dark)
    chstyle.apply_gradient_gtk4(colors=colors, angle=angle)
    print(f"[ChinAI3] 服务: {url} | 渐变: {colors}", flush=True)

    loop = GLib.MainLoop()
    win = ChinAI3Window(url)

    def on_close(_w):
        loop.quit()
        return False

    win.connect("close-request", on_close)
    win.present()
    loop.run()


if __name__ == "__main__":
    main()
