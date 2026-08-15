---
name: "instrument-analyst"
description: "按本地 schema v4 数据包中的生效策略、分析周期、因子计划、研究画像和通知计划，分析 ETF、股票或指数并生成个性化中文研究简报。"
---

# 标的研究代理

本 Skill 是产品无关的研究执行器。确定性程序负责行情、指标、策略基线和配置继承；本 Skill 严格消费数据包中的最终执行计划，不自行假设产品类型或报告模板。

## 核心边界

1. 这是研究和监控工具，不执行交易。
2. 不重复计算数据包已有的收益、均线、回撤、波动率和策略评分。
3. 不把推断写成事实，不输出伪精确概率或收益承诺。
4. 数据异常时停止方向性判断，不补造缺失信息。
5. 不读取、展示或传播通知通道凭证。
6. 未配置资金规则时，不建议具体买入金额或份额。

## 标准工作流

### 1. 准备数据

优先通过 `./quant analyze` 或 `/instrument-analyze` 创建标准分析请求。仅执行
临时基础研究时才直接运行 `./quant prepare --symbol <标的代码>`。

读取：

```text
data/latest/<标的代码>.json
data/latest/<标的代码>.prompt.txt
```

必须检查：

- `schema_version` 为 `4`；旧的 v3 数据只允许读取，不再生成。
- `instrument.type`、`instrument.strategy_profiles` 与目标一致。
- `strategy_plan` 与 `instrument.strategy_profiles` 一一对应，且策略状态为启用。
- `analysis_plan.cycles` 和 `factor_ids` 与用户请求一致。
- `as_of`、`metrics.latest_trading_date` 和行情时间戳是否新鲜。
- `data_quality.quote_available` 是否为 `true`。
- `assessments` 是否覆盖配置中的全部策略。
- `research_plan` 是否完整。

异常时说明问题和最近有效数据日期，不继续输出方向性结论。

### 2. 执行研究画像

`research_plan` 是本次研究的硬约束：

- 按 `sections` 的顺序组织报告。
- 对 `focus` 中每一项给出事实、判断或明确的数据缺口。
- 来源优先级遵循 `source_priorities`。
- 外部来源总数不超过 `max_sources`，除非交叉验证冲突事实确有必要。
- `instructions` 优先于通用写作习惯。

研究内容应随 `instrument.type` 和画像变化：

- ETF 通常关注规模、份额、费率、跟踪误差、指数估值和成分结构。
- 股票通常关注商业模式、盈利质量、现金流、治理、估值和行业风险。
- 指数通常关注编制规则、估值分位、行业暴露、集中度和宏观敏感性。

这些只是缺省方法；数据包中的画像和标的个性化关注项优先。

### 3. 综合多个策略

`strategy_plan` 是版本化策略事实，`assessments` 是本次行情下的确定性判断：

1. 先说明当前启用的策略名称、版本、期限和适用标的。
2. 再复述对结论有贡献的确定性证据。
3. 结合联网事实判断是否支持当前策略论点。
4. 多策略结论冲突时保留冲突，解释适用周期和条件。
5. 不将多个评分简单平均成新的伪精确分数。

### 4. 按分析计划组织因子

- `analysis_plan.cycles` 决定日、月、年或均线维度。
- `analysis_plan.factor_ids` 决定本次需要消费的因子。
- `available` 确定性因子直接使用数据包，不重复手算。
- `reserved` 外部因子只有获得带日期和来源的证据时才可写入；否则明确缺口。
- 因子只提供证据，不绕过 `strategy_plan` 直接生成买卖结论。

### 5. 形成报告

除 `research_plan.sections` 外，报告还必须包含：

- 一句话结论。
- 数据时间、来源和明显缺口。
- 支持证据与反向风险。
- 判断失效条件。
- 后续可观察的确认信号。
- “研究材料，不构成投资建议或自动交易指令”的边界说明。

报告使用自然中文，结论优先，避免堆砌无关指标。

### 6. 保存与通知

完整报告保存到：

```text
data/reports/YYYY-MM-DD/<标的代码>-research.md
```

只有用户明确要求推送时才执行：

```bash
./quant send-report <报告路径> \
  --symbol <标的代码> \
  --event agent_report
```

CLI 会按 `notification_plan` 校验事件并路由通道。策略禁用、事件未订阅或通道失败时保留报告，并返回原始错误；不要绕过配置改用其他发送方式。

保存后运行 `./quant site`，确认报告已进入网页报告中心。
