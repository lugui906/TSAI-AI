#!/usr/bin/env bash
# 模型部署脚本：从官方源校验并装载 INT8 手部模型。
# 默认离线模式（仅检查本地缓存目录），联网可用 --download。
#
# 用法：
#   ./scripts/deploy_models.sh --check        仅校验已部署的模型
#   ./scripts/deploy_models.sh --download     从官方发布下载（需网络）
set -euo pipefail

DEST=/usr/share/tsai-airgestured/models
PALM=palm_detection_lite.tflite
LAND=hand_landmark_lite.tflite
# MediaPipe legacy 官方模型地址（mediapipe-assets 桶，Apache-2.0）
PALM_URL="https://storage.googleapis.com/mediapipe-assets/palm_detection_lite.tflite?generation=1661875885885770"
LAND_URL="https://storage.googleapis.com/mediapipe-assets/hand_landmark_lite.tflite?generation=1661875766398729"

mkdir -p "$DEST"

need_download=0
for f in "$PALM" "$LAND"; do
  if [[ ! -s "$DEST/$f" ]]; then
    echo "!! 缺少模型: $f（放至 $DEST）"
    need_download=1
  else
    echo "OK  $f ($(du -h "$DEST/$f" | cut -f1))"
  fi
done

if [[ "$need_download" -eq 1 && "${1:-}" == "--download" ]]; then
  echo ">> 下载 MediaPipe 官方模型 (mediapipe-assets)..."
  # MediaPipe legacy 手部模型（Apache-2.0），带 generation 参数避免 CDN 缓存 404
  curl -fL -o "$DEST/$LAND" "$LAND_URL"
  curl -fL -o "$DEST/$PALM" "$PALM_URL"
  echo ">> 完成。校验文件:"
  ls -l "$DEST"
elif [[ "$need_download" -eq 1 ]]; then
  echo ">> 模型缺失。可用 --download 自动获取，或离线放入 $DEST（见 models/README.md）"
  exit 1
fi

echo "部署校验通过。"