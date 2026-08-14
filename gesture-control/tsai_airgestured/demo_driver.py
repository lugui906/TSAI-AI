"""自测驱动：无摄像头/模型时的完整链路验证。

使用 ``DemoCamera``（脚本化轨迹）+ ``DemoBackend``（合成关键点），
真实走完 采集->推理->滤波->状态机->分类->输出 全链路，并把手势
动作对 DBus（MPRIS 播放/暂停）的触发打印出来。

适合 CI/本地验证用途，不依赖任何硬件。

"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .config import Config
from .demo_camera import DemoSource
from .filter import KalmanFilter
from .gesture import GestureClassifier, GestureType
from .inference import DemoBackend, Inference
from .output import OutputLayer
from .state_machine import MachineState, StateMachine, StateMachineConfig

logger = logging.getLogger("tsai.demo")


class DemoDriver:
    """构造一个可自动运行的手势链路（demo 数据）。"""

    def __init__(self, cfg: Config, output: OutputLayer,
                 pattern: str = "push") -> None:
        self.cfg = cfg
        self.output = output
        self.pattern = pattern
        self.running = False

        self.inference = Inference(min_detect_conf=0.5, min_track_conf=0.6)
        # 用 demo 后端替换，并注入轨迹来源
        demo = DemoBackend()
        self.demo_src = DemoSource(fps=30, pattern=pattern)
        demo.attach(self.demo_src)
        self.inference.backend = self.inference_backend = demo

        self.kalman = KalmanFilter()
        self.classifier = GestureClassifier(
            cool_down_ms=cfg.get_int("inference", "cool_down_ms", 500),
            push_threshold=cfg.get_float("inference", "push_threshold", 0.05),
            vertical_frac=cfg.get_float("inference", "vertical_frac", 0.3),
            rearm_sec=float(cfg.get_float("inference", "rearm_sec", 2.0)),
        )
        self.camera = None  # demo 不使用物理摄像头

        smc = StateMachineConfig(sleep_after_sec=3.0)
        self.state_machine = StateMachine(smc)
        self._fps = 30
        self._frame_interval = 1.0 / self._fps
        self._events = []

    # ------------------------------------------------------------------
    def setup(self) -> None:
        self.demo_src.start()

    def _fire(self, gesture: GestureType) -> None:
        gname = gesture.value
        if not self.cfg.gesture_enabled("gesture_" + gname):
            return
        result = self.output.dispatch(gname)
        logger.info("[DEMO] gesture=%s -> %s", gname, result)
        self._events.append((time.monotonic(), gname, result))

    # ------------------------------------------------------------------
    def run(self, seconds: Optional[float] = None) -> list:
        """运行 ``seconds`` 秒（默认跑完一个来回）。返回触发事件列表。"""
        deadline = time.monotonic() + (seconds or 6.0)
        while self.running and time.monotonic() < deadline:
            self.tick(time.monotonic())
            time.sleep(self._frame_interval)
        return self._events

    def stop(self) -> None:
        self.running = False

    def tick(self, now: float) -> None:
        # 注意：轨迹推进由 DemoBackend.track 内部的 phase() 完成，这里不再重复调用
        hd = self.inference.track_hand(self.demo_src.make_frame())
        if hd.detected:
            hd.keypoints = self.kalman.track(hd.keypoints)
        st = self.state_machine.on_processed(hd, now)
        if st is MachineState.WAKE and self.state_machine.cooldown_ok and hd.detected:
            g = self.classifier.classify(hd.keypoints.astype(float),
                                         center=hd.center,
                                         hand_span=hd.hand_span)
            if g:
                self.state_machine.enter_gesture()
                self._fire(g.type)
