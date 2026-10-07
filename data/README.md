# 数据契约

人的研究报告位于 `AGENTS.md` 指定的飞书 Wiki。本目录保存程序输入输出、
审计证据和草稿，不提供网页导航。

| 路径 | 职责 |
|---|---|
| latest/ | 每标的最新数据包、提示和基础草稿，可覆盖 |
| snapshots/日期/ | 时间和唯一 ID 命名的行情/指标快照 |
| history/market.sqlite3 | 日线、估值、来源与同步记录，schema v2 |
| control/research.sqlite3 | 分析、筛选、回测、基础草稿索引，schema v1 |
| analysis/latest/、analysis/snapshots/ | 显式分析请求及冻结副本 |
| backtests/代码/ | 追加的实验 JSON、权益、参数、限制与账本 |
| selections/latest/、selections/snapshots/ | 候选指标、硬门槛和证据缺口 |
| reports/日期/ | 独立命名的基础 Markdown 草稿 |

## 研究数据包 v5

`as_of` 为带时区采集时间；市场数据时点另见 quote、metrics 和 data_quality。

- `instrument`：身份与解析后的可选策略、研究画像。
- `strategy_plan` / `assessments`：仅显式评估策略时填充，数据探索时为空数组。
- `analysis_plan`：请求、周期与因子；新请求 mode 为 `research`，无发送要求。
- `quote` / `metrics`：原始报价和程序计算结果。
- `research_plan`：可选参考关注点，不指定 Skill 或来源数量上限。
- `portfolio`：本机可选的个人语境，发布时需按具体授权处理。
- `data_quality`：行情来源、时间、样本量、增量模式、缺口修复、
  `strategy_evaluated` 与局限。

v5 移除 `notification_plan`、标的通知引用和请求发送字段。
基础报告兼容读取 v4/v3；旧分析请求可读取，但旧自动化模式不能执行。
不要手改最新 JSON 来修改规则，改配置/策略版本后重新采集。

## 历史仓储

SQLite 日线按标的与交易日去重，保留前复权 OHLC、成交量、成交额（元）、
百分比字段、数据来源和采集时间。旧模型里的日线百分比字段沿用来源百分数口径；
quote 和计算指标里的收益比例使用小数，调用时检查字段定义。
降级源缺失成交额、换手等信息时，不用零覆盖已有有效值。

正常采集使用最多 40 根重叠窗口，首次、样本不足、陈旧超过 12 天或未覆盖
`history_start_date` 时回补。若来源范围不足，显式报告历史不完整。
`history --output` 导出当前主库，不能用该前复权导出冒充不复权现金撮合数据。

估值表保存指数代码、事实日期、指标、加权口径、历史窗口、来源及其可得时点。
股息率回测必须使用真实的当时可得历史，缺失时拒绝，不使用价格代理。

## 实验与候选

普通回测规格固定模型版本、参数指纹、日期、成本与基准。
现金研究规格 v1/v2 另固定不复权 CSV 的 SHA256、分红来源和分段：

- v1：训练选候选、验证选择、留出和全期诊断，保留全部候选与比较账本。
- v2：组件和资金方案独立分账，前日持仓决定后续开仓资格，不透支保留现金。
  任一子账户日期、现金守恒或末日清算失败时整项失败。

每次 `backtest --study` 追加 JSON，保留原始规格与代码哈希。
`trade_count` 是成交笔数，`completed_rounds` 是完整平仓轮次；
`fees_yuan` 包含佣金、过户和卖出税费，滑点反映在成交价；
`net_dividends_yuan` 是税后现金股息。未清算份额、成本压力、平均仓位必须披露。
v2 全期按含首末日的日历天数年化，短期分段不年化；假设冲击不代表历史最大损失。

候选数据保持 `selection_schema_version=2`：`eligible`、`needs_research`、
`excluded`、`data_error` 分开。硬门槛通过且必要证据完整才能成为研究短名单。
市场分数仅比较流动性、波动和回撤，不代表适配性、收益预测或买入顺序。

## 审计与兼容

旧运行索引和原有证据不迁移、不删除。历史 HTML 路径继续存在作迁移依据；
新实验索引直接指向 JSON，新基础报告状态为 `draft`。
飞书链接、文档状态及来源哈希由 `research/documents.json` 维护。

当前私有 Git 允许同步主库与研究资产。提交前核验敏感信息、文件体积和数据库
完整性；同一时间只允许一台主写设备，交接参考 `install.md`。
不得提交 SQLite 事务边车、配置、日志或凭证。
