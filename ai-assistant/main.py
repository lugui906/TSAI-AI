import os
import sys

import gi

gi.require_version("Gtk", "4.0")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ipc import Client
from ui import AssistantApp

LOG = "[AI助手]"


def log(msg):
    print(f"{LOG} {msg}", flush=True)


def main():
    args = sys.argv[1:]
    hidden = "--hidden" in args
    cmd = None
    for flag in ("--screenshot", "--wake", "--context"):
        if flag in args:
            cmd = flag
            break

    if cmd:
        log(f"收到命令: {cmd}, 尝试 IPC 发送...")
        if Client.send(cmd):
            log("IPC 发送成功，后台实例已处理")
            return 0
        log("IPC 发送失败，将启动新实例")

    app = AssistantApp(start_hidden=hidden, pending_cmd=cmd)
    log(f"启动应用: hidden={hidden}, pending_cmd={cmd}")
    # 过滤自定义参数，只传 GTK 能识别的选项
    gtk_argv = [sys.argv[0]]
    for a in sys.argv[1:]:
        if a.startswith("--gdk-") or a.startswith("--gtk-") or a == "--help" or a == "--version":
            gtk_argv.append(a)
    code = app.run(gtk_argv)
    log(f"应用退出, code={code}")
    return code or 0


if __name__ == "__main__":
    sys.exit(main())
