#!/usr/bin/env bash
# 把 /usr/chindows 打包为 ZIP（直接 zip，无需暂存副本）。
# 用法: sudo ./build_zip.sh [--lite]
#   --lite  剔除大体积运行时产物（aai 模型 / l squashfs / aim 构建产物），适合分发包
set -euo pipefail

SRC="/usr/chindows"
PKG="$SRC/packaging"
OUT="$PKG/dist"
STAMP=$(date +%Y%m%d-%H%M%S)
LITE=0
[ "${1:-}" = "--lite" ] && LITE=1

mkdir -p "$OUT"
ZIP="$OUT/chindows-$STAMP.zip"

EXCLUDES=(
  "*/__pycache__/*"
  "*.pyc"
  "*.pyo"
  "*.egg-info/*"
  "*/data/workdir/*"
  "packaging/dist/*"
  "packaging/*.zip"
  "*.log"
  # AI 模型为运行时大体积产物，始终不打进 ZIP（安装时也不覆盖本机模型）
  "aai/share/models/*"
)
if [ "$LITE" = 1 ]; then
  echo "==> --lite: 剔除大体积运行时产物"
  EXCLUDES+=("l/*" "aim/build/*")
fi

EXC_ARGS=()
for p in "${EXCLUDES[@]}"; do EXC_ARGS+=("-x" "$p"); done

echo "==> 压缩中（全量: $SRC）…"
cd "$SRC"
zip -qr "$ZIP" . "${EXC_ARGS[@]}"
chmod 644 "$ZIP"
echo "==> 已生成: $ZIP ($(du -h "$ZIP" | cut -f1))"
echo "    安装: sudo $PKG/install.sh $ZIP"
