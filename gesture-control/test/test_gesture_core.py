"""核心逻辑单元测试（无硬件/网络依赖）：

* 过滤：卡尔曼滤波降噪、单帧突变被抑制。
* 状态机：SLEEP->WAKE 需连续 N 帧，超时回落 SLEEP。
* 手势分类：前推播放/暂停（尺寸增长 + 近遮罩 + 横向位移小）。

> ``python test/test_gesture_core.py``

"""

from __future__ import annotations

import time

import numpy as np

from tsai_airgestured.filter import KalmanFilter
from tsai_airgestured.gesture import GestureClassifier, GestureType
from tsai_airgestured.state_machine import MachineState, StateMachine, StateMachineConfig


# ------------------------------------------------------------------ #
# 辅助
# ------------------------------------------------------------------ #
def make_kp(cx: float, cy: float, z: float = 0.0, scale: float = 1.0) -> np.ndarray:
    """构造与 demo 同构的 21x3 关键点（含掌根 MCP，供归一化）。

    ``scale`` >1 时手部结构整体放大（模拟向镜头前推，尺寸增长）。
    """
    kp = np.zeros((21, 3), dtype=np.float64)
    kp[:, 0] = cx
    kp[:, 1] = cy
    kp[:, 2] = z
    kp[9, 0] += 0.05 * scale    # 中指 MCP
    kp[17, 0] += -0.05 * scale  # 尾指 MCP
    for i, dx in zip((4, 8, 12, 16, 20), [0.05, 0.02, -0.02, -0.05, -0.08]):
        kp[i, 0] += dx * scale
    return kp


class Hand:
    def __init__(self, detected): self.detected = detected


# ------------------------------------------------------------------------- #
def test_kalman_smooths():
    kf = KalmanFilter(num_points=21, dim=3)
    base = np.full((21, 3), 0.5)
    kf.track(base)                       # 首帧初始化
    for _ in range(5):
        kf.track(base)
    spike = base.copy()
    spike[5, 0] += 0.5                   # 单帧大突变
    out = kf.track(spike)
    assert np.all(np.isfinite(out)), "滤波器输出含 NaN"
    assert abs(out[5, 0] - 0.5) < 0.5, "突变未被抑制"
    print("kalman: OK")


def test_state_machine_wake_and_sleep():
    sm = StateMachine(StateMachineConfig(wake_streak=5, sleep_after_sec=3.0))
    history = [1.0] * 4
    for i in history[:4]:                # 前 4 帧不足以唤醒
        sm.on_processed(Hand(True), float(i))
    assert sm.state is MachineState.SLEEP
    sm.on_processed(Hand(True), 5.0)     # 第 5 帧达标
    assert sm.state is MachineState.WAKE
    sm.on_processed(Hand(False), 5.1)    # 手离开
    sm.on_processed(Hand(False), 8.2)    # >3s 未检测到手
    assert sm.state is MachineState.SLEEP
    print("state machine: OK")


# ------------------------------------------------------------------ #
def test_push_light():
    """轻轻前推 = 手掌尺寸小幅增长（靠近镜头）且中心不动，即触发播放/暂停。"""
    cl = GestureClassifier(push_threshold=0.25)
    t0 = time.monotonic()
    hit = None
    for k in range(10):
        span = 0.2 + 0.15 * (k / 9)      # 轻推：尺寸增长 ~1.75x
        hit = cl.classify(make_kp(0.5, 0.5), t0 + k * 0.03, hand_span=span)
        if hit:
            break
    assert hit is not None and hit.type is GestureType.PLAYPAUSE, hit
    print("push(light): OK")


def test_push_growth():
    """前推 = 手部尺寸增长（靠近镜头）且中心不动。"""
    cl = GestureClassifier(push_threshold=0.25)
    t0 = time.monotonic()
    hit = None
    for k in range(10):
        span = 0.2 + 0.5 * (k / 9)       # 尺寸涨到接近 0.7 画面宽
        hit = cl.classify(make_kp(0.5, 0.5, scale=1.0 + 0.8 * (k / 9)),
                          t0 + k * 0.03, hand_span=span)
        if hit:
            break
    assert hit is not None and hit.type is GestureType.PLAYPAUSE, hit
    print("push(growth): OK")


def test_scroll_up():
    """手掌上滑：中心 Y 显著减小，触发页面上滚。"""
    cl = GestureClassifier(vertical_frac=0.3)
    t0 = time.monotonic()
    hit = None
    for k in range(20):
        cy = 0.5 - 0.35 * (k / 19)       # 向上移动
        hit = cl.classify(make_kp(0.5, cy), t0 + k * 0.02, hand_span=0.3)
        if hit:
            break
    assert hit is not None and hit.type is GestureType.SCROLL_UP, hit
    print("scroll_up: OK")


def test_scroll_down():
    """手掌下滑：中心 Y 显著增大，触发页面下滚。"""
    cl = GestureClassifier(vertical_frac=0.3)
    t0 = time.monotonic()
    hit = None
    for k in range(20):
        cy = 0.5 + 0.35 * (k / 19)       # 向下移动
        hit = cl.classify(make_kp(0.5, cy), t0 + k * 0.02, hand_span=0.3)
        if hit:
            break
    assert hit is not None and hit.type is GestureType.SCROLL_DOWN, hit
    print("scroll_down: OK")


def test_no_push_without_growth():
    """手不动（尺寸无增长）不应触发前推，防误触。"""
    cl = GestureClassifier(push_threshold=0.25, cool_down_ms=0)
    t0 = time.monotonic()
    hit = None
    for k in range(12):                  # 尺寸稳定，无增长
        hit = cl.classify(make_kp(0.5, 0.5), t0 + k * 0.03, hand_span=0.3)
        if hit:
            break
    assert hit is None, f"静止手不应触发前推: {hit}"
    print("push_no_growth: OK")


def test_push_rejects_lateral():
    """垂直滑动（位移大、尺寸稳定）应判为滑动而非前推。"""
    cl = GestureClassifier(push_threshold=0.25, vertical_frac=0.3, cool_down_ms=0)
    t0 = time.monotonic()
    hit = None
    for k in range(20):
        cy = 0.5 - 0.35 * (k / 19)       # 向上滑动
        hit = cl.classify(make_kp(0.5, cy), t0 + k * 0.02, hand_span=0.3)
        if hit:
            break
    assert hit is not None and hit.type is GestureType.SCROLL_UP, f"应判为滑动而非前推: {hit}"
    print("push_rejects_lateral(->scroll): OK")


def main():
    test_kalman_smooths()
    test_state_machine_wake_and_sleep()
    test_scroll_up()
    test_scroll_down()
    test_push_light()
    test_push_growth()
    test_no_push_without_growth()
    test_push_rejects_lateral()
    print("\nALL CORE TESTS PASSED")


if __name__ == "__main__":
    main()
