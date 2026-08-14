# AI 模型部署说明

系统纯本地离线推理，模型**预装**于固定路径，运行零网络请求。

## 模型部署位置

    /usr/share/tsai-airgestured/models/
    ├── palm_detection_lite.tflite   手掌检测（轻量）INT8，约 80KB
    └── hand_landmark_lite.tflite    手部关键点回归 INT8，约 70KB

## 来源与许可

- 采用 Apache-2.0 许可的 MediaPipe 系列手部模型（INT8 量化版），
  可自由打包、修改、商用集成。
- 部署脚本 `scripts/deploy_models.sh` 负责从官方源校验并装载（可选）。

## 输入输出张量约定（推理后端校准依据）

推理后端 `OpenCVTfliteBackend` 使用 OpenCV DNN（`readNetFromTFLite`）
加载上述 `.tflite`，其预处理/后处理集中在 `tsai_airgestured/inference.py`
的 `_parse_detect` / `_parse_landmark`，部署自有模型时按下列 I/O 校准：

- **palm_detection_lite**：输入 192×192 归一化图；输出 6 元素
  （4 边界框归一化坐标 + 2 个滑动物理度量/置信度）。第 0 项为置信度，
  第 1..4 项为 box（见 `_parse_detect`）。
- **hand_landmark_lite**：输入裁剪后 ROI（建议 224×224）；输出 65 元素
  `[x0 y0 z0 vis0 ... x20 y20 z20 vis20]`，顺序即 MediaPipe
  ``LANDMARK_NAMES``（见 inference 常亮）。

> 注意：模型 Z 轴为视觉估算相对深度，无 ToF 能力；仅用于相对变化判定，
> 禁止用于绝对距离。

## 未装载模型的回落行为

若上述两个 `.tflite` 不存在，服务启动会自动回落 **DemoBackend**（测试
模式）：使用脚本化轨迹合成 21 点关键点，让 采集->滤波->状态机->手势
分类->输出 全链路可在无硬件/模型的环境下自测。可用：

    tsai-airgestured --demo push
    tsai-airgestured --check

## 已知限制与生产建议（重要）

1. **hand_landmark_lite 可用**：经 OpenCV DNN（`readNetFromTFLite`）
   可加载并输出真实 21 点回归（x/y/z）。其坐标为以图像中心为原点的
   相对值；位移/时长阈值需按模型实际输出量纲校准
   （`config.push_threshold` 即为入口）。

2. **palm_detection_lite 的解析受限**：该模型内置 MediaPipe 自定义
   后处理算子（anchor/解码），OpenCV DNN 的 TFLite 导入器无法正确解码
   这些算子，故允许给出**尽力而为**的检测结果（用于 SLEEP→WAKE 的松弛
   唤醒），但精度不保证。若需严格的手掌检测：

   - 优先在支持的环境安装 **`tflite-runtime`**（`pip install tflite-runtime`），
     用其官方 `Interpreter` 执行 palm 检测，可获得完整 anchor 解码；
   - 或在你的发行版用兼容 Python 版本安装，OpenCV backend 在 palm 不可靠时
     自动降级（系统配置 ``[inference]`` 无影响，核心手势仍可用 landmark）。

3. **Z 轴**为视觉估算相对深度（无 ToF），仅用于相对变化（前推判定），
   禁用绝对距离。