#!/bin/bash
# Chindows AIM 2.0 integration script
# Installs AIM binary and systemd service

CUSTOM_ROOT="${CUSTOM_ROOT:-/}"
SERVICE_NAME="aim.service"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
    echo "Usage: $0 {install|uninstall|suspend|resume} [--custom-root PATH]"
    exit 1
}

# Parse --custom-root if present
while [[ $# -gt 0 ]]; do
    case "$1" in
        --custom-root)
            CUSTOM_ROOT="$2"
            shift 2
            ;;
        install|uninstall|suspend|resume)
            ACTION="$1"
            shift
            ;;
        *)
            usage
            ;;
    esac
done

BIN_DST="${CUSTOM_ROOT}/usr/bin/aim"
SERVICE_DST="${CUSTOM_ROOT}/etc/systemd/system/${SERVICE_NAME}"
SCRIPT_DST="${CUSTOM_ROOT}/usr/local/lib/aim/chindows-integrate.sh"

install_all() {
    echo "Installing AIM 2.0 to ${CUSTOM_ROOT}..."
    install -Dm755 "${PROJECT_DIR}/build/aim" "${BIN_DST}"
    install -Dm644 "${PROJECT_DIR}/scripts/aim.service" "${SERVICE_DST}"
    install -Dm755 "${PROJECT_DIR}/scripts/chindows-integrate.sh" "${SCRIPT_DST}"
    echo "Done: binary, systemd service, and integration script installed."

    if [[ "${CUSTOM_ROOT}" == "/" ]]; then
        systemctl daemon-reload
        systemctl enable "${SERVICE_NAME}"
        systemctl start "${SERVICE_NAME}"
        echo "AIM service enabled and started."
    else
        echo "Custom root mode: skip systemctl (run 'systemctl daemon-reload' from target root)."
    fi
}

uninstall_all() {
    echo "Removing AIM 2.0 from ${CUSTOM_ROOT}..."
    rm -f "${BIN_DST}"
    rm -f "${SERVICE_DST}"
    rm -f "${SCRIPT_DST}"
    echo "Done."

    if [[ "${CUSTOM_ROOT}" == "/" ]]; then
        systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
        systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
        systemctl daemon-reload
    fi
}

handle_suspend() {
    echo "System suspending - pausing AI inference tasks..."
    pkill -SIGTSTP aim 2>/dev/null || true
}

handle_resume() {
    echo "System resuming - restarting AI inference tasks..."
    pkill -SIGCONT aim 2>/dev/null || true
    systemctl restart "${SERVICE_NAME}" 2>/dev/null || true
}

case "${ACTION}" in
    install)
        install_all
        ;;
    uninstall)
        uninstall_all
        ;;
    suspend)
        handle_suspend
        ;;
    resume)
        handle_resume
        ;;
    *)
        usage
        ;;
esac
