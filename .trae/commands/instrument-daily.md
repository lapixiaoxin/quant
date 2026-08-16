---
description: 按标的配置生成研究简报，并按通知策略决定是否推送。
argument-hint: "[标的代码] [push]"
---

必须提供标的代码参数。运行 `./quant prepare --symbol ${1}`，然后读取：

```text
data/latest/${1}.json
data/latest/${1}.prompt.txt
```

数据包中的 `research_plan.skill` 决定使用哪个研究 Skill；
`sections`、`focus`、`source_priorities` 和 `instructions` 是本次报告的硬约束。
完整报告的 Markdown 推送源保存到
`data/reports/YYYY-MM-DD/${1}-research.md`。
保存后运行 `./quant site`，生成同名 HTML 并让其进入根路径工作台。

仅当第二个参数为 `push` 时，按数据包中的 `notification_plan` 执行：

```bash
./quant send-report <报告路径> \
  --symbol ${1} \
  --event agent_report
```
