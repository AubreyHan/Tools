# GitHub 自动同步守护进程 (GitHub Auto-Sync Daemon)

这是一个专为 macOS 设计的轻量级后台自动同步守护进程。它能够实时监控本地 Git 仓库，并在本地修改后自动提交与推送；同时定期拉取远程仓库的更新，并能够自动处理冲突。

---

## 🌟 核心功能

1. **自动库检测**：定时扫描指定的根目录，识别所有配置了 GitHub 远程链接的仓库，并动态将其加入监控列表。
2. **本地变更自动推送**：利用 `watchdog` 监听文件修改，采用 **10秒防抖 (Debounce) 机制**，在修改停止 10 秒后自动执行 `git commit` 和 `git push`。
3. **远程变更自动拉取**：每隔 60 秒自动执行 `git fetch`，检测到远程有更新时自动拉取。
4. **冲突自动解决**：拉取时采用 `ours` 策略（默认优先保留本地修改），如遇冲突会自动执行 `checkout --ours` 并提交推送，确保同步不中断且本地修改不丢失。
5. **开机自启**：注册为 macOS 的 `launchd` 用户级守护进程 (LaunchAgent)，开机自动运行。
6. **系统通知**：同步完成后，通过 macOS 原生系统通知展示同步成功的文件夹及操作。

---

## 📂 目录结构

服务运行在用户隐藏目录 `~/.github_sync` 中：
* `github_sync_daemon.py`：守护进程主程序（核心逻辑）。
* `config.json`：服务配置文件。
* `install.sh`：安装、重启与部署脚本。
* `daemon.log`：运行日志文件。
* `venv/`：Python 虚拟环境（包含 `watchdog` 依赖）。

---

## ⚙️ 配置文件说明 (`config.json`)

你可以通过修改 `~/.github_sync/config.json` 来定制服务：

```json
{
  "search_roots": ["~"],                         // 扫描 Git 仓库的根目录列表
  "exclude_dirs": [                              // 扫描时排除的文件夹（提高性能）
    "Library", "Downloads", "Movies", "Music", "Pictures", "Public",
    ".Trash", ".gemini", ".cache", ".config", ".local", ".oh-my-zsh",
    ".git", "node_modules", "venv", ".venv"
  ],
  "scan_interval_seconds": 300,                  // 扫描新 Git 仓库的间隔（秒）
  "remote_poll_interval_seconds": 60,            // 轮询远程 GitHub 变更的间隔（秒）
  "debounce_seconds": 10,                         // 本地修改防抖等待时间（秒）
  "conflict_strategy": "ours",                   // 冲突解决策略 ("ours" 或 "theirs")
  "log_level": "INFO"                            // 日志级别 (DEBUG, INFO, WARNING, ERROR)
}
```
*修改配置后，请运行 `~/.github_sync/install.sh` 重启服务以生效。*

---

## 🚀 迁移至新电脑配置步骤

由于项目内所有路径均使用动态变量，迁移十分便捷：

### 1. 在当前电脑打包
在当前电脑的终端运行以下命令，打包核心文件：
```bash
tar -czf github_sync_backup.tar.gz -C ~/.github_sync github_sync_daemon.py config.json install.sh README.md
```

### 2. 将压缩包发送至新电脑
使用隔空投送 (AirDrop)、`scp` 或 U 盘等方式，将 `github_sync_backup.tar.gz` 发送到新电脑。

### 3. 在新电脑一键部署
在新电脑终端运行以下命令即可完成安装并自动启动服务：
```bash
# 创建隐藏目录并解包
mkdir -p ~/.github_sync
tar -xzf github_sync_backup.tar.gz -C ~/.github_sync

# 授权并运行安装脚本
chmod +x ~/.github_sync/install.sh
~/.github_sync/install.sh
```

---

## 🛠️ 运维与调试

### 查看实时同步日志
```bash
tail -f ~/.github_sync/daemon.log
```

### 检查服务运行状态
```bash
launchctl list | grep githubsync
```
*如果输出中第一列显示了数字（PID），说明服务正在正常运行。*

### 手动重启服务
```bash
~/.github_sync/install.sh
```

### 卸载服务
若想彻底停用并卸载该同步服务，请运行：
```bash
launchctl unload ~/Library/LaunchAgents/com.user.githubsync.plist
rm ~/Library/LaunchAgents/com.user.githubsync.plist
rm -rf ~/.github_sync
```

---

## ⚠️ 注意事项
* **Git 凭证**：请确保你的电脑已经配置好 GitHub 的免密推送权限（通过 SSH 密钥或 macOS Keychain 凭证助手）。如果手动执行 `git push` 需要输入密码，则自动同步会失败，具体报错可在 `daemon.log` 中查看。
* **文件冲突**：默认的冲突解决策略是 `ours`，在遇到难以自动合并的代码冲突时，会以本地修改为准覆盖远程相应冲突行。
