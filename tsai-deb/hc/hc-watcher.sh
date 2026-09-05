#!/bin/bash
PIDFILE="$XDG_RUNTIME_DIR/huaci-ai.pid"

# 多实例保护
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        exit 0
    fi
    rm -f "$PIDFILE"
fi

echo "$$" > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

LOG="$HOME/.cache/huaci-ai.log"

# 确保 XIM 服务器(ibus-x11)在 :0 上运行——hc 是 tkinter(X11) 应用，
# 没有它就无法用中文输入法。GDK_BACKEND 强制用 x11，避免被 /etc/profile 的 wayland 覆盖。
export GDK_BACKEND=x11
start_ibus_x11() {
    if ! xprop -display "${DISPLAY:-:0}" -root >/dev/null 2>&1; then
        return
    fi
    if ! pgrep -x ibus-x11 >/dev/null 2>&1; then
        if command -v ibus-x11 >/dev/null 2>&1; then IBUS_X11=ibus-x11; else IBUS_X11=/usr/libexec/ibus-x11; fi
        setsid "$IBUS_X11" >> "$LOG" 2>&1 &
    fi
}

while true; do
    start_ibus_x11
    /usr/bin/python3 /usr/chindows/hc/main.py >> "$LOG" 2>&1
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -eq 0 ]; then
        break
    fi
    sleep 5
done
