# macOS Disk Image Auto-Eject Daemon - Installation Guide

This guide explains how to install the automatic disk image (.dmg) auto-eject daemon on another macOS computer. 

Since the installation and uninstallation scripts are fully self-contained and path-independent (dynamically resolving Python paths and user directories), the process is quick and simple.

---

## Files Needed

You need the following 3 files:
1. `autoeject.py`: The Python monitoring script.
2. `install.sh`: The setup and LaunchAgent loader.
3. `uninstall.sh`: The cleaner and unloader.

---

## Installation Steps (On the Target Mac)

### 1. Copy the Files
Copy the three files (`autoeject.py`, `install.sh`, `uninstall.sh`) into any directory on the new Mac (for example, a temporary folder or `~/Downloads`).

### 2. Open Terminal
Open the **Terminal** application and navigate to the directory where you copied the files:
```bash
cd /path/to/copied/files
```
*(Tip: You can type `cd ` and drag the folder from Finder into the Terminal window to auto-fill the path).*

### 3. Run the Installer
Execute the following command to make the scripts executable and run the installation:
```bash
chmod +x install.sh uninstall.sh && ./install.sh
```

### 4. What the Installer Does Automatically
1. Creates the user-level hidden directory `~/.autoeject/` (`/Users/username/.autoeject/`).
2. Copies the daemon script (`autoeject.py`) and uninstaller (`uninstall.sh`) into that directory.
3. Locates the correct Python 3 interpreter path.
4. Generates a custom LaunchAgent configuration file `com.aubreyhan.autoeject.plist` pointing to the correct user paths.
5. Registers and boots the daemon via `launchctl bootstrap`.

---

## Verifying the Installation

1. **Check if the service is running**:
   ```bash
   launchctl list | grep autoeject
   ```
   *If successful, you will see a line starting with a PID (Process ID) followed by `com.aubreyhan.autoeject`.*

2. **View the live logs**:
   ```bash
   tail -f ~/.autoeject/autoeject.log
   ```
   *You should see a message indicating the daemon has started: `Auto-eject daemon started. Timeout: 900s. Polling interval: 30s.`*

---

## How to Uninstall

To cleanly stop the service and delete all scripts, configurations, and logs, simply run the uninstaller from the hidden directory:
```bash
~/.autoeject/uninstall.sh
```
*(Or if you still have the uninstaller in your original download folder, you can run `./uninstall.sh` from there).*
