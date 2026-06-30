#!/bin/bash
set -e

DAEMON_DIR="$HOME/.github_sync"
PLIST_LABEL="com.user.githubsync"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

echo "=== GitHub Auto-Sync Daemon Installer ==="

# 1. Ensure daemon directory exists
echo "Creating daemon directory at $DAEMON_DIR..."
mkdir -p "$DAEMON_DIR"

# 2. Setup Python virtual environment
echo "Creating Python virtual environment..."
python3 -m venv "$DAEMON_DIR/venv"

# 3. Install required dependencies
echo "Installing dependencies (watchdog)..."
"$DAEMON_DIR/venv/bin/pip" install --upgrade pip
"$DAEMON_DIR/venv/bin/pip" install watchdog

# 4. Create launchd plist file
echo "Generating launchd plist..."
cat <<EOF > "$DAEMON_DIR/$PLIST_LABEL.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$DAEMON_DIR/venv/bin/python</string>
        <string>$DAEMON_DIR/github_sync_daemon.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>$DAEMON_DIR</string>
    <key>StandardOutPath</key>
    <string>$DAEMON_DIR/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>$DAEMON_DIR/daemon.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF

# 5. Stop and unload old agent if it exists
echo "Stopping existing daemon instance if running..."
if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    # Try bootout for newer macOS versions
    launchctl bootout "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null || true
fi

# 6. Copy and set permissions for plist
echo "Installing plist file..."
mkdir -p "$HOME/Library/LaunchAgents"
cp "$DAEMON_DIR/$PLIST_LABEL.plist" "$PLIST_PATH"
chmod 644 "$PLIST_PATH"

# 7. Load and start the daemon
echo "Loading and starting the daemon..."
launchctl load "$PLIST_PATH" 2>/dev/null || launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "=== Installation Completed ==="
echo "The GitHub Auto-Sync daemon has been started."
echo "You can view logs at: $DAEMON_DIR/daemon.log"
echo "Configuration file: $DAEMON_DIR/config.json"
