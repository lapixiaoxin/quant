# Quant Monitor

面向个人长期投资研究的本地行情监控与分析工程。程序负责可验证的行情、指标和策略基线，研究 Skill 按产品和标的画像补充基本面与市场语境；系统不自动交易。

## 当前能力

- ETF、股票、指数统一标的模型。
- 产品大类默认值与单标的个性化覆盖。
- 可配置的多策略画像、研究画像、通知策略和通知通道。
- 东方财富行情采集，失败后自动降级腾讯。
- JSON 快照、Markdown 基础报告、飞书路由和静态本地看板。
- schema v3 将最终研究与通知计划交给 TRAE，避免代理入口硬编码 ETF。

详细约束见 [AGENTS.md](AGENTS.md)，技术设计见
[docs/architecture.md](docs/architecture.md)。

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
events = ["manual", "base_report", "agent_report"]
title_template = "{symbol} {name} 研究简报"

[notification_channels.feishu_primary]
type = "feishu"
enabled = false
mode = "app"
app_secret_env = "FEISHU_APP_SECRET"
receive_id_env = "FEISHU_RECEIVE_ID"

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

安装脚本创建 `.venv`、开发检查工具、本机配置和工作日 14:00 的
`launchd` 任务。敏感值仅通过环境变量或 macOS 钥匙串提供：

```bash
export FEISHU_APP_SECRET="<app-secret>"
export FEISHU_RECEIVE_ID="<群聊 chat_id>"
```

## 常用命令

```bash
./quant doctor
./quant instruments
./quant prepare --symbol 515100
./quant daily --symbol 515100
./quant daily --all
./quant base-report --symbol 515100
./quant dashboard
./quant send-report data/reports/YYYY-MM-DD/515100-research.md \
  --symbol 515100 \
  --event agent_report
```

发送命令不会直接选择飞书，而是按该标的的通知策略校验事件并路由通道。

定时任务管理：

```bash
./scripts/service.sh status
./scripts/service.sh run-now
./scripts/service.sh stop
./scripts/service.sh start
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

## 数据目录

```text
data/latest/                 最新 schema v3 数据包、提示和基础报告
data/snapshots/YYYY-MM-DD/   带采集时刻的不可变快照
data/reports/YYYY-MM-DD/     基础报告和研究代理报告
data/dashboard/              静态本地看板
```

`data/latest` 是配置解析后的运行产物，不应手工修改。盘中快照不是最终收盘价；研究前必须检查 `as_of`、交易日和 `data_quality`。

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
