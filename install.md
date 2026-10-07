# 安装与设备交接

## 新工作区

需要 Git、Python 3.9+。无需网页服务、Node、Agent CLI 或独立数据库。

```bash
git clone git@github.com:lapixiaoxin/quant.git "$HOME/Quant"
cd "$HOME/Quant"
sh scripts/install.sh
./scripts/check.sh
./quant doctor
```

安装仅在当前工作区创建 `.venv`，安装 Python 依赖并检查配置。首次运行从
`config/config.example.toml` 复制本机配置，权限为 0600。既有配置不会被覆盖。
升级使用 `git pull --ff-only origin main`，再运行安装和检查。

Agent 自身的联网、Python 分析工具和飞书连接由其运行环境提供，不写入本工程。
飞书研究根目录和归档契约见 `AGENTS.md` 与 `research/README.md`。
飞书需要用户登录以及对应 Wiki 的读写权限；`doctor` 只检查本地状态。

## 旧版服务迁移

旧版可能在 `~/.local/share/quant-monitor` 保存独立运行副本，并加载以下服务：

```text
com.local.quant-monitor.daily
com.local.quant-monitor.remote
com.local.etf-monitor
```

先停用并检查：

```bash
sh scripts/stop_legacy_services.sh
```

脚本对上述固定服务调用 `launchctl disable` 和 `bootout`，再检查未加载。
它保留旧配置、日志和运行数据。若权限阻断或服务仍加载，脚本返回失败，
不得将删除仓库代码视作停止了旧服务；需在有权限的本机终端完成。
不要重新运行历史版本的服务安装脚本。

核对仓库与旧运行目录的 SQLite 完整性、各表行数、时间覆盖和独有快照。
空库或较旧运行副本不得覆盖当前库；有独有资料时先备份，再有针对性导入。
本次重构不再提供会覆盖数据库的运行副本同步命令。

若 `.venv` 是指向旧运行目录的符号链接，安装脚本会停止并提示。确认后仅移除
该符号链接，在工作区重建 `.venv`；不要删除其指向的未知运行数据。

## 单写者交接与备份

同一时刻仅一台设备写入和提交 SQLite。旧设备停止所有写入后，以
SQLite `backup` API 导出一致副本，或在确认没有写入进程时执行
`PRAGMA wal_checkpoint(TRUNCATE)`，并检查 `PRAGMA integrity_check` 为 `ok`。
确认主库包含全部事务后再提交；不得删除仍在使用的 WAL 来“清理”事务。

检查敏感信息和文件体积后提交并推送，接管设备再拉取。
若两端已有不同数据，先分别备份并比较，不能用 Git 自动合并二进制。
`config/config.toml`、凭证、日志、虚拟环境、SQLite WAL/SHM/JOURNAL 和
文档索引锁文件均不提交。

当前仓库为私有。未来公开前需清理 Git 历史中的个人研究与数据。
