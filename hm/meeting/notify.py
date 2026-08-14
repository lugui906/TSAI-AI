"""Desktop notification with rate-limiting / cooldown.

Prevents notification spam: repeated notifications are only pushed once per
cooldown window, so loops firing `notify()` cannot flood the desktop.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

logger = logging.getLogger("meeting.notify")

APP_NAME = "TSAI-OS 会议纪要"

# min seconds between two notifications with the same body
_COOLDOWN_SAME = 20.0
# min seconds between any two notifications at all
_COOLDOWN_ANY = 3.0

_state = {"any_time": 0.0, "same": None, "same_time": 0.0}


def _throttled(body: str) -> bool:
    now = time.monotonic()
    if now - _state["any_time"] < _COOLDOWN_ANY:
        return False
    if _state["same"] == body and now - _state["same_time"] < _COOLDOWN_SAME:
        return False
    _state["any_time"] = now
    _state["same"] = body
    _state["same_time"] = now
    return True


def notify(summary: str, body: str = "会议纪要已更新",
           force_fallback: bool = False) -> bool:
    """Push a desktop notification via notify-send, rate-limited."""
    if not _throttled(body):
        return False

    tool = shutil.which("notify-send")
    if tool is None and not force_fallback:
        logger.info("notify-send unavailable; skipping notification")
        return False
    if tool is None:
        logger.info("AI NOTIFY: %s - %s", body, summary)
        return True
    try:
        subprocess.run(
            [tool, "-a", APP_NAME, body, summary[:200]],
            check=False, timeout=5,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("notification failed: %s", exc)
        return False