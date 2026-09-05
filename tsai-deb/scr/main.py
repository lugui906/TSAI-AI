#!/usr/bin/env python3
"""AI 屏幕控制 — HTML 套壳入口（独立 Flask，支持多开）。"""
import os
import sys

sys.path.insert(0, "/usr/chindows")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402
from chindshell import shell  # noqa: E402


def main():
    shell.run(
        app_id="com.tsai.ai-screen-control",
        prgname="com.tsai.ai-screen-control",
        title="AI 屏幕控制",
        icon="remote-desktop",
        server_module=server,
    )


if __name__ == "__main__":
    main()
