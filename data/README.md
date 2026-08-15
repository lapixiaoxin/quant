# 运行数据目录

本目录只保存可再生成或需要审计的运行产物，不是配置源。

```text
latest/                 每个标的最新的 schema v3 数据包、代理提示和基础报告
snapshots/YYYY-MM-DD/   每次采集的带时间戳快照
reports/YYYY-MM-DD/     基础报告和研究代理报告
dashboard/              从 latest 数据包生成的静态看板
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
