#!/usr/bin/env bash
# =============================================================================
# register-boot-entry.sh
#
# 在 UEFI Live / 急救环境下，自动探测硬盘上安装的 Linux 系统并注册 UEFI 启动项。
#
# 特性：
#   * 零硬编码：磁盘、EFI 分区、根分区、加载器、启动标签全部自动探测，
#     不预设任何设备名 / 分区号 / 文件路径。
#   * 支持多块硬盘、多系统，逐个探测并注册。
#   * 自动在 ESP 写入指向根分区的 grub.cfg（search.fs_uuid + configfile）。
#   * 通过 efibootmgr 向固件 NVRAM 注册启动项，并排到启动顺序首位。
#   * 自动处理 Secure Boot（优先 shimx64.efi，其次 grubx64.efi）。
#   * 全部挂载点基于临时目录，完成后自动清理。
#
# 用法：
#   sudo ./register-boot-entry.sh             # 探测全部磁盘并注册
#   sudo ./register-boot-entry.sh /dev/sdb    # 只处理指定磁盘
#
# 说明：ESP_GUID 是 UEFI 规范定义的固定分区类型 GUID，属技术常量，非环境硬编码。
# =============================================================================
set -euo pipefail

readonly ESP_GUID="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
readonly ROOT_FSTYPES="ext4 ext3 ext2 btrfs xfs f2fs"

log()  { printf '\033[1;32m[+] %s\033[0m\n' "$*"; }
info() { printf '\033[1;34m[*] %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "请以 root 权限运行（sudo）。"
[[ -d /sys/firmware/efi ]] || die "当前不是 UEFI 引导模式，无法注册 UEFI 启动项。"
command -v efibootmgr >/dev/null 2>&1 || die "缺少 efibootmgr。"
command -v lsblk      >/dev/null 2>&1 || die "缺少 lsblk。"
command -v blkid      >/dev/null 2>&1 || die "缺少 blkid。"

# 记录本次创建的临时挂载点，结束时统一清理
# 注意：mount_part 常在 $(...) 子壳中调用，故用文件而非数组记录
readonly MPS_LOG="$(mktemp /tmp/regboot-log.XXXXXX)"
cleanup() {
  local mp
  while IFS= read -r mp; do
    umount "$mp" >/dev/null 2>&1 || true
    rmdir "$mp" >/dev/null 2>&1 || true
  done < "$MPS_LOG"
  rm -f "$MPS_LOG"
}
trap cleanup EXIT

# 挂载分区（尽量只读），返回挂载点。若已挂载则复用现有挂载点（不负责卸载）。
# $1=分区名(sda1)  $2=ro|rw
mount_part() {
  local name="$1" mode="${2:-ro}"
  local dev="/dev/$name"
  local mp existing
  existing=$(awk -v d="$dev" '$1==d {print $2; exit}' /proc/mounts)
  if [[ -n "$existing" ]]; then
    printf '%s\n' "$existing"
    return 0
  fi
  mp="$(mktemp -d /tmp/regboot.XXXXXX)"
  if ! mount -o "$mode" "$dev" "$mp" 2>/dev/null; then
    rmdir "$mp" 2>/dev/null
    return 1
  fi
  printf '%s\n' "$mp" >> "$MPS_LOG"
  printf '%s\n' "$mp"
}

# 判断分区是否为 ESP：按 GPT 类型 GUID 识别，兜底用 vfat 文件系统
is_esp() {
  local name="$1"
  local pttype fstype
  pttype=$(lsblk -rno PARTTYPE "/dev/$name" 2>/dev/null)
  fstype=$(lsblk -rno FSTYPE  "/dev/$name" 2>/dev/null)
  [[ "$pttype" == "$ESP_GUID" ]] && return 0
  [[ "$fstype" == "vfat" ]] && return 0
  return 1
}

# 判断分区是否为候选根分区（Linux 文件系统且非 swap）
is_root_candidate() {
  local name="$1"
  local fstype
  fstype=$(lsblk -rno FSTYPE "/dev/$name" 2>/dev/null)
  [[ -n "$fstype" ]] || return 1
  [[ "$fstype" == "swap" ]] && return 1
  case " $ROOT_FSTYPES " in
    *" $fstype "*) return 0 ;;
  esac
  return 1
}

# 校验分区是否真的是可引导的系统根：含 /etc/os-release 与 /boot/vmlinuz*
# 挂载成功后输出：mountpoint|os_release 值
probe_root() {
  local name="$1"
  local mp
  mp=$(mount_part "$name" "ro") || return 1
  [[ -f "$mp/etc/os-release" ]] || return 1
  compgen -G "$mp/boot/vmlinuz*" >/dev/null 2>&1 || return 1
  [[ -f "$mp/boot/grub/grub.cfg" ]] || return 1
  printf '%s\n' "$mp"
}

# 处理单块磁盘：找出其 ESP 与根分区并注册
process_disk() {
  local disk="$1"
  local dev="/dev/$disk"
  local root_name esp_name
  local esp_mp root_mp label
  local root_uuid esp_pnum
  local vendordir loader loader_path
  local entry_num cur_order new_order b

  root_name=""
  esp_name=""

  while read -r name; do
    [[ -n "$name" ]] || continue
    if [[ -z "$root_name" ]] && is_root_candidate "$name"; then
      if probe_root "$name" >/dev/null 2>&1; then
        root_name="$name"
      fi
    fi
    if [[ -z "$esp_name" ]] && is_esp "$name"; then
      esp_name="$name"
    fi
  done < <(lsblk -rno NAME,TYPE "$dev" 2>/dev/null | awk '$2=="part"{print $1}')

  if [[ -z "$esp_name" ]]; then
    warn "$dev: 未找到 EFI 系统分区，跳过。"
    return 0
  fi
  if [[ -z "$root_name" ]]; then
    warn "$dev: 未找到可引导的 Linux 根分区，跳过。"
    return 0
  fi

  info "==> 磁盘 $dev：ESP=${esp_name}  根分区=${root_name}"

  # ---- 读取系统信息（自动生成启动标签：优先 NAME，其次 PRETTY_NAME）----
  root_mp=$(mount_part "$root_name" "ro") || { warn "无法挂载 $root_name，跳过。"; return 1; }
  label=""
  label_alt=""
  while IFS='=' read -r k v; do
    case "$k" in
      NAME) v="${v%\"}"; v="${v#\"}"; label="$v" ;;
      PRETTY_NAME) v="${v%\"}"; v="${v#\"}"; label_alt="$v" ;;
    esac
  done < "$root_mp/etc/os-release"
  [[ -n "$label" ]] || label="$label_alt"
  label=$(printf '%s' "$label" | tr -s ' ' | tr -c '[:alnum:] ._-' '_' | sed 's/^[ _]*//;s/[ _]*$//')
  [[ -n "$label" ]] || label="Linux"

  root_uuid=$(blkid -s UUID -o value "/dev/$root_name")

  # ---- 写入 ESP 上的 grub.cfg（指向根分区）----
  esp_mp=$(mount_part "$esp_name" "rw") || { warn "无法挂载 $esp_name，跳过。"; return 1; }
  if [[ ! -d "$esp_mp/EFI" ]]; then
    warn "$esp_name 上不存在 EFI 目录，可能不是有效的 ESP，跳过。"
    return 1
  fi

  local new_cfg tmp_cfg
  new_cfg=$'search.fs_uuid '"${root_uuid}"$' root\nset prefix=($root)\'/boot/grub\'\nconfigfile $prefix/grub.cfg\n'
  tmp_cfg="$(mktemp /tmp/regboot.cfg.XXXXXX)"
  printf '%s' "$new_cfg" > "$tmp_cfg"
  local cfg written=0
  while IFS= read -r -d '' cfg; do
    if ! cmp -s "$cfg" "$tmp_cfg"; then
      cp "$tmp_cfg" "$cfg"
      log "已更新 $cfg"
      written=1
    fi
  done < <(find "$esp_mp/EFI" -name grub.cfg -print0)
  rm -f "$tmp_cfg"
  [[ $written -eq 1 ]] && sync

  # ---- 选择加载器与厂商目录（不预设路径）----
  vendordir=""
  # 优先使用与系统名同名的真实目录（大小写不敏感），其次 EFI 下任意含 .efi 的目录
  for cand in "$esp_mp"/EFI/*/; do
    [[ -d "$cand" ]] || continue
    local b
    b="$(basename "$cand")"
    [[ "$b" == "BOOT" ]] && continue
    compgen -G "$cand"/*.efi >/dev/null 2>&1 || continue
    [[ -z "$vendordir" ]] && vendordir="$b"
    if [[ "${b,,}" == "${label,,}" ]]; then
      vendordir="$b"
      break
    fi
  done
  [[ -z "$vendordir" ]] && vendordir="BOOT"

  loader=""
  for l in shimx64.efi grubx64.efi BOOTX64.EFI; do
    [[ -f "$esp_mp/EFI/$vendordir/$l" ]] && loader="$l" && break
  done
  if [[ -z "$loader" ]]; then
    loader=$(find "$esp_mp/EFI/$vendordir" -maxdepth 1 -iname '*.efi' 2>/dev/null | head -n1 | xargs -r basename)
  fi
  [[ -n "$loader" ]] || { warn "ESP 上未找到任何 .efi 加载器，跳过。"; return 1; }

  loader_path="\\EFI\\${vendordir}\\${loader}"
  esp_pnum="${esp_name##*[a-z]}"

  log "系统: $label  根分区 UUID: $root_uuid"
  log "加载器: $loader_path  (ESP 分区号 $esp_pnum)"

  # ---- 注册 NVRAM 启动项（先删除同名旧条目，避免重复）----
  local old
  old=$(efibootmgr 2>/dev/null | awk -v l="$label" '
    /^Boot[0-9A-F]{4}\*/ {
      line=$0; sub(/\t.*/,"",line); sub(/^Boot[0-9A-F]{4}\*[ \t]*/,"",line);
      if (line==l) { print substr($0,5,4); exit }
    }')
  [[ -z "$old" ]] || { efibootmgr --quiet -B -b "$old" >/dev/null 2>&1; log "已移除旧启动项 Boot$old ($label)"; }

  efibootmgr --quiet --create --disk "$dev" --part "$esp_pnum" \
             --label "$label" --loader "$loader_path" >/dev/null 2>&1 \
    || die "efibootmgr 注册失败。"

  entry_num=$(efibootmgr 2>/dev/null | awk -v l="$label" '
    /^Boot[0-9A-F]{4}\*/ {
      line=$0; sub(/\t.*/,"",line); sub(/^Boot[0-9A-F]{4}\*[ \t]*/,"",line);
      if (line==l) { print substr($0,5,4); exit }
    }')
  [[ -n "$entry_num" ]] || die "未能找到新注册的启动项。"
  log "已注册启动项: Boot$entry_num  $label"

  # ---- 将新条目排到启动顺序首位 ----
  current=$(efibootmgr | awk '/^BootOrder:/{sub("BootOrder:","");print;exit}' | tr -d ' ')
  new_order="$entry_num"
  for b in ${current//,/ }; do
    [[ "$b" == "$entry_num" ]] && continue
    new_order="${new_order},${b}"
  done
  efibootmgr --quiet --bootorder "$new_order" >/dev/null 2>&1
  log "启动顺序已更新: $new_order"
  printf '\n'
}

# ============================ 主流程 ============================
if [[ $# -gt 0 ]]; then
  for arg in "$@"; do
    case "$arg" in
      /dev/*) disk=${arg#/dev/} ;;
      *) die "参数无效: $arg（应为 /dev/sdX）" ;;
    esac
    process_disk "$disk"
  done
else
  while read -r disk; do
    [[ -n "$disk" ]] || continue
    process_disk "$disk"
  done < <(lsblk -dno NAME,TYPE | awk '$2=="disk"{print $1}')
fi

echo "完成。"
