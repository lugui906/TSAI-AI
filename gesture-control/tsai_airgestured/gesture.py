"""手势分类判定算法（前推播放/暂停 + 上下滑动滚动）。

对应用户文档「4.2 手势分类判定算法」。当前系统保留两个手势：

* 前推播放/暂停：手掌向镜头轻轻前推——palm 尺寸小幅增长且横向
  位移小——即触发媒体播放/暂停。
* 上滑/下滑滚动：手掌垂直甩动——中心 Y 位移达阈值、轨迹单向——
  触发页面上滚/下滚。

判定顺序：先判滑动（垂直位移大、尺寸稳定），再判前推（尺寸增长、
位移小）；两者物理上互斥。

输出统一 :class:`GestureEvent`。判定器为「无状态输入、有状态缓存」——
内部维护最近数帧轨迹，供尺寸增长与位移判定。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

__all__ = ["GestureType", "GestureEvent", "GestureClassifier"]


class GestureType(Enum):
    """系统支持的全部隔空手势。"""
    PLAYPAUSE = "playpause"
    SCROLL_UP = "scroll_up"
    SCROLL_DOWN = "scroll_down"


@dataclass
class GestureEvent:
    """一个已触发的手势事件。"""
    type: GestureType
    timestamp: float = field(default_factory=time.time)


class _Traj:
    """最近一段时间中心点轨迹（供尺寸增长 / 位移判定）。"""

    MAX_AGE_S = 0.6

    def __init__(self) -> None:
        self._t: list[float] = []
        self._xy: list[np.ndarray] = []
        self._zs: list[float] = []
        self._spans: list[float] = []

    def push(self, now: float, xy: np.ndarray, z: float, span: float) -> None:
        self._t.append(now)
        self._xy.append(np.asarray(xy, dtype=np.float64).copy())
        self._zs.append(float(z))
        self._spans.append(float(span))
        while self._t and (now - self._t[0] > self.MAX_AGE_S):
            self._t.pop(0); self._xy.pop(0); self._zs.pop(0); self._spans.pop(0)

    def __len__(self) -> int:
        return len(self._t)

    def duration(self) -> float:
        """当前轨迹的时间跨度（秒）。"""
        return self._t[-1] - self._t[0] if len(self._t) >= 2 else 0.0

    def displacement(self, lookback_s: float) -> np.ndarray:
        """当前点相对 ``lookback_s`` 前的位移向量。"""
        if len(self._t) < 2:
            return np.zeros(2)
        head = self._t[-1]
        start = head - lookback_s
        idx = 0
        for i in range(len(self._t) - 1, -1, -1):
            if self._t[i] <= start:
                idx = i
                break
        if idx >= len(self._xy) - 1:
            idx = 0
        return self._xy[-1][:2] - self._xy[idx][:2]

    def z_change(self) -> float:
        """窗口内 Z 总变化量（正值表示深度减小/靠近）。"""
        return self._zs[0] - self._zs[-1] if len(self._zs) >= 2 else 0.0

    def span_growth(self, lookback_s: float) -> float:
        """窗口内手部尺寸增长率 = 当前尺寸 / 回溯点尺寸（>1 表示手变大/靠近）。"""
        if len(self._spans) < 2:
            return 1.0
        head = self._t[-1]
        start = head - lookback_s
        idx = 0
        for i in range(len(self._t) - 1, -1, -1):
            if self._t[i] <= start:
                idx = i
                break
        if idx >= len(self._spans) - 1:
            idx = 0
        s0 = self._spans[idx]
        return (self._spans[-1] / s0) if s0 > 1e-6 else 1.0


class GestureClassifier:
    """无状态（含内部轨迹状态）隔空手势分类器（前推暂停 + 上下滑动）。

    参数
    ----
    push_threshold:
        前推判定：手掌尺寸增长率需超过该值（如 0.05 = 尺寸增长 5%）。
        越小越灵敏（轻轻前推即触发）。
    vertical_frac:
        上下滑动专属位移阈值（中心 Y 位移 / 手宽，越小越好触发）。
    cool_down_ms:
        手势触发后的冷却时间（防连击）。
    rearm_sec:
        手势结束后重新开启捕捉前需等待的秒数（防止收手回撤/连击误触发）。
    """

    LOOKBACK_S = 0.35      # 尺寸增长 / 位移判定的回溯窗口（秒，短=更灵敏）
    LAT_MOVES_FRAC = 0.3   # 前推期间横向位移需小于该值（手部宽度倍数）
    MIN_HAND_SPAN = 0.06   # 手掌最小尺寸（占画面宽比例），仅过滤极小误检框
    SPAN_ALPHA = 0.85      # 手宽指数平滑系数（越高越跟手，轻推立即反映在尺寸上）
    MIN_DUR_S = 0.12       # 滑动动作最小时长（秒）
    MAX_DUR_S = 0.6        # 滑动动作最大时长（秒）
    UNIDIR_MIN = 0.35      # 滑动单向度下限（净位移/累计路径，拒绝来回抖动）
    TRAJ_STALE_S = 0.5     # 超过此间隔未分类则视为「新手势」：重置平滑基线

    def __init__(self, push_threshold: float = 0.05,
                 vertical_frac: float = 0.3,
                 cool_down_ms: int = 500,
                 rearm_sec: float = 2.0) -> None:
        self.push_threshold = push_threshold
        self.vertical_frac = vertical_frac
        self.cool_down_s = cool_down_ms / 1000.0
        self.rearm_sec = rearm_sec
        self._traj = _Traj()
        self._last_emit = 0.0
        self._rearm_until = 0.0  # 手势后重新捕捉的时间点（单调时钟）
        self._span_sm: float | None = None  # 平滑后的手宽
        self._last_classify = 0.0  # 最近一次 classify 的时钟，用于识别「新手势」
        # 归一化尺度（每帧更新）
        self.hand_span: float = 1e-3

    def update_thresholds(self, push_threshold: float | None = None,
                          vertical_frac: float | None = None,
                          cool_down_ms: int | None = None) -> None:
        """配置热重载时动态更新阈值。"""
        if push_threshold is not None:
            self.push_threshold = push_threshold
        if vertical_frac is not None:
            self.vertical_frac = vertical_frac
        if cool_down_ms is not None:
            self.cool_down_s = cool_down_ms / 1000.0

    # ------------------------------------------------------------------
    def _fallback_span(self, kp: np.ndarray) -> float:
        """无 palm 框时的退化尺寸：指尖到腕部最大距离（归一化单位）。"""
        wrist = kp[0, :2]
        tips = kp[[4, 8, 12, 16, 20], :2]
        return float(np.max(np.linalg.norm(tips - wrist, axis=1))) or 1e-3

    # ------------------------------------------------------------------
    def classify(self, keypoints: np.ndarray, now: float | None = None,
                 center: np.ndarray | None = None,
                 hand_span: float | None = None) -> Optional[GestureEvent]:
        """按一帧（已滤波后的）关键点判定手势。命中返回事件，否则 None。

        判定顺序：先滑动（垂直位移大、尺寸稳定），后前推（尺寸增长、
        位移小）。两者物理互斥，互不抢占。
        """
        now = now if now is not None else time.monotonic()
        kp = np.asarray(keypoints, dtype=np.float64)
        if kp.ndim != 2 or len(kp) == 0 or kp.shape[1] < 3:
            return None
        if center is None:
            center = kp[:, :2].mean(axis=0)
        # 归一化单位：优先用 palm 检测的绝对手部尺寸，其次关键点跨度
        raw_span = (float(hand_span) if hand_span and hand_span > 1e-6
                    else self._fallback_span(kp))
        # 手宽指数平滑：抑制检测抖动，保留「轻推」带来的持续增长。
        # 分类间隔过长（上一手势已结束/手离开重来）时重置基线，
        # 避免陈旧平滑值继续收敛造成的假「增长」误触发。
        if self._span_sm is None or (now - self._last_classify > self.TRAJ_STALE_S):
            self._span_sm = raw_span
        else:
            self._span_sm = (self.SPAN_ALPHA * raw_span
                             + (1.0 - self.SPAN_ALPHA) * self._span_sm)
        self._last_classify = now
        self.hand_span = self._span_sm
        z = float(kp[:, 2].mean())
        self._traj.push(now, center, z, self.hand_span)

        if now - self._last_emit < self.cool_down_s:
            return None  # 冷却期，禁止连击触发
        if now < self._rearm_until:
            return None  # 手势后等待 rearm_sec 再开启捕捉

        event = self._judge_slide()
        if event:
            return event
        return self._judge_push()

    # ------------------------------------------------------------------
    def _judge_slide(self) -> Optional[GestureEvent]:
        """上下滑动：中心 Y 位移达阈值、轨迹单向、动作时长达标。"""
        dur = self._traj
        if len(dur) < 3 or not (self.MIN_DUR_S <= dur.duration() <= self.MAX_DUR_S):
            return None
        if self.hand_span < self.MIN_HAND_SPAN:
            return None
        # 收手（尺寸明显缩小）时不判滑动，防「收手被捕捉」
        if dur.span_growth(self.LOOKBACK_S) < 0.5:
            return None
        pts = np.asarray(dur._xy, dtype=np.float64)[:, :2]
        if len(pts) < 3:
            return None
        inc = np.diff(pts, axis=0)
        path_y = float(np.sum(np.abs(inc[:, 1])))
        net_y = float(pts[-1, 1] - pts[0, 1])
        my = net_y / self.hand_span
        consist = net_y / path_y if path_y > 1e-9 else 0.0
        if abs(my) > self.vertical_frac and abs(consist) > self.UNIDIR_MIN:
            return self._emit(GestureType.SCROLL_UP if my < 0
                              else GestureType.SCROLL_DOWN)
        return None

    # ------------------------------------------------------------------
    def _judge_push(self) -> Optional[GestureEvent]:
        # 前推 = 手向镜头靠近：手掌尺寸「小幅增长」且横向位移小。
        # 不做「盖住镜头」尺寸要求——轻轻前推即可触发播放/暂停。
        if len(self._traj) < 3:
            return None
        if self.hand_span < self.MIN_HAND_SPAN:
            return None  # 太小：多半是误检框，忽略
        growth = self._traj.span_growth(self.LOOKBACK_S)
        slide = np.linalg.norm(self._traj.displacement(self.LOOKBACK_S))
        slide_norm = slide / self.hand_span
        if (growth - 1.0 > self.push_threshold) and (slide_norm < self.LAT_MOVES_FRAC):
            return self._emit(GestureType.PLAYPAUSE)
        return None

    def _emit(self, t: GestureType) -> GestureEvent:
        self._last_emit = time.monotonic()
        self._rearm_until = self._last_emit + self.rearm_sec
        return GestureEvent(type=t)