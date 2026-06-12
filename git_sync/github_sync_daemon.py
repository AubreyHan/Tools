import os
import sys
import json
import time
import subprocess
import logging
import threading
from datetime import datetime
import signal

# Add common Homebrew and user binary paths to PATH to ensure git/osascript are found
env_path = os.environ.get('PATH', '')
additional_paths = ['/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin']
for p in additional_paths:
    if p not in env_path:
        env_path = f"{p}:{env_path}"
os.environ['PATH'] = env_path

# Import watchdog
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("Error: watchdog library not installed in this environment.", file=sys.stderr)
    sys.exit(1)

# Configuration defaults
DEFAULT_CONFIG = {
    "search_roots": ["~"],
    "exclude_dirs": [
        "Library", "Downloads", "Movies", "Music", "Pictures", "Public",
        ".Trash", ".gemini", ".cache", ".config", ".local", ".oh-my-zsh",
        ".git", "node_modules", "venv", ".venv"
    ],
    "scan_interval_seconds": 300,
    "remote_poll_interval_seconds": 60,
    "debounce_seconds": 10,
    "conflict_strategy": "ours",
    "log_level": "INFO"
}

# Globals
config = {}
monitored_repos = {}  # repo_path -> watch_descriptor
monitored_repos_lock = threading.Lock()
repo_locks = {}
locks_lock = threading.Lock()
sync_timers = {}
timers_lock = threading.Lock()
stop_event = threading.Event()
observer = Observer()

def load_config():
    global config
    config_path = os.environ.get('GITHUB_SYNC_CONFIG', os.path.expanduser('~/.github_sync/config.json'))
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                loaded = json.load(f)
                config = {**DEFAULT_CONFIG, **loaded}
        except Exception as e:
            print(f"Error loading config, using defaults: {e}", file=sys.stderr)
            config = DEFAULT_CONFIG.copy()
    else:
        config = DEFAULT_CONFIG.copy()
        # Ensure the directory exists and write default config
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error writing default config: {e}", file=sys.stderr)

def setup_logging():
    log_level_str = config.get('log_level', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Clear existing handlers
    logger.handlers = []
    
    # Stream handler (stdout) - launchd redirects stdout to daemon.log,
    # so we only need to write to stdout to avoid duplicate logging.
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(stream_handler)
    
    logging.info("Logging initialized.")

def send_notification(title, message):
    try:
        escaped_title = title.replace('"', '\\"')
        escaped_message = message.replace('"', '\\"')
        script = f'display notification "{escaped_message}" with title "GitHub Auto-Sync" subtitle "{escaped_title}"'
        subprocess.run(['osascript', '-e', script], check=True)
    except Exception as e:
        logging.error(f"Failed to send notification: {e}")

def git_cmd(repo_path, args, ignore_errors=False):
    cmd = ['git', '-C', repo_path] + args
    try:
        logging.debug(f"Running: {' '.join(cmd)}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return True, res.stdout.strip(), res.stderr.strip()
    except subprocess.CalledProcessError as e:
        if not ignore_errors:
            logging.error(f"Git command failed: {' '.join(cmd)}")
            logging.error(f"Stdout: {e.stdout.strip()}")
            logging.error(f"Stderr: {e.stderr.strip()}")
        return False, e.stdout.strip(), e.stderr.strip()

def is_github_repo(path):
    git_config = os.path.join(path, '.git', 'config')
    if not os.path.isfile(git_config):
        return False
    try:
        with open(git_config, 'r', errors='ignore') as f:
            content = f.read()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('url =') or line.startswith('url='):
                    if 'github.com' in line:
                        return True
    except Exception:
        pass
    return False

class GitRepoHandler(FileSystemEventHandler):
    def __init__(self, repo_path, on_change_callback):
        super().__init__()
        self.repo_path = repo_path
        self.on_change_callback = on_change_callback

    def on_any_event(self, event):
        if event.is_directory:
            return
        
        path = event.src_path
        # Ignore .git folder changes, common temp/dependency folders
        ignored_parts = ['.git/', 'node_modules/', 'venv/', '.venv/', '__pycache__/', '.DS_Store', '.git~']
        for part in ignored_parts:
            if part in path or path.endswith(part.strip('/')):
                return
        
        self.on_change_callback(self.repo_path)

def get_repo_lock(repo_path):
    with locks_lock:
        if repo_path not in repo_locks:
            repo_locks[repo_path] = threading.Lock()
        return repo_locks[repo_path]

def sync_repo(repo_path, conflict_strategy):
    success, branch, err = git_cmd(repo_path, ['branch', '--show-current'])
    if not success or not branch:
        success, branch, err = git_cmd(repo_path, ['rev-parse', '--abbrev-ref', 'HEAD'])
        if not success or branch == 'HEAD' or not branch:
            logging.warning(f"Could not determine branch for {repo_path}, skipping sync.")
            return False

    logging.info(f"Syncing {repo_path} on branch {branch}...")

    # 1. Check local changes
    _, status_out, _ = git_cmd(repo_path, ['status', '--porcelain'])
    local_changes = bool(status_out.strip())

    committed_local = False
    if local_changes:
        logging.info(f"Local changes detected in {repo_path}. Committing...")
        git_cmd(repo_path, ['add', '-A'])
        commit_msg = f"Auto-sync: local changes {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        success, _, commit_err = git_cmd(repo_path, ['commit', '-m', commit_msg])
        if success:
            committed_local = True
            logging.info(f"Committed local changes in {repo_path}")
        else:
            logging.error(f"Failed to commit local changes in {repo_path}: {commit_err}")
            _, status_out, _ = git_cmd(repo_path, ['status', '--porcelain'])
            if status_out.strip():
                logging.error(f"Local changes still present but commit failed. Aborting sync.")
                return False

    # 2. Fetch remote
    logging.debug(f"Fetching remote for {repo_path}...")
    success, _, fetch_err = git_cmd(repo_path, ['fetch', 'origin'])
    if not success:
        logging.error(f"Failed to fetch remote for {repo_path}: {fetch_err}")
        return False

    # 3. Check if remote exists for this branch
    success_remote_rev, remote_rev, _ = git_cmd(repo_path, ['rev-parse', f'origin/{branch}'], ignore_errors=True)
    
    pulled_remote = False
    pushed_local = False

    if not success_remote_rev:
        # Remote branch does not exist yet (new branch or first push)
        logging.info(f"Remote branch origin/{branch} does not exist. Pushing to set upstream...")
        success, _, push_err = git_cmd(repo_path, ['push', '-u', 'origin', branch])
        if success:
            pushed_local = True
            logging.info(f"Pushed branch {branch} to remote origin successfully.")
        else:
            logging.error(f"Failed to push new branch to remote: {push_err}")
            return False
    else:
        # Check rev lists to see if we are behind/ahead
        success_behind, behind_count, _ = git_cmd(repo_path, ['rev-list', '--count', f'HEAD..origin/{branch}'])
        remote_ahead = success_behind and behind_count.strip() != '0'

        if remote_ahead:
            logging.info(f"Remote is ahead for {repo_path} by {behind_count} commits. Pulling...")
            pull_args = ['pull', '--no-rebase']
            if conflict_strategy in ['ours', 'theirs']:
                pull_args.extend(['-X', conflict_strategy])
            pull_args.extend(['origin', branch])

            success, _, pull_err = git_cmd(repo_path, pull_args)
            if success:
                pulled_remote = True
                logging.info(f"Pulled remote changes successfully for {repo_path}")
            else:
                logging.warning(f"Pull failed for {repo_path}. Checking for unresolved conflicts...")
                success_diff, diff_out, _ = git_cmd(repo_path, ['diff', '--name-only', '--diff-filter=U'])
                unmerged_files = diff_out.strip().splitlines() if success_diff else []

                if unmerged_files:
                    logging.info(f"Resolving conflicts automatically in {repo_path} using strategy: {conflict_strategy}")
                    if conflict_strategy == 'theirs':
                        git_cmd(repo_path, ['checkout', '--theirs', '.'])
                    else:  # default to ours
                        git_cmd(repo_path, ['checkout', '--ours', '.'])
                    
                    git_cmd(repo_path, ['add', '-A'])
                    git_cmd(repo_path, ['commit', '-m', f"Auto-sync: resolved conflicts using {conflict_strategy}"])
                    pulled_remote = True
                    logging.info(f"Resolved conflicts and completed pull for {repo_path}")
                else:
                    logging.error(f"Pull failed due to non-conflict issues in {repo_path}: {pull_err}")
                    return False

        # Re-check if local is ahead (either from our commit or from conflict resolution)
        success_ahead, ahead_count, _ = git_cmd(repo_path, ['rev-list', '--count', f'origin/{branch}..HEAD'])
        local_ahead = success_ahead and ahead_count.strip() != '0'

        if local_ahead:
            logging.info(f"Local is ahead for {repo_path} by {ahead_count} commits. Pushing...")
            success, _, push_err = git_cmd(repo_path, ['push', 'origin', branch])
            if success:
                pushed_local = True
                logging.info(f"Pushed changes successfully for {repo_path}")
            else:
                logging.error(f"Failed to push changes for {repo_path}: {push_err}")
                return False

    if committed_local or pulled_remote or pushed_local:
        repo_name = os.path.basename(repo_path)
        msg_parts = []
        if committed_local or pushed_local:
            msg_parts.append("推送了本地修改")
        if pulled_remote:
            msg_parts.append("拉取了远程修改")
        action_msg = " & ".join(msg_parts) if msg_parts else "同步完成"
        send_notification(repo_name, f"同步成功: {action_msg}")
        return True

    return False

def run_sync_task(repo_path):
    if not os.path.isdir(repo_path):
        logging.debug(f"Directory {repo_path} no longer exists, skipping sync.")
        return
    lock = get_repo_lock(repo_path)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        logging.debug(f"Sync already in progress for {repo_path}, skipping concurrent run.")
        return
    try:
        sync_repo(repo_path, config['conflict_strategy'])
    except Exception as e:
        logging.error(f"Error syncing {repo_path}: {e}", exc_info=True)
    finally:
        lock.release()

def trigger_sync(repo_path):
    with timers_lock:
        if repo_path in sync_timers:
            del sync_timers[repo_path]
    run_sync_task(repo_path)

def on_repo_changed(repo_path):
    debounce_seconds = config.get('debounce_seconds', 10)
    with timers_lock:
        if repo_path in sync_timers:
            sync_timers[repo_path].cancel()
            logging.debug(f"Resetting debounce timer for {repo_path}")
        
        timer = threading.Timer(debounce_seconds, trigger_sync, args=[repo_path])
        sync_timers[repo_path] = timer
        timer.start()
        logging.debug(f"Scheduled sync for {repo_path} in {debounce_seconds} seconds")

def start_monitoring(repo_path):
    try:
        event_handler = GitRepoHandler(repo_path, on_repo_changed)
        watch = observer.schedule(event_handler, repo_path, recursive=True)
        monitored_repos[repo_path] = watch
        logging.info(f"Started monitoring: {repo_path}")
        # Run initial sync in background
        threading.Thread(target=run_sync_task, args=[repo_path], daemon=True).start()
    except Exception as e:
        logging.error(f"Failed to start monitoring {repo_path}: {e}")

def stop_monitoring(repo_path):
    watch = monitored_repos.pop(repo_path, None)
    if watch:
        try:
            observer.unschedule(watch)
            logging.info(f"Stopped monitoring: {repo_path}")
        except Exception as e:
            logging.error(f"Failed to stop monitoring {repo_path}: {e}")

def scan_for_repos():
    logging.info("Scanning for Git repositories...")
    found_repos = set()
    
    exclude_set = set(config.get('exclude_dirs', []))
    search_roots = config.get('search_roots', ["~"])
    
    for root_path in search_roots:
        root_path = os.path.expanduser(root_path)
        if not os.path.isdir(root_path):
            logging.warning(f"Search root does not exist: {root_path}")
            continue
            
        for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
            # If .git is in dirnames, we handle this repository and clear dirnames so we don't walk into it
            if '.git' in dirnames:
                if is_github_repo(dirpath):
                    found_repos.add(dirpath)
                dirnames.clear()
            else:
                # Prune directory names starting with '.' or in exclude list in-place
                dirnames[:] = [d for d in dirnames if d not in exclude_set and not d.startswith('.')]

    with monitored_repos_lock:
        current_repos = set(monitored_repos.keys())
        
        # Repos to add
        new_repos = found_repos - current_repos
        for repo in new_repos:
            start_monitoring(repo)
            
        # Repos to remove
        removed_repos = current_repos - found_repos
        for repo in removed_repos:
            stop_monitoring(repo)
            
    logging.info(f"Scan complete. Currently monitoring {len(monitored_repos)} repositories.")

def scan_loop():
    scan_interval = config.get('scan_interval_seconds', 300)
    while not stop_event.is_set():
        try:
            scan_for_repos()
        except Exception as e:
            logging.error(f"Error in scan loop: {e}", exc_info=True)
        stop_event.wait(scan_interval)

def remote_poll_loop():
    poll_interval = config.get('remote_poll_interval_seconds', 60)
    while not stop_event.is_set():
        stop_event.wait(poll_interval)
        if stop_event.is_set():
            break
            
        with monitored_repos_lock:
            repos = list(monitored_repos.keys())
            
        for repo_path in repos:
            if stop_event.is_set():
                break
            # Only trigger sync if the local directory still exists
            if os.path.isdir(repo_path):
                # Trigger sync check in a background thread for each repository
                threading.Thread(target=run_sync_task, args=[repo_path], daemon=True).start()

def signal_handler(signum, frame):
    logging.info(f"Received signal {signum}, shutting down daemon...")
    stop_event.set()

def main():
    load_config()
    setup_logging()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logging.info("Starting file observer...")
    observer.start()
    
    # Run initial scan synchronously to find existing repos immediately
    try:
        scan_for_repos()
    except Exception as e:
        logging.error(f"Initial scan failed: {e}", exc_info=True)
        
    # Start scanner and poller loops in background threads
    scanner_thread = threading.Thread(target=scan_loop, daemon=True)
    scanner_thread.start()
    
    poller_thread = threading.Thread(target=remote_poll_loop, daemon=True)
    poller_thread.start()
    
    logging.info("Daemon is running. Press Ctrl+C or send SIGTERM to stop.")
    
    while not stop_event.is_set():
        time.sleep(1)
        
    logging.info("Shutting down observer...")
    observer.stop()
    observer.join()
    
    # Cancel all pending debounce timers
    with timers_lock:
        for timer in sync_timers.values():
            timer.cancel()
            
    logging.info("Daemon stopped.")

if __name__ == '__main__':
    main()
