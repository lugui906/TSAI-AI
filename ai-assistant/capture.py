import os
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib

OUT_DIR = os.path.expanduser("~/.cache/ai-assistant")
os.makedirs(OUT_DIR, exist_ok=True)

TESS_LANGS = "chi_sim+eng"


def next_path(ext="png"):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(OUT_DIR, f"shot-{stamp}-{int(time.time() * 1000)}.{ext}")


def ocr_text(path):
    try:
        p = subprocess.run(
            ["tesseract", path, "stdout", "-l", TESS_LANGS],
            capture_output=True,
            timeout=180,
        )
        return p.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _idle_call(fn, *args):
    """Dispatch fn to the GTK main loop exactly once."""

    def run():
        fn(*args)
        return False

    GLib.idle_add(run)


def run_screenshot(on_done, on_error):
    def worker():
        target = next_path("png")
        try:
            p = subprocess.run(
                ["gnome-screenshot", "-a", "-f", target],
                capture_output=True,
                timeout=300,
            )
        except Exception as e:
            _idle_call(on_error, str(e))
            return
        if p.returncode != 0:
            err = (p.stderr or b"").decode("utf-8", "replace").strip()
            _idle_call(on_error, err or "截图失败")
            return
        if not os.path.exists(target) or os.path.getsize(target) == 0:
            _idle_call(on_error, "截图为空")
            return
        text = ocr_text(target)
        _idle_call(on_done, target, text)

    threading.Thread(target=worker, daemon=True).start()
