#!/usr/bin/env bash
APPDIR="$(dirname "$(readlink -f "$0")")/squashfs-root"
export PATH="${APPDIR}:${APPDIR}/usr/sbin${PATH:+:${PATH}}"
export XDG_DATA_DIRS="${APPDIR}/usr/share${XDG_DATA_DIRS:+:${XDG_DATA_DIRS}}"
export LD_LIBRARY_PATH="${APPDIR}/usr/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
exec "${APPDIR}/token-monitor" --no-sandbox "$@"
