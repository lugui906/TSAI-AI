"""快捷键注册脚本 — 使用 gsettings 注册 Alt+T（截图）和 Alt+S（唤醒）"""
import json
import os
import shlex
import subprocess
import sys

GS_BASE = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_PREFIX = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"

SHOT = "aiassist-shot"
WAKE = "aiassist-wake"
CTXT = "aiassist-context"


def _gsettings(*args):
    subprocess.run(["gsettings", *args], check=False, capture_output=True)


def setup(script_path):
    script_path = os.path.abspath(script_path)
    shot_path = CUSTOM_PREFIX + SHOT + "/"
    wake_path = CUSTOM_PREFIX + WAKE + "/"
    ctxt_path = CUSTOM_PREFIX + CTXT + "/"
    _gsettings("set", GS_BASE, "custom-keybindings",
               json.dumps([shot_path, wake_path, ctxt_path]))

    cmd_shot = "python3 %s --screenshot" % shlex.quote(script_path)
    cmd_wake = "python3 %s --wake" % shlex.quote(script_path)
    cmd_ctxt = "python3 %s --context" % shlex.quote(script_path)
    for path, name, binding, cmd in (
        (shot_path, "AI助手·截图", "<Alt>t", cmd_shot),
        (wake_path, "AI助手·唤醒", "<Alt>s", cmd_wake),
        (ctxt_path, "AI助手·界面上下文", "<Alt>d", cmd_ctxt),
    ):
        key = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:%s" % path
        _gsettings("set", key, "name", name)
        _gsettings("set", key, "binding", binding)
        _gsettings("set", key, "command", cmd)

    autostart_dir = "/etc/xdg/autostart"
    os.makedirs(autostart_dir, exist_ok=True)
    desktop = """[Desktop Entry]
Type=Application
Name=AI助手
Comment=AI 助手后台常驻（Alt+S 唤醒，Alt+T 截图，Alt+D 界面上下文）
Exec=python3 %s --hidden
X-GNOME-Autostart-enabled=true
""" % script_path
    with open(os.path.join(autostart_dir, "ai-assistant.desktop"), "w") as f:
        f.write(desktop)

    print("快捷键已注册：Alt+T 截图 / Alt+S 唤醒 / Alt+D 界面上下文；已添加自启动")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 1:
        print("usage: shortcuts.py <main.py路径>")
        sys.exit(1)
    setup(args[0])
