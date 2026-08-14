#!/bin/bash
# Chindows AIM 2.0 integration script
# This script handles systemd integration, suspend/resume hooks

SERVICE_NAME="aim.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
BIN_PATH="/usr/local/bin/aim"

install_service() {
    echo "Installing AIM 2.0 systemd service..."
    cp scripts/aim.service "${SERVICE_PATH}"
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    systemctl start "${SERVICE_NAME}"
    echo "AIM service installed and started."
}

install_binary() {
    echo "Installing AIM binary to ${BIN_PATH}..."
    cp build/aim "${BIN_PATH}"
    chmod +x "${BIN_PATH}"
    echo "Binary installed."
}

handle_suspend() {
    echo "System suspending - pausing AI inference tasks..."
    # Signal AIM to pause tasks
    pkill -SIGTSTP aim 2>/dev/null || true
}

handle_resume() {
    echo "System resuming - restarting AI inference tasks..."
    # Signal AIM to resume tasks
    pkill -SIGCONT aim 2>/dev/null || true
    systemctl restart "${SERVICE_NAME}" 2>/dev/null || true
}

case "${1}" in
    install)
        install_binary
        install_service
        ;;
    uninstall)
        systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
        systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
        rm -f "${SERVICE_PATH}"
        systemctl daemon-reload
        ;;
    suspend)
        handle_suspend
        ;;
    resume)
        handle_resume
        ;;
    *)
        echo "Usage: $0 {install|uninstall|suspend|resume}"
        exit 1
        ;;
esac
