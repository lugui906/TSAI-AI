#!/usr/bin/env bash
# 实时 CPU 频率/温度检测 — i5-13420H (12 threads)
# 用法: ./freqwatch.sh [刷新秒数]   (默认 1s)
set -euo pipefail

INTERVAL="${1:-1}"
NPROC=$(nproc)
hdr=""
tput clear 2>/dev/null

while true; do
  cur="$(( $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq) / 1000 )) MHz"

  # 全核平均频率
  avg=$(grep MHz /proc/cpuinfo \
        | grep -oE '[0-9]+\.[0-9]{3}' \
        | awk '{s+=$1; n++} END { if(n>0) printf "%.3f MHz", s/n }')

  # 温度 (若有 thermal_zone)
  tmp=$(find /sys/class/thermal -name 'temp' 2>/dev/null | \
        while read -r t; do echo "$(( $(cat "$t") / 1000 ))"; done | sort -rn | head -1)

  gov=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo "?")
  max=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null)
  max=$(( max / 1000 ))

  tput home 2>/dev/null
  printf "CPU: i5-13420H (%d 线程)\n" "$NPROC"
  printf "Governor: %s     范围: 400-%s MHz\n" "$gov" "$max"
  printf "当前 (cpu0): %-9s  平均: %s\n" "$cur" "$avg"
  printf "核心频率: "; grep MHz /proc/cpuinfo | grep -oE '[0-9]+\.[0-9]{3}' \
      | awk '{printf "%.3f  ", $1}'; printf "\n"
  if [ -n "$tmp" ]; then printf "温度:      %s°C\n" "$tmp"; fi
  printf -- "------------------------------------------\n"
  printf "按 Ctrl+C 退出   (刷新: %ss)\n" "$INTERVAL"

  sleep "${INTERVAL}"
done
