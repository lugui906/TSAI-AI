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

# 注册单个根分区：写本目录 grub.cfg、注册 NVRAM 启动项、排到启动顺序首位
# $1=磁盘设备名(nvme1n1)  $2=ESP分区名(p1)  $3=ESP挂载点  $4=根分区名(p4)  $5=ESP分区号
register_root() {
  local dev="$1" esp_name="$2" esp_mp="$3" root_name="$4" esp_pnum="$5"
  local root_mp label label_alt root_uuid
  local vendordir loader loader_path
  local new_cfg tmp_cfg cfg written=0
  local old_entries removed entry_num current new_order b

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

  # ---- 选定本系统的厂商目录：优先与系统名同名的目录（大小写不敏感），
  #      否则用 BOOT（grub 前缀内嵌在 .efi 里，复制加载器到新目录不可靠）----
  vendordir=""
  for cand in "$esp_mp"/EFI/*/; do
    [[ -d "$cand" ]] || continue
    local cb
    cb="$(basename "$cand")"
    [[ "$cb" == "BOOT" ]] && continue
    compgen -G "$cand"/*.efi >/dev/null 2>&1 || continue
    if [[ "${cb,,}" == "${label,,}" ]]; then
      vendordir="$cb"
      break
    fi
  done
  if [[ -z "$vendordir" ]] && [[ -d "$esp_mp/EFI/BOOT" ]] \
     && compgen -G "$esp_mp/EFI/BOOT"/*.efi >/dev/null 2>&1; then
    vendordir="BOOT"
  fi
  [[ -n "$vendordir" ]] || { warn "$root_name: ESP 上无匹配目录亦无 BOOT 加载器，跳过。"; return 1; }

  loader=""
  for l in shimx64.efi grubx64.efi BOOTX64.EFI; do
    [[ -f "$esp_mp/EFI/$vendordir/$l" ]] && loader="$l" && break
  done
  if [[ -z "$loader" ]]; then
    loader=$(find "$esp_mp/EFI/$vendordir" -maxdepth 1 -iname '*.efi' 2>/dev/null | head -n1 | xargs -r basename)
  fi
  [[ -n "$loader" ]] || { warn "ESP 上未找到任何 .efi 加载器，跳过。"; return 1; }

  # ---- 只写本目录的 grub.cfg（指向本根分区），多系统互不覆盖 ----
  new_cfg=$'search.fs_uuid '"${root_uuid}"$' root\nset prefix=($root)\'/boot/grub\'\nconfigfile $prefix/grub.cfg\n'
  tmp_cfg="$(mktemp /tmp/regboot.cfg.XXXXXX)"
  printf '%s' "$new_cfg" > "$tmp_cfg"
  cfg="$esp_mp/EFI/$vendordir/grub.cfg"
  if ! cmp -s "$cfg" "$tmp_cfg"; then
    cp "$tmp_cfg" "$cfg"
    log "已更新 $cfg"
    written=1
  fi
  rm -f "$tmp_cfg"
  [[ $written -eq 1 ]] && sync

  loader_path="\\EFI\\${vendordir}\\${loader}"

  log "系统: $label  根分区 UUID: $root_uuid"
  log "加载器: $loader_path  (ESP 分区号 $esp_pnum)"

  # ---- 删除旧条目：同名条目，以及指向本目录的非 BOOT 旧条目（防止 grub.cfg
  #      被重指向后残留误导项），避免重复注册 ----
  old_entries=""
  old_entries+=$(efibootmgr 2>/dev/null | awk -v l="$label" '
    /^Boot[0-9A-F]{4}\*/ {
      line=$0; sub(/\t.*/,"",line); sub(/^Boot[0-9A-F]{4}\*[ \t]*/,"",line);
      if (line==l) { print substr($0,5,4) }
    }' 2>/dev/null || true)
  if [[ "$vendordir" != "BOOT" ]]; then
    old_entries+=$(efibootmgr 2>/dev/null | awk -v d="$vendordir" '
      /^Boot[0-9A-F]{4}\*/ {
        p=$0; sub(/^Boot[0-9A-F]{4}\*[ \t]*/,"",p); sub(/^[^\t]*\t/,"",p);
        if (tolower(p) ~ ("\\\\efi\\\\" tolower(d) "\\\\")) print substr($0,5,4)
      }' 2>/dev/null || true)
  fi
  removed=""
  for old in $old_entries; do
    case " $removed " in *" $old "*) continue ;; esac
    efibootmgr --quiet -B -b "$old" >/dev/null 2>&1 || true
    log "已移除旧启动项 Boot$old"
    removed="$removed $old"
  done

  efibootmgr --quiet --create --disk "$dev" --part "$esp_pnum" \
             --label "$label" --loader "$loader_path" >/dev/null 2>&1 \
    || { warn "efibootmgr 注册失败 ($label)。"; return 1; }

  entry_num=$(efibootmgr 2>/dev/null | awk -v l="$label" '
    /^Boot[0-9A-F]{4}\*/ {
      line=$0; sub(/\t.*/,"",line); sub(/^Boot[0-9A-F]{4}\*[ \t]*/,"",line);
      if (line==l) { print substr($0,5,4); exit }
    }' 2>/dev/null || true)
  [[ -n "$entry_num" ]] || { warn "未能找到新注册的启动项 ($label)。"; return 1; }
  log "已注册启动项: Boot$entry_num  $label"

  # ---- 将新条目排到启动顺序首位 ----
  current=$(efibootmgr 2>/dev/null | awk '/^BootOrder:/{sub("BootOrder:","");print;exit}' | tr -d ' ')
  new_order="$entry_num"
  for b in ${current//,/ }; do
    [[ "$b" == "$entry_num" ]] && continue
    new_order="${new_order},${b}"
  done
  efibootmgr --quiet --bootorder "$new_order" >/dev/null 2>&1 || true
  log "启动顺序已更新: $new_order"
  printf '\n'
}

# 处理单块磁盘：找出其 ESP 与全部可引导根分区，逐个注册
process_disk() {
  local disk="$1"
  local dev="/dev/$disk"
  local esp_name="" esp_mp esp_pnum name
  local root_names=()

  while read -r name; do
    [[ -n "$name" ]] || continue
    if is_root_candidate "$name" && probe_root "$name" >/dev/null 2>&1; then
      root_names+=("$name")
    fi
    if [[ -z "$esp_name" ]] && is_esp "$name"; then
      esp_name="$name"
    fi
  done < <(lsblk -rno NAME,TYPE "$dev" 2>/dev/null | awk '$2=="part"{print $1}')

  if [[ -z "$esp_name" ]]; then
    warn "$dev: 未找到 EFI 系统分区，跳过。"
    return 0
  fi
  if [[ ${#root_names[@]} -eq 0 ]]; then
    warn "$dev: 未找到可引导的 Linux 根分区，跳过。"
    return 0
  fi

  info "==> 磁盘 $dev：ESP=${esp_name}  根分区=${root_names[*]}"

  esp_mp=$(mount_part "$esp_name" "rw") || { warn "无法挂载 $esp_name，跳过。"; return 1; }
  if [[ ! -d "$esp_mp/EFI" ]]; then
    warn "$esp_name 上不存在 EFI 目录，可能不是有效的 ESP，跳过。"
    return 1
  fi
  esp_pnum="${esp_name##*[a-z]}"

  for name in "${root_names[@]}"; do
    register_root "$dev" "$esp_name" "$esp_mp" "$name" "$esp_pnum"
  done
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
