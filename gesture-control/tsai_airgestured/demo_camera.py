"""确定性测试帧源。

对应用 ``device`` 配置为 ``demo`` 时的接管：不依赖真实摄像头，通过
脚本化轨迹合成手势，用于在本机无摄像头的环境中验证 状态机 -> 滤波 ->
手势分类 -> 输出 的完整链路。

实际 21 点关键点由 ``inference`` 的 demo 后端基于同一轨迹合成，使整条
流水线可端到端自测。

"""

from __future__ import annotations

import time

import numpy as np

from .camera import Frame

__all__ = ["DemoSource"]


class DemoSource:
    """非硬件测试源：按预定动作序列定时产出合成帧与轨迹真值。"""

    GESTURE_DURATION_SEC = 0.4  # 每个手势动作时长（ms 级别验证 120-600）
    IDLE_DURATION_SEC = 1.0

    def __init__(self, fps: int = 30, pattern: str = "") -> None:
        self.fps = max(1, int(fps))
        names = (pattern or "idle").split(",")
        # 自动在每个手势之间插入 idle 停顿，使状态机有足够时间轮转
        self._schedule: list[tuple[str, float]] = []
        for n in names:
            self._schedule.append((n, self.GESTURE_DURATION_SEC))
            if n != "idle":
                self._schedule.append(("idle", self.IDLE_DURATION_SEC))
        self._ti = 0.0
        self._cur = np.array([0.5, 0.5, 0.0], dtype=np.float64)  # 当前中心（有状态）
        self._span = 0.2  # 模拟 palm 宽度（占画面宽比例），push 时增长

    def start(self) -> None:
        self._ti = time.monotonic()
        self._cur[:] = [0.5, 0.5, 0.0]
        self._span = 0.2

    # ------------------------------------------------------------------
    def phase(self) -> tuple[str, float]:
        """推进一帧并返回 (当前动作名, 该动作内归一化进度 0..1)。

        内部同步更新 ``_cur`` 中心：idle 保持上一手势终点，避免突变导致
        位移误判。
        """
        elapsed = time.monotonic() - self._ti
        total = 0.0
        for name, dur in self._schedule:
            if elapsed < total + dur:
                p = max(0.0, min(1.0, (elapsed - total) / dur))
                self._apply(name, p)
                return name, p
            total += dur
        last_name, last_dur = self._schedule[-1] if self._schedule else ("idle", self.IDLE_DURATION_SEC)
        p = max(0.0, min(1.0, (elapsed - total) / last_dur))
        self._apply(last_name, p)
        return last_name, p

    def _apply(self, name: str, p: float) -> None:
        """把动作进度映射为中心坐标/尺寸；idle 保持当前位置。"""
        if name == "idle":
            return  # 保持 _cur 与 _span
        start = self._cur.copy()
        end = start.copy()
        if name == "scroll_up":
            end[1] -= 0.35
        elif name == "scroll_down":
            end[1] += 0.35
        elif name == "push":
            # 前推：中心略靠上 + 深度靠近；palm 尺寸显著增长（接近盖住镜头）
            end[2] -= 0.25
            self._span = 0.2 + 0.35 * p
        self._cur = start + (end - start) * p

    def make_frame(self) -> Frame:
        """制作一帧空画面（真实像素仅占位，手势真值在 inference 层合成）。"""
        return Frame(image=np.zeros((240, 320, 3), dtype=np.uint8))
