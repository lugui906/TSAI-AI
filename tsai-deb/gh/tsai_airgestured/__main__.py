"""命令行入口。

用法::

    tsai-airgestured                      # 以守护进程方式运行
    tsai-airgestured --config PATH        # 指定配置文件
    tsai-airgestured --demo [手势序列]     # 无摄像头/模型的自测模式
    tsai-airgestured --check              # 自检：模型/摄像头/输出后端
    tsai-airgestured --version

Demo 模式示例::

    tsai-airgestured --demo push,scroll_up,scroll_down

"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import Optional

from . import CONFIG_PATH, __version__
from .config import Config
from .output import OutputLayer

log_fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=log_fmt)
logger = logging.getLogger("tsai.main")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tsai-airgestured",
                                description="TSAI-OS 隔空手势离线守护进程")
    p.add_argument("-c", "--config", default=CONFIG_PATH, help="配置文件路径")
    p.add_argument("--demo", nargs="?", const="push,scroll_up,scroll_down",
                   metavar="GESTURES", help="自测模式（无摄像头/模型）")
    p.add_argument("--check", action="store_true", help="运行环境自检后退出")
    p.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    p.add_argument("--monitor", action="store_true",
                   help="实时打印中心/位移/Z/手宽诊断（利于标定阈值）")
    p.add_argument("--version", action="version", version=f"tsai-airgestured {__version__}")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    cfg = Config(path=args.config, auto_reload=True)

    if args.check:
        return run_check(cfg)

    output = OutputLayer()

    if args.demo is not None:
        from .demo_driver import DemoDriver
        driver = DemoDriver(cfg, output, pattern=args.demo)
    else:
        from .driver import GestureDriver
        driver = GestureDriver(cfg, output)
    driver.monitor = args.monitor

    driver.running = True
    driver.setup()

    def _stop(*_a) -> None:
        logger.info("shutting down")
        driver.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        driver.run()
    except KeyboardInterrupt:
        pass
    finally:
        driver.stop()
        try:
            driver.camera.release()
        except Exception:
            pass
    return 0


def run_check(cfg: Config) -> int:
    """自检并打印各环节就绪状态。"""
    from .camera import Camera
    from .inference import Inference

    print("== TSAI airgestured 自检 ==")
    print(f"配置文件 : {cfg.path}")
    device = cfg.get_str("camera", "device", "/dev/video0")
    cam = Camera(device)
    ok = cam.open(320, 240, 5)
    print(f"摄像头   : {device} -> {'OK' if ok else '不可用（可尝试 --demo）'}")
    cam.release()

    inf = Inference()
    print(f"推理后端 : {type(inf.backend).__name__}  "
          f"{'(DEMO)' if inf.backend.__class__.__name__ == 'DemoBackend' else ''}")

    out = OutputLayer()
    print(f"DBus     : {'OK' if out.has_dbus else '不可用'}")
    print(f"xdotool  : {out.xdo or '不可用'}")
    print(f"ydotool  : {out.ydo or '不可用'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())