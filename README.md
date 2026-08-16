# Quant Monitor

面向个人长期投资研究的本地行情监控与分析工程。程序负责可验证的行情、指标和策略基线，研究 Skill 按产品和标的画像补充基本面与市场语境；系统不自动交易。

## 当前能力

- ETF、股票、指数统一标的模型。
- 产品大类默认值与单标的个性化覆盖。
- 可配置的多策略画像、研究画像、通知策略和通知通道。
- 东方财富行情采集，失败后自动降级腾讯。
- 增量 SQLite 日线历史库、JSON 审计快照、HTML 标的报告和静态本地看板。
- 可版本化策略生命周期、无未来数据回测执行器和 HTML 验证报告。
- 候选池发现、硬门槛初筛、证据缺口和同类标的短名单工作流。
- 标的 Markdown 推送源自动生成同名 HTML；工程 Markdown 使用独立安全阅读器。
- schema v4 动态注入启用策略、分析周期、因子、研究计划和通知计划。
- 选择、分析、回测、报告和发布状态统一登记到控制面 SQLite。
- TraeCode CLI 非交互定时研究，并在 CLI 不可用时按配置降级。
- 基于 lark-cli WebSocket 的飞书白名单远程命令。

详细约束见 [AGENTS.md](AGENTS.md)，技术设计见
[docs/architecture.md](docs/architecture.md)。

统一研究工作台：[index.html](index.html)。它自动汇总投资看板、候选筛选、
策略与回测、分析作业、报告中心、渠道状态和系统文档；原始 JSON 快照与
SQLite 不进入可视化目录。

- 研究中心：[research/index.html](research/index.html)
- 新设备部署：[install.md](install.md)
- 当前能力与边界：[capabilities.md](capabilities.md)
- 工程约束与文档路径：[AGENTS.md](AGENTS.md)

## 配置模型

行为按以下顺序解析：

```text
产品大类默认值
  ├─ 策略画像：策略实现 + 少量业务阈值
  ├─ 研究画像：Skill + 章节 + 关注项 + 来源
  └─ 通知策略：事件 + 通道 + 标题
              ↓
       单个标的覆盖或追加
              ↓
    data/latest schema v4 执行计划
```

精简示例：

```toml
[product_types.etf]
strategy_profiles = ["dividend_low_vol_default"]
research_profile = "etf_core"
notification_policy = "daily_research"
history_days = 500

[strategy_profiles.dividend_low_vol_default]
strategy = "dividend_low_vol"

[strategy_profiles.dividend_low_vol_default.parameters]
deep_drawdown = -0.08
attention_drawdown = -0.05
high_volatility = 0.25

[research_profiles.etf_core]
skill = "instrument-analyst"
sections = ["数据可靠性", "价格位置与趋势", "估值与基本面", "风险"]
focus = ["规模与费率", "指数估值", "成分结构"]
source_priorities = ["基金管理人", "指数机构", "交易所"]
max_sources = 6

[notification_policies.daily_research]
enabled = true
channels = ["feishu_primary"]
events = ["manual", "base_report", "agent_report", "scheduled_report"]
title_template = "{symbol} {name} 研究简报"

[notification_channels.feishu_primary]
type = "feishu"
enabled = false
mode = "app"
app_secret_env = "FEISHU_APP_SECRET"
receive_id_env = "FEISHU_RECEIVE_ID"

[automation]
enabled = false
mode = "traecli"
send = true
fallback_to_base = true

[remote]
enabled = false
prefix = "/quant"
allowed_sender_ids = []
allowed_chat_ids = []
allowed_channel_targets = []

[[instruments]]
symbol = "515100"
name = "红利低波100ETF景顺"
exchange = "SH"
type = "etf"
research_focus = ["红利风格相对强弱", "分红与股息可持续性"]
```

单个标的可覆盖 `strategy_profiles`、`research_profile`、
`notification_policy` 和 `history_days`，并通过 `research_focus`、
`research_instructions` 追加个性需求。完整配置见
[`config/config.example.toml`](config/config.example.toml)。

## 初始化

要求 macOS 与 Python 3.9 或更高版本：

```bash
chmod +x quant scripts/*.sh
./scripts/install_macos.sh
```

安装脚本把最小运行副本部署到 `~/.local/share/quant-monitor`，在该目录
创建 `.venv`、同步本机配置，并注册工作日 `launchd` 任务。独立运行目录可
避开 macOS 对 Documents 等目录的后台访问限制。敏感值仅通过本机配置、
环境变量或 macOS 钥匙串提供：

```bash
export FEISHU_APP_SECRET="<app-secret>"
export FEISHU_RECEIVE_ID="<群聊 chat_id>"
```

## 常用命令

```bash
./quant doctor
./quant instruments
./quant history --all
./quant strategies --symbol 515100
./quant select \
  --universe research/universes/dividend-low-vol-100-etf.toml
./quant backtest \
  --strategy-record 515100-dividend-low-vol-v1
./quant analyze --symbol 515100 \
  --cycle daily --cycle moving_average --no-send
./quant prepare --symbol 515100
./quant daily --symbol 515100
./quant daily --all
./quant automate --all --no-send
./quant base-report --symbol 515100
./quant dashboard
./quant site
./quant listen --check
./quant send-report data/reports/YYYY-MM-DD/515100-research.md \
  --symbol 515100 \
  --event agent_report
```

发送命令不会直接选择飞书，而是按该标的的通知策略校验事件并路由通道。

`site` 会刷新根工作台、五个管理模块、投资看板、标的 HTML 报告和单一返回路径。
`dashboard`、`select`、`backtest`、自动化研究和飞书分析命令也会同步刷新；
Agent 新建 Markdown 推送源后仍应执行一次 `./quant site` 生成 HTML。

本地浏览：

```bash
python3 -m http.server 8765 --bind 127.0.0.1
```

访问 <http://127.0.0.1:8765/>，不要再从文件目录或 JSON 快照进入。

`automate` 有两种模式：

- `base`：无需大模型的确定性基础分析。
- `traecli`：非交互执行 `/instrument-analyze` 标准作业；CLI 不可用时可降级为 `base`。

定时任务管理：

```bash
./scripts/service.sh status
./scripts/service.sh run-now daily
./scripts/service.sh restart remote
./scripts/service.sh stop all
./scripts/service.sh start all
```

质量检查：

```bash
./scripts/check.sh
```

## TRAE 分析

通用研究 Skill：

```text
.trae/skills/instrument-analyst/SKILL.md
```

项目命令：

```text
/instrument-daily 515100
/instrument-daily 515100 push
/instrument-analyze 515100 data/analysis/latest/<请求 ID>.json
/instrument-select dividend-low-vol-100-etf
```

TraeCode CLI 的同语义命令位于
`.traecli/commands/`。标准分析入口读取 schema v4 的 `strategy_plan`、
`analysis_plan` 和 `research_plan`，因此新增产品类型、周期或标的画像时不需要
复制 ETF 专用命令。`instrument-daily` 继续作为兼容入口。

引导脚本在字节内场网络优先安装内部版 TraeCode CLI，其他环境回退公开版。
项目还会识别官方默认路径 `~/.local/bin/traecli`，不依赖交互式 shell 的 PATH。

## 研究知识库

人与 Agent 讨论后的整理结果放在 `research/`：

```text
research/library/   可提交、经过脱敏的通用经验
research/private/   私有仓库内同步的具体标的、持仓语境和个人计划
research/methods/   数据、策略与回测方法说明
research/templates/ HTML 讨论报告模板
research/universes/ 候选池、硬门槛、低频事实与来源日期
research/selections/候选筛选工作台和深度选择报告
research/strategies/策略生命周期、参数指纹和回测模型绑定
```

具体标的讨论默认保存为
`research/private/<标的代码>/<YYYY-MM-DD>-<主题>.html`。报告记录事实、
来源、假设、结论、反例和失效条件，不直接保存冗长聊天原文。

## 飞书远程命令

启用 `[remote]` 并完成 lark-cli 长连接配置后，支持：

```text
/quant status
/quant strategies 515100
/quant analyze 515100 daily,moving_average
/quant analyze all daily
/quant base 515100
/quant prepare 515100
/quant dashboard
/quant help
```

只处理白名单发送人或群聊，未知命令不会转为 Shell。详细配置见
[install.md](install.md)。

## 数据目录

```text
data/latest/                 最新 schema v4 数据包、提示和基础报告
data/snapshots/YYYY-MM-DD/   带采集时刻的不可变快照
data/reports/YYYY-MM-DD/     基础报告和研究代理报告
data/dashboard/              静态本地看板
data/history/market.sqlite3  标准化日线历史库
data/control/research.sqlite3 统一运行索引
data/analysis/               标准分析请求及快照
data/backtests/              回测 JSON 与 HTML 验证报告
data/selections/             候选初筛数据包、快照与基础 HTML 报告
```

项目根目录的 `index.html` 是自动生成的统一研究工作台与内容目录。

`data/latest` 是配置解析后的运行产物，不应手工修改。每次成功采集会把日线
幂等写入 SQLite；JSON 快照继续保留单次任务的审计上下文。盘中快照不是最终
收盘价；研究前必须检查 `as_of`、交易日和 `data_quality`。

当前 SQLite 适合单机、日线和中长线研究，无需部署数据库服务。系统已提供
长线目标仓位回测、成本、基准、回撤、波动、换手和交易次数；尚未实现参数优化、
严格样本外评估、涨跌停、停牌、分红再投资和申赎冲击，因此不能把当前关注度
映射当作已验证的买卖信号。

当前远端仓库是私有仓库，`data/` 和 `research/private/` 会进入 Git，方便
跨设备复用。`config/config.toml`、日志、凭证和 SQLite 事务边车文件仍被忽略。
若未来改为公开仓库，必须先清理 Git 历史中的个人数据。

常驻服务写入 `~/.local/share/quant-monitor`。主写设备使用
`./scripts/sync_runtime_data.sh` 将运行数据安全导出到仓库；SQLite 不做 Git
自动合并，多设备之间必须按 [install.md](install.md) 的单写者交接流程切换。

## GitHub 协作

远端仓库：

```text
git@github.com:lapixiaoxin/quant.git
```

当前采用直接维护 `main` 的方式。每次改动完成后执行质量检查和敏感信息审计，
再提交并推送 `origin/main`。行情数据库、快照、报告、看板和私有研究允许进入
当前私有仓库；本机配置、日志、虚拟环境、SQLite 事务边车文件和凭证继续忽略。

## 安全边界

- 不提交或输出通知凭证、持仓隐私和本机配置。
- 远程入口只调用白名单应用用例，不执行任意 Shell。
- 技术指标由程序计算，研究代理不重复手算。
- 基本面事实标注来源与时间，缺失数据不补造。
- 数据异常时不输出方向性结论。
- 没有资金规则时不建议具体买入金额。
