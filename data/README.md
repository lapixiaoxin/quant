# 运行数据目录

本目录只保存可再生成或需要审计的运行产物，不是配置源。

```text
latest/                 每个标的最新的 schema v3 数据包、代理提示和基础报告
snapshots/YYYY-MM-DD/   每次采集的带时间戳快照
reports/YYYY-MM-DD/     基础报告和研究代理报告
dashboard/              从 latest 数据包生成的静态看板
history/market.sqlite3  标准化日线历史库，供长期查询和未来回测使用
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

不要手工修改 `latest/*.json`。运行数据默认不提交到 Git。

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
