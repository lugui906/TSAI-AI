"""摄像头采集层。

基于 OpenCV ``VideoCapture`` 实现，对应文档「硬件采集层」：
内置设备抢占检测、自动释放、定时重试，支持休眠/唤醒两种分辨率与帧率，
以及帧格式统一（BGR -> RGB 供推理）。

本采集层封装了与推理层解耦的 ``Frame`` 数据对象：无论后端是真实摄像头
还是测试桩，都能产出结构一致的帧。

"""

from __future__ import annotations

import glob
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("tsai.camera")


@dataclass
class Frame:
    """一帧原始数据 + 归一化图像。

    属性
    ----
    image:
        RGB 顺序、HxWx3 的 uint8 图像（已做 BGR->RGB 转换）。
    width / height:
        图像宽高。
    grayscale:
        WxH 灰度图（供手掌检测后端使用的可选项）。
    timestamp:
        采集时间戳（秒）。
    """

    image: np.ndarray
    width: int = 0
    height: int = 0
    grayscale: Optional[np.ndarray] = None
    timestamp: float = field(default_factory=time.time)


class Camera:
    """OpenCV 摄像头封装。

    参数
    ----
    device:
        摄像头设备标识，形如 ``/dev/video0`` 或整数索引。
        传入 ``"demo"`` 时启动确定性测试源（见 ``DemoCamera``）。
    """

    def __init__(self, device: str) -> None:
        self.device = device
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._is_demo = device.lower().startswith("demo")
        self._retry_delay = 2.0
        self.recent_error: Optional[str] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def open(self, width: int, height: int, fps: int) -> bool:
        """以指定分辨率/帧率打开摄像头。返回是否成功。"""
        if self._is_demo:
            logger.info("Demo camera source selected")
            return True
        with self._lock:
            try:
                self.release_locked()
                index = self._to_index(self.device)
                cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                cap.set(cv2.CAP_PROP_FPS, fps)
                if not cap.isOpened():
                    cap.release()
                    self.recent_error = f"cannot open {self.device}"
                    return False
                self._cap = cap
                self.recent_error = None
                return True
            except Exception as exc:  # 设备断开/占用异常
                self.recent_error = str(exc)
                logger.warning("open failed: %s", exc)
                return False

    @staticmethod
    def _to_index(device: str) -> int:
        """把设备路径或纯数字转成 OpenCV 索引整数。"""
        if device.isdigit():
            return int(device)
        for tail in ("/dev/video", "/dev/media"):
            if device.startswith(tail):
                rest = device[len(tail):]
                if rest.isdigit():
                    return int(rest)
        raise ValueError(f"unsupported device spec: {device}")

    # ------------------------------------------------------------------
    # 设备自动探测
    # ------------------------------------------------------------------
    @classmethod
    def list_cameras(cls) -> list[str]:
        """自动探测可用的摄像头设备，返回 ``/dev/videoN`` 路径列表。

        逐个尝试以 V4L2 打开，仅保留真正能打开的采集设备；
        通常 ``/dev/video0`` 可能是元数据设备，真正的采集口可能是
        ``video1`` 等，因此按探测结果为准。
        """
        found: list[str] = []
        for path in sorted(glob.glob("/dev/video*")):
            try:
                idx = cls._to_index(path)
                cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                ok = bool(cap.isOpened())
                cap.release()
                if ok:
                    found.append(path)
            except Exception:
                continue
        return found

    @staticmethod
    def device_label(path: str) -> str:
        """返回设备的友好名（读 /sys/class/video4linux/videoN/name），失败回退路径。"""
        name_file = os.path.join("/sys/class/video4linux", os.path.basename(path), "name")
        try:
            with open(name_file) as f:
                name = f.read().strip()
            if name:
                return f"{path} - {name}"
        except Exception:
            pass
        return path

    def release(self) -> None:
        """释放摄像头资源。"""
        if self._is_demo:
            return
        with self._lock:
            self.release_locked()

    def release_locked(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    @property
    def available(self) -> bool:
        return bool(self._cap) if not self._is_demo else True

    def can_retry(self) -> bool:
        """是否处于可重试状态（被抢占/失败后延时重试）。"""
        return not self.available

    # ------------------------------------------------------------------
    # 采集
    # ------------------------------------------------------------------
    def read(self) -> Optional[Frame]:
        """读取一帧。失败返回 None（由上层决定降级/丢帧）。"""
        if self._is_demo:
            return None  # Demo 由外部合成帧
        if self._cap is None:
            return None
        try:
            ok, img = self._cap.read()
        except Exception:
            return None
        if not ok or img is None:
            return None
        return self._postprocess(img)

    @staticmethod
    def _postprocess(img: np.ndarray) -> Frame:
        """统一 BGR -> RGB，缓存灰度图，记录尺寸。"""
        h, w = img.shape[:2]
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        return Frame(image=rgb, width=w, height=h, grayscale=gray)