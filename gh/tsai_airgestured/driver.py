"""驱动主循环（核心协调线程）。

把 采集 -> 推理 -> 滤波 -> 状态机 -> 手势分类 -> 输出 串成一条事件循环，
并按文档「双状态节能调度 + 高负载丢帧保护」动态切换采集规格。

线程模型
----------
* 主循环线程：以目标 FPS 步进，处理一帧的全部流水线。
* 也支持 ``DemoDriver``：无摄像头时用 DemoSource + DemoBackend 走完整链路。

对外
----
状态变化通过 ``on_state_change`` 回调暴露 （供 UI / 日志 / DBus 同步）。

"""

from __future__ import annotations

import logging
import time

import numpy as np
from typing import Callable, Optional

from . import STATE_GESTURE, STATE_IDLE, STATE_SLEEP, STATE_WAKE
from .camera import Camera, Frame
from .config import Config
from .filter import KalmanFilter
from .gesture import GestureClassifier, GestureType
from .inference import Inference
from .output import OutputLayer
from .state_machine import MachineState, StateMachine, StateMachineConfig

logger = logging.getLogger("tsai.driver")


class GestureDriver:
    """驱动主循环。"""

    def __init__(self, cfg: Config, output: OutputLayer,
                 on_state_change: Optional[Callable[[str], None]] = None) -> None:
        self.cfg = cfg
        self.output = output
        self.on_state_change = on_state_change
        self.running = False

        # 推理与滤波
        self.inference = Inference(
            min_detect_conf=cfg.get_float("inference", "min_detect_conf", 0.5),
            min_track_conf=cfg.get_float("inference", "min_track_conf", 0.6),
        )
        self.kalman = KalmanFilter()
        self.classifier = GestureClassifier(
            cool_down_ms=cfg.get_int("inference", "cool_down_ms", 500),
            push_threshold=cfg.get_float("inference", "push_threshold", 0.05),
            vertical_frac=cfg.get_float("inference", "vertical_frac", 0.3),
            rearm_sec=float(cfg.get_float("inference", "rearm_sec", 2.0)),
        )
        self.state_machine = StateMachine(
            StateMachineConfig(
                sleep_after_sec=float(cfg.get_int("general", "sleep_timeout_sec", 3)),
            ),
            on_state_change=self._sm_ui,
        )
        self.camera = Camera(cfg.get_str("camera", "device", "/dev/video0"))
        self._sleep_fps = cfg.get_int("camera", "sleep_fps", 5)
        self._wake_fps = cfg.get_int("camera", "wake_fps", 30)
        self._fps = self._sleep_fps
        self._frame_interval = 1.0 / self._fps
        self._last_state: Optional[str] = None

    def _sm_ui(self, st: MachineState) -> None:
        """状态机变化 -> 转为 UI/DBus 状态。"""
        mapping = {
            MachineState.SLEEP: STATE_SLEEP,
            MachineState.WAKE: STATE_WAKE,
            MachineState.GESTURE: STATE_GESTURE,
            MachineState.IDLE: STATE_IDLE,
        }
        s = mapping[st]
        if s != self._last_state:
            self._last_state = s
            logger.info("state -> %s", s)
            self.output.emit_state(s)
            if self.on_state_change:
                self.on_state_change(s)

    # ------------------------------------------------------------------
    def setup(self) -> None:
        """以休眠态采集规格打开摄像头（失败时自动探测可用设备回落）。"""
        if self.camera.open(*self.cfg_stream()):
            return
        # 配置的设备不可用时自动探测可用摄像头（如 /dev/video0 是元数据设备）
        try:
            devs = self.camera.list_cameras()
        except Exception:
            devs = []
        if devs:
            logger.info("auto-detect camera: %s", devs[0])
            self.camera.device = devs[0]
            self.camera.open(*self.cfg_stream())

    def cfg_stream(self) -> tuple[int, int, int]:
        """按状态返回摄像头采集规格 (w, h, fps)。"""
        spec = self.state_machine.cfg.wake_camera if self.state_machine.state is not MachineState.SLEEP \
            else self.state_machine.cfg.sleep_camera
        return tuple(spec)

    def _set_fps(self, fps: int) -> None:
        self._fps = fps
        self._frame_interval = 1.0 / max(1, fps)

    # ------------------------------------------------------------------
    def run(self) -> None:
        """主循环（阻塞直到停止）。"""
        logger.info("gesture pipeline started (fps=%s)", self._fps)
        last_t = time.monotonic()
        while self.running:
            dead = time.monotonic() - last_t
            if dead < self._frame_interval:
                time.sleep(self._frame_interval - dead)
            last_t = time.monotonic()
            self.tick(last_t)

    def stop(self) -> None:
        self.running = False

    # ------------------------------------------------------------------
    def tick(self, now: float) -> None:
        """处理一帧：采集 -> 推理 -> 滤波 -> 状态机 -> 分类 -> 输出。"""
        frame = self.camera.read()
        if frame is None:
            # 采集失败：丢帧保护（高负载环境本循环不空转）
            self.state_machine.on_processed(None, now)
            return

        st = self.state_machine.state
        if st is MachineState.SLEEP:
            hand = self.inference.detect_hand(frame)
        else:
            hand = self.inference.track_hand(frame)

        # 关键点滤波（仅在有有效关键点时）
        if hand and hand.detected:
            hand.keypoints = self.kalman.track(hand.keypoints)
            hand.center = self._smooth_center(hand.center)

        nst = self.state_machine.on_processed(hand, now)

        # 按新状态切换循环帧率：WAKE 用高帧率保证轨迹足够密，休眠态降帧省电
        next_fps = self._wake_fps if nst is MachineState.WAKE else self._sleep_fps
        if next_fps != self._fps:
            self._set_fps(next_fps)

        # 手势分类：仅 WAKE/核心就绪态且冷却通过
        if nst is MachineState.WAKE and self.state_machine.cooldown_ok and hand and hand.detected:
            gesture = self.classifier.classify(hand.keypoints.astype(float),
                                               center=hand.center,
                                               hand_span=hand.hand_span)
            self._monitor(now, hand, gesture)
            if gesture and self.cfg.gesture_enabled("gesture_" + gesture.type.value):
                self.state_machine.enter_gesture()
                self._fire(gesture.type)

    def _smooth_center(self, center: np.ndarray) -> np.ndarray:
        """对 palm 中心做指数平滑（降低帧间抖动，位移信号更干净）。"""
        import numpy as np
        c = np.asarray(center, dtype=np.float64)
        if getattr(self, "_center_sm", None) is None:
            self._center_sm = c.copy()
        alpha = 0.5
        self._center_sm = alpha * c + (1.0 - alpha) * self._center_sm
        return self._center_sm.astype(np.float32)

    def _monitor(self, now: float, hand, gesture) -> None:
        """实时诊断：节流输出，展示为何某手势未触发（便于调参）。"""
        if getattr(self, "monitor", False):
            if now - getattr(self, "_mon_last", 0.0) >= 0.5:
                self._mon_last = now
                c = self.classifier
                traj = c._traj
                raw = np.zeros(2)
                if len(traj) >= 2:
                    raw = traj.displacement(0.5)
                nx = raw[0] / c.hand_span if abs(raw[0]) else 0.0
                ny = raw[1] / c.hand_span if abs(raw[1]) else 0.0
                growth = traj.span_growth(c.LOOKBACK_S) if len(traj) >= 2 else 1.0
                logger.info(
                    "MONITOR st=%-6s center=(%+.3f,%+.3f) rawMove=(%+.3f,%+.3f) "
                    "norm=(%+.2f,%+.2f) handW=%.3f grow=%.2f z=%+.3f th=%.2f -> %s",
                    self.state_machine.state.name, hand.center[0], hand.center[1],
                    raw[0], raw[1], nx, ny, c.hand_span, growth,
                    traj.z_change() if len(traj) else 0.0, c.push_threshold,
                    gesture.type.name if gesture else "none")

    # ------------------------------------------------------------------
    def _fire(self, gesture: GestureType) -> None:
        """执行一个手势对应的系统动作。"""
        gname = gesture.value
        if not self.cfg.gesture_enabled("gesture_" + gname):
            logger.info("gesture %s disabled in config", gname)
            return
        logger.info("gesture triggered: %s", gname)
        result = self.output.dispatch(gname)
        logger.info("gesture %s -> %s", gname, result)