# Quant Monitor 自动化安装指南

本文面向在一台新 macOS 设备上执行部署的 Agent。目标是完成代码安装、飞书出站、定时研究以及可选的飞书远程命令。

## 1. 部署结果

完整部署后可获得两个独立服务：

| 服务 | 作用 | 启用条件 |
|---|---|---|
| `com.local.quant-monitor.daily` | 工作日定时分析、生成看板并按策略推送 | `automation.enabled = true` |
| `com.local.quant-monitor.remote` | 通过飞书 WebSocket 接收白名单命令 | `remote.enabled = true` 且 `lark-cli` 就绪 |

自动化有两个等级：

- `base`：完全本地、确定性分析，无需大模型，适合作为可靠降级。
- `traecli`：TraeCode CLI 非交互运行 `/instrument-analyze`，按标准请求执行联网研究并按通知策略推送。

## 2. 系统前置条件

- macOS。
- Git。
- Python 3.9 或更高版本。
- SSH 已有权限访问 `git@github.com:lapixiaoxin/quant.git`。
- 完整 Agent 研究需要 TraeCode CLI。
- 飞书远程命令需要 Node.js、npm 和 `lark-cli`。

TraeCode CLI 官方安装与非交互模式文档：

- <https://docs.trae.cn/cli_get-started-with-trae-cli>
- <https://docs.trae.cn/cli_use-cases>

字节内场设备必须使用内部版。`bootstrap_macos.sh --with-traecli` 会先尝试
内部安装器，内场不可达时再回退公开版；也可用 `TRAECLI_INSTALL_URL`
显式覆盖安装地址。

## 3. 快速安装

```bash
git clone git@github.com:lapixiaoxin/quant.git "$HOME/Quant"
cd "$HOME/Quant"
./scripts/bootstrap_macos.sh --with-traecli --with-lark-cli
```

也可只安装基础分析：

```bash
git clone git@github.com:lapixiaoxin/quant.git "$HOME/Quant"
cd "$HOME/Quant"
./scripts/install_macos.sh
```

安装脚本会：

1. 将最小运行副本同步到 `~/.local/share/quant-monitor`，避开 macOS 对 Documents 等目录的 LaunchAgent 访问限制。
2. 在运行目录创建 `.venv` 并安装项目与检查工具。
3. 从模板生成本机 `config/config.toml`，并以 `0600` 权限同步到运行目录。
4. 执行 `./quant doctor`。
5. 执行 `./quant site`，刷新工作台、Markdown 阅读器和历史页面导航。
6. 根据配置安装定时研究服务。
7. 仅在远程命令配置和 `lark-cli` 都就绪时安装监听服务。

## 4. 配置飞书出站

编辑 `config/config.toml`：

```toml
[notification_channels.feishu_primary]
type = "feishu"
enabled = true
mode = "app"
app_id = "<飞书应用 App ID>"
app_secret_env = "FEISHU_APP_SECRET"
receive_id = "<接收群 chat_id>"
receive_id_type = "chat_id"
keychain_service = "quant-monitor.feishu-app-secret"
```

LaunchAgent 不继承普通终端的临时环境变量，推荐把 App Secret 写入 macOS 钥匙串：

```bash
read -s FEISHU_SECRET
security add-generic-password -U \
  -a "$USER" \
  -s "quant-monitor.feishu-app-secret" \
  -w "$FEISHU_SECRET"
unset FEISHU_SECRET
```

飞书应用需要发送消息权限，机器人必须已加入目标群。

## 5. 配置完整 Agent 自动研究

安装后先验证版本、模型和非交互调用：

```bash
cd "$HOME/Quant"
~/.local/bin/traecli --version
~/.local/bin/traecli doctor
~/.local/bin/traecli models
~/.local/bin/traecli -p "只回复 OK"
```

内场版默认使用本机 Git/企业凭据，不需要单独登录。公开版首次运行
`traecli` 时可能打开账号授权。若模型列表为空，应先确认内场设备没有误装
公开版。项目会主动识别 `~/.local/bin/traecli`，LaunchAgent 不依赖 `.zshrc`。

配置：

```toml
[automation]
enabled = true
mode = "traecli"
send = true
fallback_to_base = true
traecli_path = "traecli"
query_timeout_seconds = 900
allowed_tools = ["Bash", "Read", "Write", "WebSearch"]
```

运行机制：

```text
traecli -p "/instrument-analyze <代码> <分析请求 JSON 路径>"
```

若设备找不到 `traecli` 且 `fallback_to_base = true`，任务会降级为确定性基础分析并继续按策略推送。Agent 自身执行失败时不会再次发送基础报告，避免重复消息。

不发送消息的验收命令：

```bash
./quant automate --all --no-send
```

## 6. 配置飞书远程命令

### 6.1 初始化 lark-cli

```bash
lark-cli config init --new
```

使用 Bot 身份即可，不需要用户身份登录。

### 6.2 飞书开放平台

在应用后台完成：

1. 事件与回调中选择“使用长连接接收事件”。
2. 添加事件 `im.message.receive_v1`。
3. 开通接收权限 `im:message:receive_as_bot`。
4. 开通回复权限 `im:message:send_as_bot`。
5. 发布应用版本，并确保机器人在目标群内。

### 6.3 获取白名单 ID

临时运行：

```bash
lark-cli event +subscribe \
  --event-types im.message.receive_v1 \
  --as bot \
  --compact \
  --quiet
```

向机器人发送测试消息，从输出中读取：

- `sender_id`：个人发送人白名单。
- `chat_id`：群聊白名单。配置后群内任何成员都能执行允许的命令。

### 6.4 启用远程入口

```toml
[remote]
enabled = true
prefix = "/quant"
allowed_sender_ids = ["ou_xxx"]
allowed_chat_ids = []
allowed_channel_targets = []
lark_cli_path = "lark-cli"
```

如果命令群就是某个飞书通知通道的 `chat_id`，可以避免重复 ID：

```toml
allowed_sender_ids = []
allowed_chat_ids = []
allowed_channel_targets = ["feishu_primary"]
```

必须至少配置一种白名单来源。然后重新安装服务：

```bash
./scripts/install_macos.sh
./scripts/service.sh status
```

支持的飞书命令：

```text
/quant status
/quant strategies <标的代码>
/quant analyze <标的代码> daily,moving_average
/quant analyze all daily
/quant base <标的代码>
/quant prepare <标的代码>
/quant dashboard
/quant help
```

远程入口不接受任意 Shell，不在白名单中的消息会被忽略。

## 7. 定时任务

执行时间来自：

```toml
[app]
report_time = "14:00"
```

工作日运行：

```text
./quant automate --all
```

服务操作：

```bash
./scripts/service.sh status
./scripts/service.sh restart daily
./scripts/service.sh restart remote
./scripts/service.sh run-now daily
```

日志：

```text
~/.local/share/quant-monitor/logs/daily.out.log
~/.local/share/quant-monitor/logs/daily.err.log
~/.local/share/quant-monitor/logs/remote.out.log
~/.local/share/quant-monitor/logs/remote.err.log
```

## 8. 部署验收

Agent 必须逐项执行：

```bash
./scripts/check.sh
./quant doctor
./quant instruments
./quant dashboard
./quant site
./scripts/service.sh status
```

配置真实标的后，再对该代码执行 `prepare`、`history`、`strategies`、
`base-report` 和 `automate --no-send` 验收。模板不预置示例标的。

如果启用了远程命令：

```bash
./quant listen --check
```

本地查看统一入口：

```bash
python3 -m http.server 8765 --bind 127.0.0.1
```

浏览器访问 `http://127.0.0.1:8765/`。根路径必须显示研究工作台，不能显示
仓库文件目录。

确认以下事实：

- 测试与 Ruff 全部通过。
- 最新数据包是 schema v4，并包含 `strategy_plan` 与 `analysis_plan`。
- SQLite 历史库包含当前标的日线，日期范围与行情源一致。
- 控制面 SQLite 完整性为 `ok`，分析、回测和报告状态可查询。
- `index.html` 已生成，根路径可以进入五个业务模块、看板和文档。
- 本机配置和凭证未进入 Git。
- `daily` 服务已运行或已安装。
- `remote` 仅在白名单和长连接就绪时运行。
- 首次正式推送前，先使用 `--no-send` 验证完整链路。

## 9. 更新

```bash
cd "$HOME/Quant"
git pull --ff-only origin main
./scripts/install_macos.sh
```

不要覆盖 `config/config.toml`。安装脚本只会在文件不存在时从模板创建。
每次重装都会同步源码和本机配置。私有仓库中的历史行情、控制面、分析请求、
回测、报告、看板和 `research/private/` 只用于补齐运行目录缺失文件，不覆盖
目标设备已经产生的新数据库、快照、报告或私有研究。

常驻服务产生的数据位于运行副本。由当前主写设备导出到私有仓库：

```bash
cd "$HOME/Quant"
./scripts/sync_runtime_data.sh
./scripts/check.sh
./quant doctor
git status --short
git add data research
git commit -m "data: 同步研究数据"
git push origin main
```

SQLite 不通过 Git 自动合并，同一时刻只能有一台主写设备。其他设备可以
`git pull` 后直接浏览仓库中的报告和看板，但不得同时导出并提交各自的
`market.sqlite3` 或 `research.sqlite3`。主写设备交接顺序为：旧设备停止写入、
导出、检查、提交并推送；新设备再拉取并显式用仓库数据接管运行副本：

```bash
git pull --ff-only origin main
QUANT_RUNTIME_DATA_MODE=replace ./scripts/install_macos.sh
```

`replace` 会用仓库版本覆盖运行副本中的同名数据，只能在确认目标设备没有
未同步研究产物后使用；默认 `preserve` 模式仍只补齐缺失文件。

SQLite 的 `-wal`、`-shm`、`-journal`、本机配置、日志和凭证不会进入 Git。
若未来将仓库公开，必须先清理 Git 历史中的个人数据。
