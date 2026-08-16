---
description: 按标准分析请求动态注入周期、因子和生效策略，生成报告。
argument-hint: "[标的代码] [分析请求 JSON] [push]"
tools: Read,Write,Bash,WebSearch
---

先运行：

```bash
./quant prepare --symbol ${1} --analysis-request ${2}
```

读取 `data/latest/${1}.json` 和 `.prompt.txt`。数据包必须是 schema v4，
并同时消费 `strategy_plan`、`analysis_plan` 和 `research_plan`。

使用 `research_plan.skill` 指定的 Skill 生成围绕当前生效策略的报告，
Markdown 推送源保存为：

```text
data/reports/YYYY-MM-DD/${1}-research.md
```

当 `${3}` 为 `push` 时，运行：

```bash
./quant send-report <报告路径> --symbol ${1} --event agent_report
```

最后运行 `./quant site`，确认同名 HTML 报告进入网页报告目录。
