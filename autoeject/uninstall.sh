#!/bin/bash
# Uninstallation script for com.aubreyhan.autoeject LaunchAgent
# This script stops the LaunchAgent and deletes the hidden directory and configurations.

set -e

TARGET_DIR="~/.autoeject"
PLIST_NAME="com.aubreyhan.autoeject.plist"
USER_LAUNCHAGENTS_DIR="~/Library/LaunchAgents"

# Resolve absolute paths
RESOLVED_TARGET_DIR=$(eval echo "${TARGET_DIR}")
RESOLVED_LAUNCHAGENTS_DIR=$(eval echo "${USER_LAUNCHAGENTS_DIR}")
TARGET_PLIST_PATH="${RESOLVED_LAUNCHAGENTS_DIR}/${PLIST_NAME}"

echo "Uninstalling disk image auto-eject daemon..."

if [ -f "$TARGET_PLIST_PATH" ]; then
    echo "- Stopping and unloading LaunchAgent..."
    launchctl bootout gui/$(id -u) "$TARGET_PLIST_PATH" 2>/dev/null || true
    
    echo "- Removing plist configuration..."
    rm -f "$TARGET_PLIST_PATH"
else
    echo "- LaunchAgent plist is not installed at ${TARGET_PLIST_PATH}"
fi

if [ -d "$RESOLVED_TARGET_DIR" ]; then
    echo "- Removing hidden directory ${TARGET_DIR}..."
    rm -rf "$RESOLVED_TARGET_DIR"
    echo "LaunchAgent and hidden directory removed successfully."
else
    echo "- Hidden directory ${TARGET_DIR} does not exist."
fi
