# 运行数据目录

本目录只保存可再生成或需要审计的运行产物，不是配置源。
面向人的统一入口位于项目根目录 `index.html`；工作台只收录可阅读报告，
不会把本目录中的原始 JSON 快照或 SQLite 直接当作导航页面。

```text
latest/                 每个标的最新的 schema v3 数据包、代理提示和基础报告
snapshots/YYYY-MM-DD/   每次采集的带时间戳快照
reports/YYYY-MM-DD/     基础报告和研究代理报告
dashboard/              从 latest 数据包生成的静态看板
history/market.sqlite3  标准化日线历史库，供长期查询和未来回测使用
selections/latest/      每个候选池最新的初筛 JSON 和基础 HTML 报告
selections/snapshots/   带时间戳的候选池初筛快照
```

## schema v3

最新数据包包含：

- `instrument`：标的身份和最终解析后的画像引用。
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

当降级行情源缺少成交额或换手率时，更新不会用零值覆盖历史库中已有的非零值。
JSON 快照继续保留一次任务的审计上下文；SQLite 负责跨日期查询和未来回测输入，
两者不能相互替代。

查看覆盖范围：

```bash
./quant history --all
```

## 候选筛选数据

候选池配置位于 `research/universes/`。执行：

```bash
./quant select --universe research/universes/<候选池 ID>.toml
```

会生成独立的 `selection_schema_version = 1` 数据包。候选状态包括：

- `eligible`：硬门槛和必需证据完整。
- `needs_research`：硬门槛未失败，但仍缺少费率、规模或跟踪质量等证据。
- `excluded`：已知事实明确违反硬门槛。
- `data_error`：单个候选采集或计算失败，保留错误而不拖垮整个候选池。

`market_score` 只比较流动性、近期波动和一年最大回撤，不代表最终适配性、
收益预测或买入顺序。
