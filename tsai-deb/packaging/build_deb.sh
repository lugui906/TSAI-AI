#!/usr/bin/env bash
# 从 chindows 源码树构建一个可在普通 Ubuntu 系系统安装的 .deb。
# 用法: sudo ./build_deb.sh   （输出到 packaging/dist/chindows_<ver>_all.deb）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$SCRIPT_DIR/.." && pwd)"          # chindows 源码树根（packaging 的上一级）
BUILD_DIR="$SCRIPT_DIR/dist"
VER="12.0.0"
PKG="chindows"
DEST="usr/tsai-12"                          # 应用安装目录（其他 OS 统一装到版本化路径 /usr/tsai-12）

[ "$(id -u)" = 0 ] || { echo "需要 root 运行（为生成正确属主/权限）"; exit 1; }

mkdir -p "$BUILD_DIR"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "==> 源目录: $SRC"

# ---- 1) 数据载荷：/usr/chindows ----
mkdir -p "$STAGE/$DEST" "$STAGE/usr/share/applications" "$STAGE/usr/bin" \
         "$STAGE/usr/lib/systemd/user" "$STAGE/usr/lib/systemd/system" \
         "$STAGE/usr/share/tsai-airgestured/models" "$STAGE/etc" "$STAGE/DEBIAN" \
         "$STAGE/usr/lib/tsai-12/opencode"

cp -a "$SRC/." "$STAGE/$DEST/"

# 兼容链接：代码引用 /usr/chindows（8 字母，另有 9 字母别名），统一指向实际安装目录 /usr/tsai-12
ln -sfn tsai-12 "$STAGE/usr/chindows"
ln -sfn tsai-12 "$STAGE/usr/chwindows"



# 剔除开发/运行残留（只针对真实应用目录 $DEST）
rm -rf "$STAGE/$DEST/packaging/deb" "$STAGE/$DEST/packaging/dist" \
       "$STAGE/$DEST/packaging/external" 2>/dev/null || true
find "$STAGE/$DEST" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/$DEST" -type d -name "*.egg-info" -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/$DEST" -type d -name ".pytest_cache" -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/$DEST" -type f \( -name "*.pyc" -o -name "*.pyo" -o -name "*.log" \) -delete 2>/dev/null || true
rm -f "$STAGE/$DEST/chinai3.zip" "$STAGE/$DEST/x.zip" 2>/dev/null || true
rm -rf "$STAGE/$DEST/aai/share/models" 2>/dev/null || true

# ---- 2) 应用菜单 / 入口 / 服务 / 配置 ----
install -m 644 "$SRC"/packaging/desktop/*.desktop "$STAGE/usr/share/applications/"
install -m 0755 "$SCRIPT_DIR"/deb/wrappers/* "$STAGE/usr/bin/"
install -m 0644 "$SCRIPT_DIR"/deb/systemd-user/* "$STAGE/usr/lib/systemd/user/"
install -m 0644 "$SCRIPT_DIR"/deb/systemd/* "$STAGE/usr/lib/systemd/system/"
install -m 0644 "$SRC/gh/etc/tsai-airgestured.conf" "$STAGE/etc/tsai-airgestured.conf"

# 模型目录占位
mkdir -p "$STAGE/$DEST/aai/share/models"
echo "请放置 faster-whisper 模型（model.bin, 见 aai 代码注释）" > "$STAGE/$DEST/aai/share/models/README.txt"
echo "请放置 models/palm.tflite（见 gh/models/README.md）" > "$STAGE/usr/share/tsai-airgestured/models/README.txt"

# ---- 2.5) 预制服务：aim 二进制 + opencode 双架构二进制 ----
# aim：不编译，直接用宿主当前的 /bin/aim（merged-usr 下与 /usr/bin/aim 同一文件）
AIM_SRC="/bin/aim"
if [ -x "$AIM_SRC" ]; then
  install -m 0755 "$AIM_SRC" "$STAGE/usr/bin/aim"
  echo "==> aim: 复制宿主二进制 $AIM_SRC（$(du -h "$STAGE/usr/bin/aim" | cut -f1)）"
else
  echo "WARN: 未找到 $AIM_SRC，将不含 aim（运行依赖缺失）"
fi

# opencode 双架构二进制（amd64/arm64），配 /usr/bin/opencode 选择包装脚本
OPDIR="$SCRIPT_DIR/external/opencode"
if [ -f "$OPDIR/opencode-linux-x64" ] && [ -f "$OPDIR/opencode-linux-arm64" ]; then
  install -m 0755 "$OPDIR/opencode-linux-x64"   "$STAGE/usr/lib/tsai-12/opencode/opencode-linux-x64"
  install -m 0755 "$OPDIR/opencode-linux-arm64" "$STAGE/usr/lib/tsai-12/opencode/opencode-linux-arm64"
  echo "==> included opencode: $(du -h "$OPDIR"/opencode-linux-* | tr '\n' ' ')"
else
  echo "WARN: 未找到 $OPDIR/opencode-linux-{x64,arm64}，将不含 opencode 二进制（运行依赖缺失）"
fi

# ---- 3) DEBIAN 控制文件 ----
install -m 0644 "$SCRIPT_DIR/deb/control" "$STAGE/DEBIAN/control"
install -m 0755 "$SCRIPT_DIR/deb/postinst" "$STAGE/DEBIAN/postinst"
install -m 0755 "$SCRIPT_DIR/deb/prerm"    "$STAGE/DEBIAN/prerm"
install -m 0755 "$SCRIPT_DIR/deb/postrm"   "$STAGE/DEBIAN/postrm"
echo "/etc/tsai-airgestured.conf" > "$STAGE/DEBIAN/conffiles"

# 计算 Installed-Size（KB）
SIZE=$(du -sk "$STAGE/usr" "$STAGE/etc" | awk '{s+=$1} END{print s}')
sed -i "s/^Version:.*/Version: $VER/" "$STAGE/DEBIAN/control"
sed -i '/^Installed-Size:/d' "$STAGE/DEBIAN/control"
sed -i "/^Description:/i Installed-Size: $SIZE" "$STAGE/DEBIAN/control"

# md5sums（不含 DEBIAN）
( cd "$STAGE" && find . -path ./DEBIAN -prune -o -type f -print | \
  sort | while read -r f; do md5sum "${f#./}"; done ) > "$STAGE/DEBIAN/md5sums"

# 修正属主
chown -R root:root "$STAGE"
find "$STAGE/usr/bin" -type f -exec chmod 0755 {} +

# ---- 4) 打包 ----
OUT="$BUILD_DIR/${PKG}_${VER}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT"
echo
echo "==> 已生成: $OUT ($(du -h "$OUT" | cut -f1))"
echo "    安装: sudo apt install ./$OUT  或 sudo dpkg -i $OUT && sudo apt -f install"