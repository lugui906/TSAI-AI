"""AI 推理层（纯本地 CPU 离线推理）。

对应用档文档「AI 推理层」：双模型分级调度 ——
  * ``palm_detection_lite.tflite``：手掌检测（SLEEP/闻言运行，低分辨率 5FPS）
  * ``hand_landmark_lite.tflite``：21 点手部关键点（WAKE/高分辨率 30FPS）

模型默认部署于 ``/usr/share/tsai-airgestured/models``（可用环境变量 ``TSAI_MODEL_DIR``
覆盖，或放入仓库内 ``models/`` 目录），禁止在线下载。

后端抽象
--------
为兼顾可移植与可测试：
  * ``OpenCVTfliteBackend``：通过 OpenCV DNN（``readNetFromTFLite``）加载
    INT8 ``.tflite`` 模型，无第三�扩展依赖；模型缺失时仅告警并可跳过。
  * ``DemoBackend``：无模型/无摄像头时的确定性测试后端，基于 demo 轨迹
    合成 21 点关键点，供本地验证状态机与手势链路。

二者产出统一的 :class:`HandResult` 数据结构，上层无需关心后端差异。

"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import MODEL_DIR
from .camera import Frame

logger = logging.getLogger("tsai.inference")

PALM_MODEL = "palm_detection_lite.tflite"
LANDMARK_MODEL = "hand_landmark_lite.tflite"

# 21 个手部关键点的语义（MediaPipe 惯例，索引即各路关节）
LANDMARK_NAMES = [
    "wrist", "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
    "index_mcp", "index_pip", "index_dip", "index_tip",
    "middle_mcp", "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp", "ring_pip", "ring_dip", "ring_tip",
    "pinky_mcmcp", "pinky_pip", "pinky_dip", "pinky_tip",
]


@dataclass
class HandData:
    """一次推理结果，统一规范化的手部数据。

    属性
    ----
    detected:
        是否检测到可信手掌。
    confidence:
        检测/跟踪置信度。
    keypoints:
        ``(21, 3)`` 归一化坐标 (x, y, z)，z 为视觉相对深度（无 ToF，不可用于绝对距离）。
    visibility:
        ``(21,)`` 每个关键点的可见/跟踪置信度。
    center:
        手掌归一化中心 (x, y)。
    hand_span:
        手掌在画面中的绝对尺寸（归一化到帧宽），来自 palm 检测框。
        用作滑动/前推位移的归一化单位（与 landmark 输出尺度无关）。
    """

    detected: bool = False
    confidence: float = 0.0
    keypoints: np.ndarray = field(default_factory=lambda: np.zeros((21, 3), dtype=np.float32))
    visibility: np.ndarray = field(default_factory=lambda: np.zeros(21, dtype=np.float32))
    center: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float32))
    hand_span: float = 0.0


class Inference:
    """推理门面：按阶段选择后端与模型，并对输出做置信度过滤。

    参数
    ----
    model_dir:
        模型目录；缺失模型时自动回落 demo 后端。
    min_detect_conf / min_track_conf:
        最小检测/跟踪置信度（低于则丢弃该帧）。
    """

    def __init__(self, model_dir: str = MODEL_DIR,
                 min_detect_conf: float = 0.5,
                 min_track_conf: float = 0.6) -> None:
        self.model_dir = model_dir
        self.min_detect_conf = min_detect_conf
        self.min_track_conf = min_track_conf
        self.backend = self._build_backend()

    def _build_backend(self):
        if self._models_present():
            try:
                return OpenCVTfliteBackend(self.model_dir)
            except Exception as exc:
                logger.warning("tflite model load failed, fallback demo: %s", exc)
        else:
            logger.info("no models installed -> demo backend (test mode)")
        return DemoBackend()

    def _models_present(self) -> bool:
        return os.path.isfile(os.path.join(self.model_dir, PALM_MODEL)) and \
            os.path.isfile(os.path.join(self.model_dir, LANDMARK_MODEL))

    # ------------------------------------------------------------------
    def detect_hand(self, frame: Frame) -> HandData:
        """SLEEP 态：仅手掌检测，返回低置信度 ROI。"""
        return self.backend.detect(frame)

    def track_hand(self, frame: Frame) -> HandData:
        """WAKE 态：全量关键点回归，返回 21 点。"""
        hd = self.backend.track(frame)
        if hd.detected and hd.confidence < self.min_track_conf:
            return HandData(detected=False, confidence=hd.confidence)
        return hd


class OpenCVTfliteBackend:
    """使用 OpenCV DNN 加载 ``.tflite`` 的推理后端。

    ``.tflite`` 为 INT8 量化模型，OpenCV DNN 后端在网络内部直接执行
    INT8 运算，无需额外运行时。

    流水线（对应 MediaPipe 官方 hand_tracking）：
      1. palm_detection_lite：192x192 全图手掌检测（SSD head），解码出
         手在画面中的绝对位置（见 :mod:`.palm_detector`）。
      2. 以检测框为 ROI 裁出手部区域并放大到 landmark 输入尺寸。
      3. hand_landmark_lite：对 ROI 回归 21 点，映射回原图得到绝对关键点。

    恢复「绝对位置」是本后端的核心——仅跑 landmark 全图只能得到以手中心为
    原点的结构，无法判定滑动位移。
    """

    PALM_INPUT = 192
    LAND_INPUT = 224
    PALM_SCORE_THRESH = 0.5      # 高于静态角落噪声(~0.27)即可，避免漏检真实手
    MIN_PALM_SPAN = 0.06          # 手掌最小尺寸（占画面宽比例），过滤极小可疑框
    ROI_PAD = 2.2  # landmark 裁剪边长 = 手部短边 * 该系数（预留手指空间）

    def __init__(self, model_dir: str) -> None:
        import cv2
        self._cv2 = cv2
        self._net = cv2.dnn.readNetFromTFLite(os.path.join(model_dir, PALM_MODEL))
        self._land = cv2.dnn.readNetFromTFLite(os.path.join(model_dir, LANDMARK_MODEL))
        from .palm_detector import decode_and_select
        self._palm_decode = decode_and_select

    # ------------------------------------------------------------------
    def _detect_palm(self, frame: Frame):
        """返回手在模型(192x192)归一化坐标下的 :class:`Palm`，或 None。"""
        import cv2
        blob = cv2.dnn.blobFromImage(frame.image, 1.0 / 255.0,
                                     (self.PALM_INPUT, self.PALM_INPUT),
                                     (0, 0, 0), swapRB=False)
        self._net.setInput(blob)
        raw_boxes = self._net.forward("Identity")     # (1, 2016, 18)
        raw_scores = self._net.forward("Identity_1")  # (1, 2016, 1)
        return self._palm_decode(raw_boxes, raw_scores,
                                 score_thresh=self.PALM_SCORE_THRESH)

    def detect(self, frame: Frame) -> HandData:
        """SLEEP 态：仅手掌检测，返回绝对手部中心。"""
        p = self._detect_palm(frame)
        if p is None or max(p.w, p.h) < self.MIN_PALM_SPAN:
            return HandData(detected=False)
        return HandData(detected=True, confidence=p.score,
                        center=p.center.astype(np.float32),
                        hand_span=float(max(p.w, p.h)))

    def track(self, frame: Frame) -> HandData:
        """WAKE 态：手掌检测 + ROI 关键点回归，返回绝对坐标。"""
        p = self._detect_palm(frame)
        if p is None or max(p.w, p.h) < self.MIN_PALM_SPAN:
            return HandData(detected=False)
        ih, iw = frame.image.shape[:2]

        # —— 由手掌框构造方形 ROI（原图像素坐标系）——
        px_cx = float(p.x_center * iw)
        px_cy = float(p.y_center * ih)
        side = max(float(p.w * iw), float(p.h * ih)) * self.ROI_PAD
        half = side / 2.0
        x0 = max(0, int(px_cx - half)); x1 = min(iw, int(px_cx + half))
        y0 = max(0, int(px_cy - half)); y1 = min(ih, int(px_cy + half))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return HandData(detected=False)

        import cv2
        crop = frame.image[y0:y1, x0:x1]
        blob = cv2.dnn.blobFromImage(crop, 1.0 / 255.0,
                                     (self.LAND_INPUT, self.LAND_INPUT),
                                     (0, 0, 0), swapRB=False)
        self._land.setInput(blob)
        kp_out = self._land.forward("Identity")      # (1, 63)
        score_out = self._land.forward("Identity_1")  # (1, 1)

        kp = np.asarray(kp_out, dtype=np.float32).reshape(21, 3)
        # —— 把 ROI 内归一化关键点映射回原图（归一化到帧宽/高）——
        cw = x1 - x0; ch = y1 - y0
        abs_x = (kp[:, 0] * cw + x0) / iw
        abs_y = (kp[:, 1] * ch + y0) / ih
        kp_abs = np.stack([abs_x, abs_y, kp[:, 2]], axis=1).astype(np.float32)
        try:
            conf = float(np.asarray(score_out, dtype=np.float32).reshape(-1)[0])
        except Exception:
            conf = 0.6
        # 中心采用手掌框中心（绝对位置，随移动真实变化）
        center = np.array([px_cx / iw, px_cy / ih], dtype=np.float32)
        return HandData(detected=True, confidence=conf,
                        keypoints=kp_abs, center=center,
                        hand_span=float(max(p.w, p.h)))


def _parse_landmark(outs) -> HandData:
    """解析手部关键点输出为 (21,3) + visibility，并校验有效性。

    兼容不同张量布局；若关键点 x/y 全为 0（无有效手）则视为未检测，避免误唤醒。
    """
    arr = _flat(outs)
    if arr is None or arr.size < 21 * 3:
        return HandData(detected=False)
    kp = arr[:63].reshape(21, 3)
    if not np.any(np.linalg.norm(kp[:, :2], axis=1) > 1e-5):
        return HandData(detected=False)
    vis = arr[63:84] if arr.size >= 84 else np.full(21, 0.9)
    conf = float(np.clip(np.mean(vis), 0.0, 1.0))
    return HandData(detected=True, confidence=conf,
                    keypoints=kp.astype(np.float32),
                    visibility=vis.astype(np.float32),
                    center=kp[:, :2].mean(axis=0).astype(np.float32))


def _flat(value) -> Optional[np.ndarray]:
    """把后端返回的张量摊平成 1 维数组；失败返回 None。"""
    try:
        return np.asarray(value, dtype=np.float32).reshape(-1)
    except Exception:
        return None


class DemoBackend:
    """确定性测试后端：由 demo 轨迹合成关键点，供链路测试。"""

    def __init__(self) -> None:
        self._tracker: Optional[object] = None  # 注入 DemoSource

    def attach(self, source) -> None:
        """挂接 DemoSource 以提供实时轨迹真值。"""
        self._tracker = source

    # ------------------------------------------------------------------
    def detect(self, frame: Frame) -> HandData:
        return HandData(detected=True, confidence=0.95,
                        keypoints=self._center_frame(frame))

    def track(self, frame: Frame) -> HandData:
        name, p = self._tracker.phase()
        cx, cy, cz = self._tracker._cur  # 状态化中心
        kp = self._make_keypoints(float(cx), float(cy), float(cz))
        span = float(getattr(self._tracker, "_span", 0.2))  # demo 合成 palm 尺寸
        vis = np.full(21, 0.98, dtype=np.float32)
        return HandData(detected=True, confidence=0.9,
                        keypoints=kp, visibility=vis, center=np.array([cx, cy]),
                        hand_span=span)

    @staticmethod
    def _make_keypoints(cx: float, cy: float, cz: float) -> np.ndarray:
        """围绕手掌中心合成 21 点固定开手结构（含相对 z 渐变）。"""
        kp = np.zeros((21, 3), dtype=np.float32)
        kp[:, 0] = cx
        kp[:, 1] = cy
        kp[:, 2] = cz
        # 掌根 MCP（供掌宽归一化）
        kp[9, 0] += 0.05   # 中指 MCP
        kp[17, 0] += -0.05  # 尾指 MCP
        # 张手：指尖沿 x 散开
        for i, dx in zip((4, 8, 12, 16, 20), [0.05, 0.02, -0.02, -0.05, -0.08]):
            kp[i, 0] += dx
        return kp

    @staticmethod
    def _center_frame(frame: Frame) -> np.ndarray:
        return np.zeros((21, 3), dtype=np.float32)
