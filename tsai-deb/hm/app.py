#!/usr/bin/env python3
"""TSAI-OS 会议概括 — HTML 套壳入口（独立 Flask 服务）。"""
import os
import sys

sys.path.insert(0, "/usr/chindows")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402
from chindshell import shell  # noqa: E402


def main():
    shell.run(
        app_id="com.tsai.meeting-hm",
        prgname="com.tsai.meeting-hm",
        title="TSAI-OS 会议概括",
        icon="audio-input-microphone",
        server_module=server,
    )


if __name__ == "__main__":
    main()
