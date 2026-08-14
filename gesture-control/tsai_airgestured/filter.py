"""卡尔曼滤波降噪。

对应用户「算法后处理层」的 21 点卡尔曼滤波：对每个手部关键点做独立、
轻量的时序平滑，抑制单帧突变噪声并保留有效手势轨迹。

实现一个可复用的 ``Kalman1D``（对应每个坐标分量一个滤波器），以及
对 21 点二维/三维关键点批量封装的 ``KalmanFilter``。

参数（文档语义）:
    ``process_noise``（过程噪声 Q）: 抖动越小越平滑
    ``measure_noise``（观测噪声 R）: 噪声越大越平滑

"""

from __future__ import annotations

import numpy as np

__all__ = ["Kalman1D", "KalmanFilter"]


class Kalman1D:
    """一维常量速度卡尔曼滤波器。"""

    def __init__(self, t_0: float = 0.0, process_noise: float = 5e-3,
                 measurement_noise: float = 1e-2) -> None:
        # 状态: [位置, 速度]
        self.x = np.array([t_0, 0.0], dtype=np.float64)
        self.P = np.eye(2, dtype=np.float64) * 1.0
        self.Q = np.array([[process_noise, 0.0], [0.0, process_noise]], dtype=np.float64)
        self.R = measurement_noise
        self.A = np.array([[1.0, 1.0], [0.0, 1.0]], dtype=np.float64)  # dt=1 步进
        self.H = np.array([[1.0, 0.0]], dtype=np.float64)

    def predict(self) -> None:
        """预测步骤（在观测前调用，推进状态）。"""
        self.x = self.A @ self.x
        self.P = self.A @ self.P @ self.A.T + self.Q

    def update(self, z: float) -> float:
        """更新步骤，返回滤波后估计。"""
        pred, _ = self.x[0], self.P[0, 0]
        s = self.P[0, 0] + self.R
        k = self.P[0, 0] / s if s > 0 else 0.0
        residual = z - pred
        self.x[0] += k * residual
        self.x[1] += k * residual  # 速度修正，简化处理
        self.P[0, 0] *= (1.0 - k)
        self.P[1, 1] *= (1.0 - k)
        return self.x[0]

    def reset(self, z: float) -> None:
        """重置到给定观测值。"""
        self.x[:] = [z, 0.0]


class KalmanFilter:
    """对 ``(N, D)`` 关键点序列的批量卡尔曼滤波。

    实例化后调用 :meth:`track` 得到平滑结果；内部对每个坐标分量维护
    独立的 ``Kalman1D``。
    """

    def __init__(self, num_points: int = 21, dim: int = 3,
                 process_noise: float = 5e-3, measurement_noise: float = 1e-2) -> None:
        self._filters = [
            Kalman1D(process_noise=process_noise, measurement_noise=measurement_noise)
            for _ in range(num_points * dim)
        ]
        self.num_points = num_points
        self.dim = dim
        self._inited = False
        self._prev = np.zeros((num_points, dim), dtype=np.float64)

    def reset_all(self, keypoints: np.ndarray = None) -> None:
        """重置所有滤波器；可选依据给定关键点初始化。"""
        self._inited = False
        if keypoints is not None:
            kp = np.asarray(keypoints, dtype=np.float64).reshape(-1)
            for i, val in enumerate(kp):
                if i < len(self._filters):
                    self._filters[i].reset(val)
            self._inited = True
            self._prev = np.asarray(keypoints, dtype=np.float64).reshape(self._prev.shape)

    def track(self, keypoints: np.ndarray) -> np.ndarray:
        """对输入 ``(N, D)`` 关键点做一帧滤波，返回平滑后的 ``(N, D)``。

        首帧直接透传并将其作为初始状态；后续帧先预测再更新。
        """
        kp = np.asarray(keypoints, dtype=np.float64)
        flat = kp.reshape(-1)
        out = np.empty_like(flat)
        for i, val in enumerate(flat):
            if i >= len(self._filters):
                continue
            f = self._filters[i]
            if not self._inited:
                f.reset(val)
                out[i] = val
            else:
                f.predict()
                out[i] = f.update(val)
        self._inited = True
        self._prev = out.reshape(kp.shape)
        return self._prev

    @property
    def smoothed(self) -> np.ndarray:
        return self._prev
