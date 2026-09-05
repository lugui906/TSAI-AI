"""MediaPipe palm_detection_lite 纯 numpy 后处理（无 tflite-runtime 依赖）。

原先 OpenCV DNN 无法解析 palm 模型（接口输出为 SSD 头：``(1, 2016, 18)`` 原始
回归 + ``(1, 2016, 1)`` 得分），绝对手部位置因此丢失（hand_landmark 输出以手
中心为原点）。本模块按 MediaPipe 官方 ``SsdAnchorsCalculator`` 与
``TensorsToDetectionsCalculator`` 的配置，用 numpy 完成 anchor 生成、box/keypoint
解码与非极大值抑制，恢复手在画面中的绝对位置。

模型配置（取自 palm_detection_cpu.pbtxt + SSD anchor 算法）：

* input 192x192，输出 ``(1, 2016, 18)`` + ``(1, 2016, 1)``
* anchors: num_layers=4, min_scale=0.1484375, max_scale=0.75,
  strides=[8,16,16,16], aspect_ratios=[1.0,0.5], fixed_anchor_size=true,
  offset 0.5, input 192 -> 共 2016 个
* decode: reverse_output_order=true, x/y/w/h_scale=192,
  box_coord_offset=0, keypoint_coord_offset=4, num_keypoints=7,
  num_values_per_keypoint=2, sigmoid_score=true
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

INPUT_SIZE = 192
NUM_ANCHORS = 2016
NUM_COORDS = 18
NUM_KEYPOINTS = 7

# --- SsdAnchorsCalculator 参数 ---
_MIN_SCALE = 0.1484375
_MAX_SCALE = 0.75
_STRIDES = (8, 16, 16, 16)
_ASPECT_RATIOS = (1.0, 0.5)
_ANCHOR_OFFSET = 0.5
_FIXED_ANCHOR_SIZE = True


def _calculate_scale(min_scale: float, max_scale: float, index: int,
                     num_strides: int) -> float:
    if num_strides == 1:
        return (min_scale + max_scale) * 0.5
    return min_scale + (max_scale - min_scale) * index / (num_strides - 1.0)


def generate_anchors() -> np.ndarray:
    """返回按 MediaPipe 输出顺序排列的 ``(NUM_ANCHORS, 4)`` 数组
    (x_center, y_center, w, h)。与 C++ ``GenerateAnchors`` 循环完全一致。"""
    anchors = []
    layer_id = 0
    num_layers = len(_STRIDES)
    while layer_id < num_layers:
        scales = []
        aspect_ratios = []
        last_same = layer_id
        while last_same < len(_STRIDES) and _STRIDES[last_same] == _STRIDES[layer_id]:
            scale = _calculate_scale(_MIN_SCALE, _MAX_SCALE, last_same, len(_STRIDES))
            for ar in _ASPECT_RATIOS:
                aspect_ratios.append(ar)
                scales.append(scale)
            last_same += 1

        anchor_w = []
        anchor_h = []
        for i in range(len(aspect_ratios)):
            rs = math.sqrt(aspect_ratios[i])
            anchor_h.append(scales[i] / rs)
            anchor_w.append(scales[i] * rs)

        stride = _STRIDES[layer_id]
        fm_h = math.ceil(1.0 * INPUT_SIZE / stride)
        fm_w = math.ceil(1.0 * INPUT_SIZE / stride)
        for y in range(fm_h):
            for x in range(fm_w):
                x_center = (x + _ANCHOR_OFFSET) / fm_w
                y_center = (y + _ANCHOR_OFFSET) / fm_h
                for aid in range(len(anchor_h)):
                    if _FIXED_ANCHOR_SIZE:
                        w = 1.0
                        h = 1.0
                    else:
                        w = anchor_w[aid]
                        h = anchor_h[aid]
                    anchors.append((x_center, y_center, w, h))
        layer_id = last_same
    arr = np.asarray(anchors, dtype=np.float32).reshape(-1, 4)
    if arr.shape[0] != NUM_ANCHORS:
        raise RuntimeError(
            f"generated {arr.shape[0]} anchors, expected {NUM_ANCHORS}")
    return arr


_ANCHORS = generate_anchors()


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -100.0, 100.0)
    return 1.0 / (1.0 + np.exp(-x))


def decode(raw_boxes: np.ndarray, raw_scores: np.ndarray) -> np.ndarray:
    """SSD 解码。
    参数：
        raw_boxes: ``(2016, 18)`` 或 ``(1, 2016, 18)``
        raw_scores: ``(2016, 1)`` 或 ``(1, 2016, 1)``
    返回：
        ``(2016, N)`` 数组，列为
        ``[x_center, y_center, w, h, score, kp0x, kp0y, ..., kp6x, kp6y]``
        （归一化坐标，相对 192x192 输入图）。
    """
    boxes = np.asarray(raw_boxes, dtype=np.float32).reshape(-1, NUM_COORDS)
    scores = _sigmoid(np.asarray(raw_scores, dtype=np.float32).reshape(-1, 1))

    if boxes.shape[0] != NUM_ANCHORS:
        raise ValueError(f"boxes rows {boxes.shape[0]} != {NUM_ANCHORS}")

    axc = _ANCHORS[:, 0]
    ayc = _ANCHORS[:, 1]
    aw = _ANCHORS[:, 2]
    ah = _ANCHORS[:, 3]

    # reverse_output_order=true -> 输入序为 (x_center, y_center, w, h)
    x_center = boxes[:, 0] / 192.0 * aw + axc
    y_center = boxes[:, 1] / 192.0 * ah + ayc
    w = boxes[:, 2] / 192.0 * aw
    h = boxes[:, 3] / 192.0 * ah

    kp = np.empty((NUM_ANCHORS, NUM_KEYPOINTS * 2), dtype=np.float32)
    for k in range(NUM_KEYPOINTS):
        off = 4 + k * 2
        kp[:, k * 2] = boxes[:, off] / 192.0 * aw + axc
        kp[:, k * 2 + 1] = boxes[:, off + 1] / 192.0 * ah + ayc

    return np.hstack([x_center[:, None], y_center[:, None],
                      w[:, None], h[:, None], scores,
                      kp])


def nms(dets: np.ndarray, score_thresh: float = 0.5,
        iou_thresh: float = 0.5) -> Optional[np.ndarray]:
    """对解码结果（行列见 :func:`decode`）做阈值 + 非极大值抑制。

    返回选中行的纵向数组（索引顺序即 dets 行号），无则返回 None。
    """
    if dets is None or dets.shape[0] == 0:
        return None
    keep = dets[:, 4] >= score_thresh
    dets = dets[keep]
    if dets.shape[0] == 0:
        return None
    x1 = dets[:, 0] - dets[:, 2] / 2.0
    y1 = dets[:, 1] - dets[:, 3] / 2.0
    x2 = dets[:, 0] + dets[:, 2] / 2.0
    y2 = dets[:, 1] + dets[:, 3] / 2.0
    scores = dets[:, 4]
    order = scores.argsort()[::-1]
    keep_idx = []
    while order.size > 0:
        i = order[0]
        keep_idx.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_i = (x2[i] - x1[i]) * (y2[i] - y1[i])
        area_j = (x2[order[1:]] - x1[order[1:]]) * (y2[order[1:]] - y1[order[1:]])
        union = area_i + area_j - inter
        iou = np.zeros_like(inter)
        nz = union > 0
        iou[nz] = inter[nz] / union[nz]
        order = order[1:][iou <= iou_thresh]
    return dets[keep_idx]


@dataclass
class Palm:
    """一个检测到的手掌（已在原始帧坐标系）。"""
    score: float
    x_center: float
    y_center: float
    w: float
    h: float
    keypoints: np.ndarray  # (7, 2) x,y 相对原始帧（归一化于帧宽/高）

    @property
    def center(self) -> np.ndarray:
        return np.array([self.x_center, self.y_center], dtype=np.float32)


def decode_and_select(raw_boxes: np.ndarray, raw_scores: np.ndarray,
                      score_thresh: float = 0.5
                      ) -> Optional[Palm]:
    """完整解码 + NMS，返回置信度最高（且非极大抑制后保留）的手掌。"""
    dets = decode(raw_boxes, raw_scores)
    picked = nms(dets, score_thresh=score_thresh)
    if picked is None or len(picked) == 0:
        return None
    best = picked[0]
    kp = best[5:].reshape(NUM_KEYPOINTS, 2)
    return Palm(score=float(best[4]), x_center=float(best[0]),
                y_center=float(best[1]), w=float(best[2]), h=float(best[3]),
                keypoints=kp.astype(np.float32))