#!/usr/bin/env bash
# chindows 更新/安装脚本：解包 ZIP → 覆盖 /usr/chindows → 自动安装应用菜单(desktop)。
# 用法: sudo ./install.sh [chindows-*.zip]    缺省自动取 packaging/dist 里最新的 zip
set -euo pipefail

INSTALL_DIR="/usr/chindows"
PKG="$INSTALL_DIR/packaging"
APPS_DIR="/usr/share/applications"

[ "$(id -u)" = 0 ] || { echo "需要 root 运行"; exit 1; }

ZIP="${1:-}"
if [ -z "$ZIP" ]; then
  ZIP=$(ls -t "$PKG"/dist/chindows-*.zip 2>/dev/null | head -1 || true)
fi
if [ -z "$ZIP" ] || [ ! -f "$ZIP" ]; then
  echo "找不到 ZIP。用法: sudo $0 <chindows-*.zip>"
  exit 1
fi
echo "==> 安装包: $ZIP"

# 1) 解包到安装目录（覆盖同名文件，保留额外的旧文件；
#    始终排除 aai/share/models —— 模型是本机运行时数据，绝不覆盖）
echo "==> 解包（保留本机 aai/share/models 模型）…"
unzip -q -o "$ZIP" -d "$INSTALL_DIR" -x "aai/share/models/*"
echo "==> 模型目录保持不动: $INSTALL_DIR/aai/share/models"

# 2) 权限与可执行位
chown -R root:root "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/ainote2/main" 2>/dev/null || true
chmod +x "$INSTALL_DIR/l/token-monitor.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/packaging/build_zip.sh" "$INSTALL_DIR/packaging/install.sh" 2>/dev/null || true

# 3) 清理 __pycache__ / .pyc
find "$INSTALL_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$INSTALL_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

# 4) 应用菜单自动安装（修复/更新 desktop）
if [ -d "$PKG/desktop" ]; then
  mkdir -p "$APPS_DIR"
  install -m 644 "$PKG"/desktop/*.desktop "$APPS_DIR/"
  echo "==> 应用菜单已更新: $(ls "$PKG"/desktop/*.desktop | wc -l) 项"
fi
# 剔除旧命名残留，避免菜单重复
for stale in ai-knowledge.desktop ai-screen-control.desktop ai-agent.desktop \
             ai-timer.desktop hy.desktop ainote.desktop aai.desktop; do
  rm -f "$APPS_DIR/$stale" 2>/dev/null || true
done

# 5) 刷新菜单 / 图标缓存
update-desktop-database "$APPS_DIR" 2>/dev/null || true
for th in /usr/share/icons/hicolor /usr/share/icons/Win11 /usr/share/icons/Win11-dark; do
  [ -d "$th" ] && gtk-update-icon-cache -f -q "$th" 2>/dev/null || true
done

# 6) 提示重启常驻服务
if pgrep -f "chinai3/main.py" >/dev/null 2>&1; then
  echo "==> 检测到 ChinAI3 运行中，如需加载新代码请重启: systemctl --user restart chinai3-app"
fi

echo "==> 完成。应用菜单已刷新，可在活动概览中看到全部应用。"
