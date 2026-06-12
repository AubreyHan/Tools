#!/bin/bash
# Installation script for com.aubreyhan.autoeject LaunchAgent
# This script sets up the LaunchAgent and places the daemon inside ~/.autoeject

set -e

# Target user hidden directory (relative/symbolic to home)
TARGET_DIR="~/.autoeject"
SCRIPT_NAME="autoeject.py"
PLIST_NAME="com.aubreyhan.autoeject.plist"
USER_LAUNCHAGENTS_DIR="~/Library/LaunchAgents"

# Resolve absolute paths for operations and launchd configuration
RESOLVED_TARGET_DIR=$(eval echo "${TARGET_DIR}")
RESOLVED_LAUNCHAGENTS_DIR=$(eval echo "${USER_LAUNCHAGENTS_DIR}")
TARGET_PLIST_PATH="${RESOLVED_LAUNCHAGENTS_DIR}/${PLIST_NAME}"

# Create hidden directory
mkdir -p "${RESOLVED_TARGET_DIR}"

# Copy autoeject.py to hidden directory
cp "$(dirname "$0")/${SCRIPT_NAME}" "${RESOLVED_TARGET_DIR}/${SCRIPT_NAME}"
chmod +x "${RESOLVED_TARGET_DIR}/${SCRIPT_NAME}"

# Copy install.sh to hidden directory for distributing to other computers
if [ -f "$0" ]; then
    cp "$0" "${RESOLVED_TARGET_DIR}/install.sh"
    chmod +x "${RESOLVED_TARGET_DIR}/install.sh"
fi

# Copy uninstall.sh to hidden directory for convenience
if [ -f "$(dirname "$0")/uninstall.sh" ]; then
    cp "$(dirname "$0")/uninstall.sh" "${RESOLVED_TARGET_DIR}/uninstall.sh"
    chmod +x "${RESOLVED_TARGET_DIR}/uninstall.sh"
fi

# Find python3 path
PYTHON_PATH=$(which python3)
if [ -z "$PYTHON_PATH" ]; then
    echo "Error: python3 not found in PATH." >&2
    exit 1
fi

echo "Installing disk image auto-eject daemon..."
echo "- Hidden directory:   ${TARGET_DIR} (${RESOLVED_TARGET_DIR})"
echo "- Python interpreter: ${PYTHON_PATH}"
echo "- Daemon script:      ${TARGET_DIR}/${SCRIPT_NAME}"
echo "- Log output:         ${TARGET_DIR}/autoeject.log"
echo "- Error output:       ${TARGET_DIR}/autoeject.err"

# Create the plist file dynamically
cat <<EOF > "${RESOLVED_TARGET_DIR}/${PLIST_NAME}"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.aubreyhan.autoeject</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${RESOLVED_TARGET_DIR}/${SCRIPT_NAME}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${RESOLVED_TARGET_DIR}/autoeject.log</string>
    <key>StandardErrorPath</key>
    <string>${RESOLVED_TARGET_DIR}/autoeject.err</string>
</dict>
</plist>
EOF

# Ensure user's LaunchAgents directory exists
mkdir -p "${RESOLVED_LAUNCHAGENTS_DIR}"

# Copy plist to LaunchAgents directory
cp "${RESOLVED_TARGET_DIR}/${PLIST_NAME}" "${TARGET_PLIST_PATH}"
echo "- Copied plist configuration to ${TARGET_PLIST_PATH}"

# Unload first if already loaded to ensure fresh reload
launchctl bootout gui/$(id -u) "${TARGET_PLIST_PATH}" 2>/dev/null || true

# Load the LaunchAgent
echo "- Loading LaunchAgent..."
launchctl bootstrap gui/$(id -u) "${TARGET_PLIST_PATH}"

echo "LaunchAgent installed and started successfully!"
echo "Check status: launchctl list | grep autoeject"
echo "Check logs:   tail -f ${TARGET_DIR}/autoeject.log"
