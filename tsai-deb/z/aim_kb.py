#!/usr/bin/env python3
"""AIM 知识库 — HTML 套壳入口（独立 Flask，支持多开）。"""
import os
import sys

sys.path.insert(0, "/usr/chindows")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402
from chindshell import shell  # noqa: E402


def main():
    shell.run(
        app_id="com.tsai.ai-knowledge",
        prgname="com.tsai.ai-knowledge",
        title="AI 知识库",
        icon="folder",
        server_module=server,
    )


if __name__ == "__main__":
    main()
