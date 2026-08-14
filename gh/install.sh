#!/usr/bin/env bash
# TSAI 隔空手势系统安装脚本
set -euo pipefail
cd "$(dirname "$0")"

PREFIX="${PREFIX:-/usr/local}"
CONF_DST="${CONF_DST:-/etc/tsai-airgestured.conf}"
SVC_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

echo ">> 安装 Python 包"
pip install --break-system-packages -e . 2>/dev/null || pip install -e . || \
  echo "（跳过 pip 安装，将使用 tools/tsai-airgestured 直接运行）"

echo ">> 安装命令行入口"
install -D -m 0755 tools/tsai-airgestured "$PREFIX/bin/tsai-airgestured"

echo ">> 安装全局配置（已存在则保留 .orig）"
if [[ -e "$CONF_DST" ]]; then
  cp -a "$CONF_DST" "$CONF_DST.orig"
fi
install -D -m 0644 etc/tsai-airgestured.conf "$CONF_DST"

echo ">> 安装 systemd 用户服务"
mkdir -p "$SVC_DIR"
install -D -m 0644 systemd/tsai-airgestured.service "$SVC_DIR/tsai-airgestured.service"

echo ">> 准备模型目录（需部署 .tflite，见 models/README.md）"
mkdir -p /usr/share/tsai-airgestured/models

cat <<EOF
完成。命令：
  自检          : $PREFIX/bin/tsai-airgestured --check
  调试运行      : $PREFIX/bin/tsai-airgestured --demo scroll_up,scroll_down
  服务          : systemctl --user enable --now tsai-airgestured
  设置面板      : python3 panel/tsai_settings.py
EOF