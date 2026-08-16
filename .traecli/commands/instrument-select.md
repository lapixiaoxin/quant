---
description: 发现并比较一组同类标的，生成可审计的 HTML 选择报告。
argument-hint: "[候选池 ID 或投资目标]"
---

使用项目中的 `instrument-selector` Skill 执行标的选择。

如果 `research/universes/${1}.toml` 已存在，先运行：

```bash
./quant select --universe research/universes/${1}.toml
```

读取：

```text
data/selections/latest/${1}.json
```

补齐费用、规模、跟踪误差、指数规则、成分暴露和来源时间后复跑程序筛选，
并将唯一的 HTML 选择报告保存到：

```text
research/selections/${1}/YYYY-MM-DD-selection.html
```

保存前核对数据包状态：`needs_research` 只能列为临时深研顺序，不得写成
“首选”“备选”或最终短名单。
同时核对动态事实使用原始生效日期，而不是网页查询日期，并确认关键来源在
HTML 中可点击。
完成后运行 `./quant site`，确认根路径研究工作台已出现最新报告入口。

如果 `${1}` 不是现有候选池 ID，则先按自然语言目标发现候选并创建 TOML。
只形成研究短名单，不执行交易，不输出具体买入金额。
