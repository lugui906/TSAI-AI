"""手掌检测在线诊断：直读当前画面的 palm 检测原始得分与框，用于排查识别问题。

用法：
    python3 tools/palm_diag.py
把手掌放到镜头前，观察 best 一行：
    best score=0.92 box=(0.34,0.28) w/h=(0.31,0.29)
score 越高越是可信手掌；w/h 是占画面宽度/高度的比例（手应在 0.1~0.5）。
若 score 一直 <0.5 且框都很小/在边缘，说明没检测到完整张开的掌。
"""

import sys
import time

import cv2
import numpy as np

sys.path.insert(0, ".")
from tsai_airgestured.inference import OpenCVTfliteBackend
from tsai_airgestured.camera import Frame


def main() -> None:
    backend = OpenCVTfliteBackend("/usr/share/tsai-airgestured/models")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: cannot open /dev/video0")
        return
    print("diagnosing... 把手掌放到画面中央张开，观察 best 行")
    t0 = time.time()
    while time.time() - t0 < 12:
        ok, im = cap.read()
        if not ok:
            continue
        frame = Frame(np.asarray(im))
        best = None
        try:
            # 直接取 NMS 前/后原始结果的上界，便于观察不管阈值
            best = _report(backend, frame)
        except Exception as exc:
            print("ERR", exc)
        if best is not None:
            print(f"best {best}", flush=True)
        time.sleep(0.4)
    cap.release()


def _report(backend, frame):
    cv2 = backend._cv2
    blob = cv2.dnn.blobFromImage(frame.image, 1.0 / 255.0, (192, 192), (0, 0, 0), swapRB=False)
    backend._net.setInput(blob)
    raw_boxes = backend._net.forward("Identity")
    raw_scores = backend._net.forward("Identity_1")
    from tsai_airgestured.palm_detector import decode, nms
    dets = decode(raw_boxes, raw_scores)
    picked = nms(dets, score_thresh=0.2, iou_thresh=0.6)
    if picked is None or len(picked) == 0:
        return None
    best = picked[0]
    return (f"score={best[4]:.2f} center=({best[0]:.2f},{best[1]:.2f}) "
            f"w/h=({best[2]:.2f},{best[3]:.2f})  ndets={len(picked)}")


if __name__ == "__main__":
    main()