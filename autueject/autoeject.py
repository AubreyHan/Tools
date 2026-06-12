#!/usr/bin/env python3
import subprocess
import plistlib
import time
import sys
import os
import logging

# Read idle timeout from environment variable, default to 15 minutes (900 seconds)
TIMEOUT_ENV = os.environ.get("AUTOEJECT_TIMEOUT")
if TIMEOUT_ENV:
    try:
        IDLE_TIMEOUT_SECONDS = float(TIMEOUT_ENV)
    except ValueError:
        IDLE_TIMEOUT_SECONDS = 15 * 60
else:
    IDLE_TIMEOUT_SECONDS = 15 * 60

POLL_INTERVAL_SECONDS = 30

# List of process names to ignore when checking if a volume is in use.
# These are typical macOS background indexing, sync, or system helper processes.
IGNORED_PROCESSES = {
    'mds', 'mds_stores', 'fseventsd', 'Spotlight', 'sharedfilelistd',
    'quicklookd', 'QuickLookUIService', 'corespotlightd', 'cloudd',
    'dbfseventsd', 'livefilesd', 'HazelFind'
}

def get_mounted_images():
    """Retrieve all mounted disk images and their mount points using hdiutil."""
    try:
        res = subprocess.run(["hdiutil", "info", "-plist"], capture_output=True, check=True)
        data = plistlib.loads(res.stdout)
        images = []
        for img in data.get("images", []):
            image_path = img.get("image-path")
            mount_points = []
            for entity in img.get("system-entities", []):
                mp = entity.get("mount-point")
                if mp:
                    mount_points.append(mp)
            if image_path and mount_points:
                images.append({
                    "image_path": image_path,
                    "mount_points": mount_points
                })
        return images
    except Exception as e:
        logging.error(f"Error calling hdiutil info: {e}")
        return []

def get_open_files(mount_point):
    """Run lsof to get a list of active processes and their open files under the mount point."""
    try:
        # lsof -F cpn returns machine readable output:
        # p<PID>
        # c<Command Name>
        # f<FD>
        # n<File Name>
        res = subprocess.run(["lsof", "-F", "cpn", mount_point], capture_output=True, text=True)
        # lsof returns exit code 1 if no files are open, which is a normal state
        if res.returncode != 0 and not res.stdout:
            return []
        
        processes = []
        current_proc = {}
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            char = line[0]
            val = line[1:]
            if char == 'p':
                if current_proc:
                    processes.append(current_proc)
                current_proc = {'pid': val, 'files': []}
            elif char == 'c':
                current_proc['name'] = val
            elif char == 'f':
                current_proc['fd'] = val
            elif char == 'n':
                current_proc['files'].append(val)
                
        if current_proc:
            processes.append(current_proc)
            
        return processes
    except Exception as e:
        logging.error(f"Error running lsof on {mount_point}: {e}")
        return []

def is_in_use(mount_points):
    """Check if any of the mount points are actively being used by user processes."""
    active_procs = []
    my_pid = str(os.getpid())
    
    for mp in mount_points:
        procs = get_open_files(mp)
        for p in procs:
            name = p.get('name')
            pid = p.get('pid')
            
            # Skip if it's this python script, the lsof call itself, or in the ignored list
            if pid == my_pid:
                continue
            if name == 'lsof':
                continue
            if name in IGNORED_PROCESSES:
                continue
                
            active_procs.append({
                'mount_point': mp,
                'pid': pid,
                'name': name,
                'files': p.get('files', [])
            })
            
    return len(active_procs) > 0, active_procs

def eject_image(mount_point):
    """Safely detach/eject the disk image associated with the mount point."""
    logging.info(f"Attempting to eject volume: {mount_point}")
    try:
        res = subprocess.run(["hdiutil", "detach", mount_point], capture_output=True, text=True)
        if res.returncode == 0:
            logging.info(f"Successfully ejected: {mount_point}")
            return True
        else:
            logging.error(f"Failed to eject {mount_point}: {res.stderr.strip()}")
            return False
    except Exception as e:
        logging.error(f"Exception while ejecting {mount_point}: {e}")
        return False

def main():
    # Configure logging to write to stdout (LaunchAgent redirects this to a log file)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.info(f"Auto-eject daemon started. Timeout: {IDLE_TIMEOUT_SECONDS}s. Polling interval: {POLL_INTERVAL_SECONDS}s.")

    # State tracking dictionaries
    last_active = {}       # image_path -> float (timestamp)
    last_state = {}        # image_path -> str ("active" | "idle")
    last_logged_idle = {}  # image_path -> float (timestamp when last logged)

    while True:
        try:
            current_time = time.time()
            mounted_images = get_mounted_images()
            currently_mounted_paths = set()
            
            for img in mounted_images:
                path = img["image_path"]
                mps = img["mount_points"]
                currently_mounted_paths.add(path)
                
                in_use, active_procs = is_in_use(mps)
                
                if in_use:
                    # Log transition to active
                    if last_state.get(path) != "active":
                        proc_details = ", ".join([f"{p['name']}(PID:{p['pid']})" for p in active_procs[:3]])
                        if len(active_procs) > 3:
                            proc_details += "..."
                        logging.info(f"Image {path} is active. In use by: {proc_details}")
                        last_state[path] = "active"
                    last_active[path] = current_time
                    last_logged_idle.pop(path, None)  # Reset logging interval
                else:
                    # Newly detected image or transition to idle
                    if path not in last_active:
                        last_active[path] = current_time
                        last_state[path] = "idle"
                        logging.info(f"Detected disk image: {path} (mounted at {mps}). Initialized as idle.")
                    elif last_state.get(path) != "idle":
                        logging.info(f"Image {path} became idle. Timer started.")
                        last_state[path] = "idle"
                        last_active[path] = current_time
                    
                    idle_duration = current_time - last_active[path]
                    
                    # Log idle duration only every 5 minutes (300s), or when it is close to ejecting (within 60s)
                    last_log_time = last_logged_idle.get(path, 0)
                    time_since_last_log = current_time - last_log_time
                    should_log_idle = (time_since_last_log >= 300) or (IDLE_TIMEOUT_SECONDS - idle_duration <= 60 and time_since_last_log >= 30)
                    
                    if should_log_idle:
                        logging.info(f"Image {path} has been idle for {idle_duration:.0f}s (limit: {IDLE_TIMEOUT_SECONDS}s)")
                        last_logged_idle[path] = current_time
                    
                    # Check timeout and eject
                    if idle_duration >= IDLE_TIMEOUT_SECONDS:
                        if eject_image(mps[0]):
                            last_active.pop(path, None)
                            last_state.pop(path, None)
                            last_logged_idle.pop(path, None)
            
            # Clean up tracking for images that were manually unmounted by the user
            for path in list(last_active.keys()):
                if path not in currently_mounted_paths:
                    logging.info(f"Image {path} was manually unmounted. Removing from tracking.")
                    last_active.pop(path, None)
                    last_state.pop(path, None)
                    last_logged_idle.pop(path, None)
                    
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
            
        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
