#!/usr/bin/env python3
"""AI 智能体 — HTML 套壳入口（独立 Flask，支持多开）。"""
import os
import sys

sys.path.insert(0, "/usr/chindows")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402
from chindshell import shell  # noqa: E402


def main():
    shell.run(
        app_id="com.tsai.ai-agent",
        prgname="com.tsai.ai-agent",
        title="AI 智能体",
        icon="face-smile",
        server_module=server,
    )


if __name__ == "__main__":
    main()
