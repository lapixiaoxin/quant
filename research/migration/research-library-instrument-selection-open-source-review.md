> 迁移草稿，尚未发布。原文：`research/library/instrument-selection-open-source-review.html`。
> 原始 HTML 与图表保留供核验；历史结论与数据时间以正文为准。

Open-source Review

# 公开标的筛选 Skill 与工具评估

 评估现成 Skill 是否能直接承担 A 股同类 ETF 候选发现和选择。 结论是借鉴工作流与指标，不直接引入外部评分或交易建议。

评估日期2026-08-15

目标市场A 股 ETF

最终方案本地契约优先

候选方案

## 可借鉴，但不原样接入

| 方案 | 可借鉴能力 | 不直接采用原因 | 处理 |
| --- | --- | --- | --- |
| [DeepQ ETF Analysis](https://github.com/shenqingtech/skills/tree/master/skills/etf-analysis) | 规模、费率、估值、持仓、行情分层 | 依赖第三方 MCP 与 API Key，数据契约不由本项目控制 | 借鉴分析维度 |
| [Daisy Financial Research](https://github.com/agents365-ai/daisy-financial-research) | 先计划、研究记录、数值校验、来源报告 | 偏股票筛选，Tushare 与脚本体系较重 | 借鉴研究循环 |
| [Invest Agent v2](https://github.com/mirabilitum/invest) | 候选扫描、规则评分、状态跟踪 | 评分直接延伸到建仓建议，超出研究辅助边界 | 不采用交易部分 |
| [Awesome ETF Analysis](https://github.com/jeff3388/awesome-etf-analysis) | 暴露、流动性、费用、跟踪差异、指数方法的顺序 | 主要面向海外 ETF，阈值和税制不能直接迁移 | 借鉴 ETF 方法 |
| [ETF Screener](https://github.com/davidedele/ETF_Screener) | 程序计算收益、波动、回撤与成交量过滤 | 依赖 Yahoo 数据，候选发现和低频事实不足 | 借鉴确定性计算 |

落地决策

## 公开方法与本地证据契约组合

### 公开网络

发现与补证

发现候选，核验指数规则、费率、规模、跟踪误差和成分暴露。

### 本地程序

确定性

统一计算历史收益、波动、回撤、流动性、门槛和失败状态。

### 项目 Skill

研究判断

补齐来源事实，比较指数与产品差异，输出短名单和淘汰理由。

### 人工确认

最终控制

确认候选是否进入正式监控；系统不自动下单或决定仓位。

 第三方 Skill 的评分、阈值和推荐结论不作为本项目事实源。任何纳入的指标都必须 明确单位、时间、来源、缺失处理和失效条件。
