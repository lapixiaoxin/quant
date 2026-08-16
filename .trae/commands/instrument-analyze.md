---
description: 按标准分析请求动态注入周期、因子和生效策略，生成报告。
argument-hint: "[标的代码] [data/analysis/latest/<请求>.json] [push]"
---

读取第二个参数指定的分析请求，并确认其中包含第一个参数标的。

运行：

```bash
./quant prepare --symbol ${1} --analysis-request ${2}
```

随后读取：

```text
data/latest/${1}.json
data/latest/${1}.prompt.txt
```

数据包必须是 schema v4，并包含：

- `strategy_plan`：当前生效策略版本和参数指纹。
- `analysis_plan`：本次触发入口、周期和因子。
- `research_plan`：研究章节、来源和个性指令。

使用 `research_plan.skill` 指定的 Skill，围绕当前策略生成报告，禁止把一般行情
摘要代替策略分析。Markdown 推送源保存为：

```text
data/reports/YYYY-MM-DD/${1}-research.md
```

若第三个参数是 `push`，按 `notification_plan` 发送。最后运行
`./quant site`，确认同名 HTML 报告进入网页报告目录。
