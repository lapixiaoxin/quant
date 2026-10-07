# Quant：Agent 投资研究工作区

让 Agent 自主探索数据、提出假设、制定策略和验证模型。程序提供行情、
确定性指标、历史仓储、版本管理和可复现回测；人工负责实战决策与复盘。

人的研究资料统一放在[飞书研究目录](https://icnxcxzl7hll.feishu.cn/wiki/Nr1Aw5d6Li5cnjkyAuAcZ4x8nag)：
每个标的一篇主页，策略、研究与回测报告分别作为其子文档。
本地不再维护前端、看板、TRAE 专属命令、定时任务或 IM 通知。

## 开始

Python 3.9+，macOS 或 Linux：

```bash
sh scripts/install.sh
./quant doctor
./quant instruments
```

`config/config.toml` 不存在时从模板创建，既有文件不覆盖。只需身份字段就能研究：

```toml
[[instruments]]
symbol = "601985"
name = "中国核电"
exchange = "SH"
type = "stock"
history_days = 500
```

产品默认值、策略画像、研究关注点都可选。同标的可以绑定多套策略，
`strategy_profiles = []` 可清空类别默认策略。研究画像仅提供参考，不限制
Agent 使用的工具、来源数量与分析方法。

当前模板仅保留 `601985 中国核电`、`510720 红利国企ETF国泰` 两个研究对象，
均未绑定策略；报告与策略目录从空索引开始。

## 常用路径

```bash
# 获取数据并自主探索
./quant prepare --symbol 601985
./quant history --symbol 601985
./quant history --symbol 601985 --start 2025-10-01 --output research/private/601985/prices.csv
./quant history-sync --symbol 601985

# 显式策略评估与本地研究基线
./quant strategies --symbol 601985
./quant analyze --symbols 601985,510720 --cycle daily --cycle moving_average
./quant base-report --symbol 601985

# 查看模型与登记状态
./quant models
./quant reports --symbol 601985
```

`prepare` 不执行策略，不因未启用策略而失败；`analyze` 评估当前绑定的启用版本，
缺少启用版本或参数漂移会明确失败。`--all` 只包含启用标的，显式指定代码可以
研究停用标的。批量命令保留部分成功；存在任一失败时返回非零。
`history --output` 不覆盖已有 CSV；前复权价格不能直接当作真实成交价回放。

Agent 可直接使用 Python、SQL、联网研究和临时实验，无需先注册每个假设。
形成可复用规则后再固化策略版本与模型：`backtest --study` 读取已登记的冻结
实验规格，`backtest --strategy-record` 读取策略版本；`select --universe` 读取
新建的候选池。使用前先保存相应规格与来源，不附带旧投资方案作为默认值。
回测结果保存 JSON，由 Agent 解释、撰写飞书报告。

## 归档与清理

飞书是正式报告的唯一阅读入口。本地 `research/scratch/` 放临时探索并忽略提交；
决定保留后，仅归档一份定稿、必要证据和回读凭据。先查询 `research/documents.json`
与远端节点，复用标的主页；发布后回读核验，再登记 `published` 和链接。
具体字段、流程和失败处理见 [research/README.md](research/README.md)。

旧报告、策略草案、迁移稿与过程文件已清理，历史数据及计算模型继续保留。
后续目录按需创建，不积累空模板或待迁移材料。
旧电脑的后台服务需执行 `sh scripts/stop_legacy_services.sh`，详见
[install.md](install.md)。不要用旧运行副本覆盖当前数据库。

工程说明：[约定](AGENTS.md) · [架构](docs/architecture.md) ·
[能力边界](capabilities.md) · [数据契约](data/README.md)。

```bash
./scripts/check.sh
./quant doctor
```

通过检查和敏感信息审计后提交推送 `origin/main`。当前私有仓库同步研究资产，
配置、凭证、日志及 SQLite 事务边车文件不提交；数据库保持单设备写入。
