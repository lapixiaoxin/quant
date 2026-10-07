# 研究资产与飞书归档

根目录：https://icnxcxzl7hll.feishu.cn/wiki/Nr1Aw5d6Li5cnjkyAuAcZ4x8nag

每标的一篇 `代码 名称` 主页，研究、策略与回测文档分别为该主页的子节点。
跨标的比较、通用方法直接挂根节点。Agent 先查本地索引与远端子节点，
复用现有主页，不重复创建。新报告不维护本地 HTML。

## 研究步骤

1. 自主确定问题、来源和方法；检查行情时点、复权、单位与数据质量。
2. 保存本地 Markdown 草稿和所用证据，关联策略版本、模型和实验。
3. 在飞书创建对应子文档，上传必要图表并维护可读表格、来源链接和限制。
4. 回读节点、父节点、标题与正文，核对关键数值、图片和来源；保存回读凭据。
5. 使用 `./quant report-register <元数据.json>` 登记状态与链接。
   查看用 `./quant reports [--symbol 代码]`。

Agent 可以自由组织报告，但事实、假设、预测、反例、数据时间与失效条件必须可辨。
策略和回测文档应包含版本、费用、时点、平均仓位、风险指标、失败结果与验证局限。
实战交易由人完成，复盘记录预期和实际差异。

## 本地目录

`strategies/` 保存版本目录、冻结规格与方法；`universes/` 保存候选和证据；
`private/` 保存具体标的草稿及回读凭据；`library/` 保存脱敏通用经验。
`migration/` 为旧报告迁移稿。`documents.json` 是文档版本和飞书映射索引。

本地草稿是已发布版本的审计副本。后续更新先创建新的草稿路径与 document_id，
关联新证据；可以新建飞书版本文档，或更新原远端文档后记录新的回读凭据。
不要在原索引中覆盖已发布版本或修改已冻结来源。发布状态表明该版本曾被回读
核验，不证明远端文档此后从未被人工编辑。

## 元数据协议

例如保存 `research/private/601985/research-v1-metadata.json`：

```json
{
  "document_id": "601985-research-v1",
  "symbol": "601985",
  "kind": "research",
  "title": "中国核电研究 v1",
  "parent_id": "instrument-601985",
  "local_path": "research/private/601985/research-v1.md",
  "source_paths": ["data/analysis/snapshots/2026-10-04/601985-weekly-study/prices.csv"],
  "data_as_of": "2026-09-30",
  "generated_at": "2026-10-07T12:00:00+08:00",
  "status": "pending",
  "strategy_record_ids": [],
  "model": "",
  "experiment": ""
}
```

- kind：`instrument/research/strategy/backtest/selection/method`。
- 标的主页 kind 为 `instrument`、parent_id 为 `root`；具体标的其他文档必须
  引用已登记的对应主页。跨标的文档 symbol 为空、parent_id 为 `root`。
- source_paths 填不可变证据路径，不引用会覆盖的 latest；model 填 `ID@版本`，
  experiment 填冻结规格或结果路径，无关联时明确留空。
- 文件必须位于工作区 research/data 内；登记器计算正文和来源 SHA256。
- pending 不能填写 wiki_url。首次建稿即应登记，失败时保留 pending。

发布成功后保持原元数据，status 改为 `published`，补充 `wiki_url` 与
`verification_path`，后者指向如下结构的回读凭据 JSON：

```json
{
  "wiki_url": "https://icnxcxzl7hll.feishu.cn/wiki/真实子节点Token",
  "remote_document_id": "真实DocxToken",
  "parent_node_token": "真实父Wiki节点Token",
  "local_sha256": "本地正文SHA256",
  "verified_at": "2026-10-07T12:30:00+08:00",
  "remote_content": "飞书实际回读的正文或完整响应"
}
```

先核验并登记主页，再登记子文档。登记器检查链接、来源指纹、父节点与凭据字段；
远端内容的真实性、格式和数值一致性必须由 Agent 实际回读确认。
不允许生成虚构凭据以绕过发布失败。

## 迁移与隐私

`migration/` 已准备的旧研究草稿全部为 pending，具体状态以索引为准。
原 HTML、图表和历史索引路径保留为证据，迁移不改历史结论或重新标为当前建议。
草稿转换不保证复杂布局完整；发布时核对原文中的表格、图表和全部关键数值。
全部对应内容在飞书核验后，才评估清理历史本地展示文件。

私人持仓、成本和计划不进入通用 library。当前私有仓库允许同步 private，
仍禁止密码、Token、App Secret、钥匙串内容和完整身份凭据。飞书文档继承的
可见范围需适合其内容；不扩大分享范围。公开仓库前先清理历史个人数据。
