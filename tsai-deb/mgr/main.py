#!/usr/bin/env python3
"""AI 电脑管家 — chindshell 套壳入口（chinai3 风格）。

完整复刻原版 GTK 12 面板布局（左侧菜单导航 + 右侧面板），风格仿照 chinai3。
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for p in (BASE_DIR, "/usr/chindows"):
    if p not in sys.path:
        sys.path.insert(0, p)

import server  # noqa: E402
from chindshell import shell  # noqa: E402


def main():
    shell.run(
        app_id="com.aipc.manager",
        prgname="com.aipc.manager",
        title="AI 电脑管家",
        icon="computer",
        server_module=server,
        width=1100, height=750, min_w=820, min_h=560,
    )


if __name__ == "__main__":
    main()
