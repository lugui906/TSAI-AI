"""四状态严格状态机（防抖核心）。

对应文档「4.1 四状态状态机机制」。四状态互斥、自动轮转：

* ``SLEEP`` 休眠态（默认）：低帧率轻量推理，无手势执行逻辑。需连续
  5 帧稳定检测到手（置信度>0.6）才转入 ``WAKE``。
* ``WAKE`` 唤醒就绪态：全量推理，正等待手势；超过 ``sleep_after_sec``
  无手/无动作回到 ``SLEEP``。
* ``GESTURE`` 手势执行态：锁定手势判定并触发输出（带冷却）。
* ``IDLE`` 闲置过渡态：手势执行后进入；无新动作回 ``WAKE``，长期无手
  回落 ``SLEEP``。

本模块只实现纯状态迁移逻辑（不接触硬件/输出层），便于单元测试与仿真。

"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

__all__ = ["MachineState", "StateMachineConfig", "StateMachine"]


class MachineState(Enum):
    """系统对外状态（值域与 DBus StateChanged 通知一致）。"""
    SLEEP = "sleep"
    WAKE = "wake"
    GESTURE = "gesture"
    IDLE = "idle"


@dataclass
class StateMachineConfig:
    """状态机可调参数。

    ``sleep_camera`` / ``wake_camera`` 形如 ``(width, height, fps)``，
    用于驱动层切换采集规格（非本模块决策），此处仅保存。
    """

    wake_conf: float = 0.6          # 唤醒所需的检测置信度
    wake_streak: int = 5            # 唤醒所需的连续检测帧数
    sleep_after_sec: float = 3.0    # WAKE 无手/动作 -> SLEEP
    idle_to_wake_sec: float = 1.0   # IDLE 检测到新动作 -> WAKE
    idle_to_sleep_sec: float = 3.0  # IDLE 长期无手 -> SLEEP
    sleep_camera: tuple = (320, 240, 5)
    wake_camera: tuple = (640, 480, 30)


class StateMachine:
    """四状态状态机。

    驱动层每帧调用 :meth:`on_processed` 传入 :class:`HandData`，内部推进
    状态并更新计数；手势触发时调用 :meth:`enter_gesture`。状态变化通过
    ``on_state_change`` 回调通知（用于输出 UI/DBus 状态）。
    """

    def __init__(self, cfg: Optional[StateMachineConfig] = None,
                 on_state_change: Optional[Callable[[MachineState], Any]] = None) -> None:
        self.cfg = cfg or StateMachineConfig()
        self.state = MachineState.SLEEP
        self.on_state_change = on_state_change
        self._detect_streak = 0
        self._last_hand = 0.0
        self._gesture_since = 0.0
        self._hand_open = False
        self._cooldown_until = 0.0
        self._now = 0.0

    # ------------------------------------------------------------------
    def _transition(self, to: MachineState) -> None:
        if to == self.state:
            return
        self.state = to
        if self.on_state_change:
            try:
                self.on_state_change(to)
            except Exception:
                pass

    def reset(self) -> None:
        """回到默认 SLEEP 态并清零计数。"""
        self._detect_streak = 0
        self._now = 0.0
        self._transition(MachineState.SLEEP)

    # ------------------------------------------------------------------
    def on_processed(self, hand, now: Optional[float] = None) -> MachineState:
        """驱动层每帧调用；``hand`` 为 :class:`HandData`。返回当前状态。"""
        now = now if now is not None else self._now()
        self._now = now
        detected = bool(hand and hand.detected)

        if self.state is MachineState.SLEEP:
            if detected:
                self._detect_streak += 1
                if self._detect_streak >= self.cfg.wake_streak:
                    self._last_hand = now
                    self._transition(MachineState.WAKE)
            else:
                self._detect_streak = 0
            return self.state

        if self.state is MachineState.WAKE:
            if detected:
                self._last_hand = now
            elif now - self._last_hand > self.cfg.sleep_after_sec:
                self._detect_streak = 0
                self._transition(MachineState.SLEEP)
            return self.state

        if self.state is MachineState.GESTURE:
            # 手势执行后进入 IDLE 过渡态
            self._cooldown_until = now + 0.5  # 500ms 冷却兜底
            self._transition(MachineState.IDLE)
            return self.state

        if self.state is MachineState.IDLE:
            if detected:
                if now - self._last_hand > self.cfg.idle_to_wake_sec:
                    self._transition(MachineState.WAKE)
            elif now - self._last_hand > self.cfg.idle_to_sleep_sec:
                self._transition(MachineState.SLEEP)
            return self.state

        return self.state

    # ------------------------------------------------------------------
    def enter_gesture(self) -> None:
        """手势命中时由驱动层调用，切换到 GESTURE 执行态。"""
        self._transition(MachineState.GESTURE)

    @property
    def cooldown_ok(self) -> bool:
        """是否已过冷却期（允许再次触发手势）。"""
        return not self._now or self._now >= self._cooldown_until

    @classmethod
    def _clock(cls) -> float:
        import time as _t
        return _t.monotonic()

    # （对外）支持注入时间来源
    def _now(self) -> float:  # override 供测试注入时间
        import time as _t
        return _t.monotonic()
