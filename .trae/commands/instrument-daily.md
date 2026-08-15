---
description: 按标的配置生成研究简报，并按通知策略决定是否推送。
argument-hint: "[标的代码] [push]"
---

运行 `./quant prepare --symbol ${1:-515100}`，然后读取：

```text
data/latest/${1:-515100}.json
data/latest/${1:-515100}.prompt.txt
```

数据包中的 `research_plan.skill` 决定使用哪个研究 Skill；
`sections`、`focus`、`source_priorities` 和 `instructions` 是本次报告的硬约束。
完整报告保存到 `data/reports/YYYY-MM-DD/${1:-515100}-research.md`。

仅当第二个参数为 `push` 时，按数据包中的 `notification_plan` 执行：

```bash
./quant send-report <报告路径> \
  --symbol ${1:-515100} \
  --event agent_report
```
