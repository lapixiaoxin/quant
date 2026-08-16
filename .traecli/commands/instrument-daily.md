---
description: 按标的配置生成研究简报，并按通知策略决定是否推送。
argument-hint: "[标的代码] [push]"
tools: Read,Write,Bash,WebSearch
---

运行 `./quant prepare --symbol ${1:-515100}`，读取
`data/latest/${1:-515100}.json` 和对应的 `.prompt.txt`。

根据数据包中的 `research_plan.skill` 使用研究 Skill；严格执行其中的章节、关注点、来源顺序和个性指令。Markdown 推送源保存为
`data/reports/YYYY-MM-DD/${1:-515100}-research.md`。
保存后运行 `./quant site`，生成同名 HTML 并让其进入根路径工作台。

当 `$2` 为 `push` 时运行：

```bash
./quant send-report <报告路径> \
  --symbol ${1:-515100} \
  --event agent_report
```

否则只保存并展示报告，不发送。
