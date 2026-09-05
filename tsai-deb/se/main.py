#!/usr/bin/env python3
"""AI 模型管理器 — chindshell 套壳入口（chinai3 风格）。

完整复刻原版 GTK 4 个 tab：默认模型 / AIM 引擎 / 自定义 Provider / Zen 免费模型。
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
        app_id="org.chindows.se-model-manager",
        prgname="org.chindows.se-model-manager",
        title="AI 模型管理器",
        icon="preferences-system",
        server_module=server,
        width=760, height=620, min_w=560, min_h=440,
    )


if __name__ == "__main__":
    main()
