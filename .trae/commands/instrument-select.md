---
description: 发现并比较一组同类标的，生成可审计的 HTML 选择报告。
argument-hint: "[候选池 ID 或投资目标]"
---

使用 `instrument-selector` Skill 执行标的选择。

若参数对应 `research/universes/<参数>.toml`：

1. 读取候选池和已有来源。
2. 运行：

```bash
./quant select --universe research/universes/<参数>.toml
```

3. 读取 `data/selections/latest/<参数>.json` 和 `.html`。
4. 按 Skill 要求补齐低频事实、复跑初筛并生成最终 HTML 报告。
5. 报告完成前核对候选状态；`needs_research` 不得写成最终短名单或首选。
6. 核对事实日期未被报告生成日期覆盖，并确认关键来源在 HTML 中可点击。

若参数是自然语言投资目标且不存在候选池：

1. 先定义暴露、市场、期限和风险约束。
2. 从交易所、指数机构和基金管理人发现候选。
3. 创建版本化候选池 TOML，不猜测缺失数值。
4. 再执行本地初筛和深度比较。

最终报告保存到：

```text
research/selections/<候选池 ID>/YYYY-MM-DD-selection.html
```

本命令只形成研究短名单，不执行交易，不输出具体买入金额。
