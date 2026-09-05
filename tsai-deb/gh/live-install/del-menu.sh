#!/bin/bash
set -e

if [ "$(id -u)" -ne 0 ]; then
    exec sudo bash "$0" "$@"
fi

# 1. /etc/default/grub 设置隐藏
if ! grep -q '^GRUB_TIMEOUT_STYLE=hidden' /etc/default/grub; then
    sed -i 's/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=hidden/' /etc/default/grub
fi
sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' /etc/default/grub
if ! grep -q '^GRUB_RECORDFAIL_TIMEOUT=0' /etc/default/grub; then
    echo 'GRUB_RECORDFAIL_TIMEOUT=0' >> /etc/default/grub
fi

# 2. 40_custom 末尾覆盖 os-prober 的强制显示
if ! grep -q '^set timeout_style=hidden' /etc/grub.d/40_custom; then
    printf 'set timeout_style=hidden\nset timeout=0\n' >> /etc/grub.d/40_custom
fi

# 3. 清除 recordfail
grub-editenv /boot/grub/grubenv unset recordfail

# 4. 重新生成配置
update-grub

echo "GRUB 菜单已隐藏，下次开机将直接进入系统。"
