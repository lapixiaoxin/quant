# Quant Monitor

面向个人长期投资研究的本地行情监控与分析工程。程序负责可验证的行情、指标和策略基线，研究 Skill 按产品和标的画像补充基本面与市场语境；系统不自动交易。

## 当前能力

- ETF、股票、指数统一标的模型。
- 产品大类默认值与单标的个性化覆盖。
- 可配置的多策略画像、研究画像、通知策略和通知通道。
- 东方财富行情采集，失败后自动降级腾讯。
- SQLite 日线历史库、JSON 审计快照、Markdown 报告和静态本地看板。
- 可版本化的策略目录、回测领域契约和 HTML 研究知识库。
- schema v3 将最终研究与通知计划交给 TRAE，避免代理入口硬编码 ETF。
- TraeCode CLI 非交互定时研究，并在 CLI 不可用时按配置降级。
- 基于 lark-cli WebSocket 的飞书白名单远程命令。

详细约束见 [AGENTS.md](AGENTS.md)，技术设计见
[docs/architecture.md](docs/architecture.md)。

一站式文档入口：[docs/index.html](docs/index.html)。
研究知识库入口：[research/index.html](research/index.html)。

- 新设备部署：[install.md](install.md)
- 当前能力与边界：[capabilities.md](capabilities.md)

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
    data/latest schema v3 执行计划
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
./quant prepare --symbol 515100
./quant daily --symbol 515100
./quant daily --all
./quant automate --all --no-send
./quant base-report --symbol 515100
./quant dashboard
./quant listen --check
./quant send-report data/reports/YYYY-MM-DD/515100-research.md \
  --symbol 515100 \
  --event agent_report
```

发送命令不会直接选择飞书，而是按该标的的通知策略校验事件并路由通道。

`automate` 有两种模式：

- `base`：无需大模型的确定性基础分析。
- `traecli`：非交互执行 `/instrument-daily` 完成联网研究；CLI 不可用时可降级为 `base`。

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
```

TraeCode CLI 的同语义命令位于
`.traecli/commands/instrument-daily.md`。两种入口都读取 schema v3
`research_plan`，因此新增产品类型或标的画像时不需要复制 ETF 专用命令。

引导脚本在字节内场网络优先安装内部版 TraeCode CLI，其他环境回退公开版。
项目还会识别官方默认路径 `~/.local/bin/traecli`，不依赖交互式 shell 的 PATH。

## 研究知识库

人与 Agent 讨论后的整理结果放在 `research/`：

```text
research/library/   可提交、经过脱敏的通用经验
research/private/   具体标的、持仓语境和个人计划，默认不提交 Git
research/methods/   数据、策略与回测方法说明
research/templates/ HTML 讨论报告模板
```

具体标的讨论默认保存为
`research/private/<标的代码>/<YYYY-MM-DD>-<主题>.html`。报告记录事实、
来源、假设、结论、反例和失效条件，不直接保存冗长聊天原文。

## 飞书远程命令

启用 `[remote]` 并完成 lark-cli 长连接配置后，支持：

```text
/quant status
/quant analyze 515100
/quant base 515100
/quant prepare 515100
/quant dashboard
/quant help
```

只处理白名单发送人或群聊，未知命令不会转为 Shell。详细配置见
[install.md](install.md)。

## 数据目录

```text
data/latest/                 最新 schema v3 数据包、提示和基础报告
data/snapshots/YYYY-MM-DD/   带采集时刻的不可变快照
data/reports/YYYY-MM-DD/     基础报告和研究代理报告
data/dashboard/              静态本地看板
data/history/market.sqlite3  标准化日线历史库
```

`data/latest` 是配置解析后的运行产物，不应手工修改。每次成功采集会把日线
幂等写入 SQLite；JSON 快照继续保留单次任务的审计上下文。盘中快照不是最终
收盘价；研究前必须检查 `as_of`、交易日和 `data_quality`。

当前 SQLite 适合单机、日线和中长线研究，无需部署数据库服务。回测输入契约
已经建立，但撮合、参数优化和样本外评估引擎尚未交付，不能把当前关注度策略
当作已验证的买卖信号。

## GitHub 协作

远端仓库：

```text
git@github.com:lapixiaoxin/quant.git
```

当前采用直接维护 `main` 的方式。每次改动完成后执行质量检查和敏感信息审计，再提交并推送 `origin/main`。本机配置、运行数据、日志、虚拟环境和凭证均由 `.gitignore` 排除。

## 安全边界

- 不提交或输出通知凭证、持仓隐私和本机配置。
- 远程入口只调用白名单应用用例，不执行任意 Shell。
- 技术指标由程序计算，研究代理不重复手算。
- 基本面事实标注来源与时间，缺失数据不补造。
- 数据异常时不输出方向性结论。
- 没有资金规则时不建议具体买入金额。
