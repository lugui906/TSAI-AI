import os
import sys

sys.path.insert(0, "/usr/chindows")
sys.path.insert(0, "/usr/chindows/clockai")

import server  # noqa: E402
from chindshell import shell  # noqa: E402


def main():
    shell.run(
        app_id="com.tsai.ai-timer",
        prgname="com.tsai.ai-timer",
        title="AI 定时器",
        icon="alarm-clock",
        server_module=server,
    )


if __name__ == "__main__":
    main()
