# 运行数据目录

本目录只保存可再生成或需要审计的运行产物，不是配置源。
面向人的统一入口位于项目根目录 `index.html`；工作台只收录可阅读报告，
不会把本目录中的原始 JSON 快照或 SQLite 直接当作导航页面。

```text
latest/                 每个标的最新的 schema v4 数据包、代理提示和基础报告
snapshots/YYYY-MM-DD/   每次采集的带时间戳快照
reports/YYYY-MM-DD/     标的报告 Markdown 推送源和同名 HTML 网页
dashboard/              从 latest 数据包生成的静态看板
history/market.sqlite3  标准化日线与指数估值历史库，供查询和回测使用
control/research.sqlite3 选择、分析、回测、报告和发布状态索引
analysis/latest/        标准分析请求
analysis/snapshots/     按日期保存的分析请求快照
backtests/<代码>/       冻结回测 JSON 和 HTML 验证报告
selections/latest/      每个候选池最新的程序筛选 JSON
selections/snapshots/   带时间戳的程序筛选快照
```

## schema v4

最新数据包包含：

- `instrument`：标的身份和最终解析后的画像引用。
- `strategy_plan`：当前启用策略版本、生命周期、指纹和回测绑定。
- `analysis_plan`：请求 ID、触发入口、周期、因子、模式和发送要求。
- `metrics`：与策略无关的确定性指标。
- `assessments`：各策略画像独立给出的基线判断。
- `research_plan`：TRAE 应执行的章节、关注点、来源与个性指令。
- `notification_plan`：不含凭证的事件与通道路由摘要。
- `data_quality`：来源、交易日、时间戳和限制。

若要改变策略、研究内容或通知行为，请修改 `config/config.toml`，然后重新运行：

```bash
./quant prepare --symbol <标的代码>
```

不要手工修改 `latest/*.json`。当前远端仓库是私有仓库，日线数据库、快照、
报告和看板会进入 Git，便于跨设备复用和审计；SQLite 的 `-wal`、`-shm`
和 `-journal` 临时文件仍被忽略。

提交前必须确认数据包不含凭证、真实通知接收 ID 或不准备跨设备同步的个人信息。
若未来仓库改为公开，必须先从 Git 历史中清理个人研究数据，而不只是修改
`.gitignore`。

标的报告 Markdown 只用于通知和审计。运行 `./quant site` 后生成同名 HTML，
工作台和报告中心只链接 HTML；HTML 页面保留图表扩展区，不要把工程说明混入
标的报告目录。

LaunchAgent 写入的是 `~/.local/share/quant-monitor` 运行副本。由主写设备执行
`./scripts/sync_runtime_data.sh`，脚本会暂停服务、使用 SQLite 在线备份生成一致
主库并复制研究产物，再恢复原先已加载的服务。SQLite 二进制文件不支持 Git
自动合并，同一时刻只能有一台设备负责写入和导出；交接步骤见 `install.md`。

## 历史数据职责

`history/market.sqlite3` 使用 Python 标准库 SQLite，不需要单独部署数据库服务。
每次 `prepare` 或 `daily` 采集成功后，程序会按标的代码和交易日幂等写入日线：

- OHLC、成交量、成交额、振幅、涨跌幅和换手率。
- 前复权口径 `qfq`。
- 最近一次数据来源和采集时间。
- 每次同步的来源、日期范围和条数。
- 指数股息率、日期对应历史分位、20/50/80 分位线及估值来源。

当降级行情源缺少成交额或换手率时，更新不会用零值覆盖历史库中已有的非零值。
正常更新只请求最多 40 根重叠日线；首次、条数不足或明显陈旧时请求完整窗口。
增量响应中补回的近期历史日期记录在
`data_quality.repaired_history_dates`。JSON 快照继续保留一次任务的审计上下文；
SQLite 负责跨日期查询和回测输入，两者不能相互替代。

查看覆盖范围：

```bash
./quant history --all
```

按策略记录同步指数估值：

```bash
./quant valuation-sync \
  --strategy-record dividend-yield-dynamic-v1
```

当前历史数据库 schema v2 新增 `valuation_observations`。估值表按指数代码、
事实日期、指标、加权口径和历史窗口幂等保存；网络同步失败时可以通过 `--input`
导入已下载的同源 `window.pageData` 脚本。

## 候选筛选数据

候选池配置位于 `research/universes/`。执行：

```bash
./quant select --universe research/universes/<候选池 ID>.toml
```

会生成独立的 `selection_schema_version = 2` 数据包，候选池额外记录投资期限、
主题和创建日期。候选状态包括：

- `eligible`：硬门槛和必需证据完整。
- `needs_research`：硬门槛未失败，但仍缺少费率、规模或跟踪质量等证据。
- `excluded`：已知事实明确违反硬门槛。
- `data_error`：单个候选采集或计算失败，保留错误而不拖垮整个候选池。

`market_score` 只比较流动性、近期波动和一年最大回撤，不代表最终适配性、
收益预测或买入顺序。

程序筛选不再生成独立 HTML。Agent 读取该 JSON 后，在
`research/selections/<候选池 ID>/<日期>-selection.html` 补齐深度比较；
这份选择报告同时承载硬门槛、证据缺口和最终短名单，是唯一用户可见入口。

## 控制面与回测

`control/research.sqlite3` 只保存运行索引，不保存报告正文。当前表包括：

- `selection_runs`：候选池、期限、主题、候选数和短名单数。
- `analysis_runs`：触发入口、标的范围、周期、因子、模式和完成状态。
- `backtest_runs`：策略版本、结果路径、收益、回撤和交易次数。
- `report_records`：标的、策略版本、周期、因子、渠道和发布状态。

回测使用现有历史库，不会额外联网。报告生成和渠道发送分别记账；发送失败时，
报告文件仍保留并在控制面显示 `partial` 或 `failed`。

历史库已保存 000151 最近三年的逐日市值加权股息率和来源提供的时点分位，
可供 `dividend_yield_dynamic` 做有限基线回测。当前仍不保存逐日可见的盈利、
现金流和分红削减快照，基本面门禁只能使用指数编制规则代理；缺少同日估值时
必须明确失败，不得用价格回撤替代。
