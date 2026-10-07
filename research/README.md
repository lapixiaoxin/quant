# 研究资产与飞书归档

根目录：https://icnxcxzl7hll.feishu.cn/wiki/Nr1Aw5d6Li5cnjkyAuAcZ4x8nag

每标的一篇 `代码 名称` 主页，研究、策略与回测文档分别为该主页的子节点。
跨标的比较、通用方法直接挂根节点。Agent 先查本地索引与远端子节点，
复用现有主页，不重复创建；没有实际研究时不预建空文档。

## 保存什么

| 内容 | 保存位置与规则 |
|---|---|
| 给人阅读的正式报告 | 飞书；子文档建议命名为 `日期 主题 v版本`，正文自由组织 |
| 策略与实验 | 本地冻结规格、版本和完整结果；解释与结论写入飞书 |
| 原始数据与引用证据 | data/；保留来源、时间、单位、复权和哈希 |
| 报告审计副本 | private/代码/；每版本一份定稿及回读凭据 |
| 临时笔记、脚本、中间稿 | scratch/；Git 忽略，任务结束后清理 |
| 链接和版本状态 | documents.json；只登记实际保留的文档 |

目录按需创建。正式版不再另做 HTML、导航、移动版图表或迁移副本。
工程规则直接更新对应工程 Markdown，不另留重复计划和完成记录。

## 从探索到归档

1. 自主确定问题、来源和方法；检查行情时点、复权、单位与数据质量。
2. scratch/ 中完成探索。决定保留时，将证据、实验规格和 Markdown 定稿放入
   正式目录，关联策略版本与模型，用 `report-register` 登记为 `pending`。
3. 在飞书创建或更新对应文档，上传必要图表，维护可读表格、来源链接和限制。
4. 回读节点、父节点、标题与正文，核对关键数值、图片和来源，保存回读凭据，
   再使用 `./quant report-register <元数据.json>` 登记 `published`。
5. 删除临时脚本、中间稿和重复导出。提交定稿、必要证据、凭据及索引。
   查看用 `./quant reports [--symbol 代码]`。

Agent 可以自由组织报告，但事实、假设、预测、反例、数据时间与失效条件必须可辨。
策略和回测文档应包含版本、费用、时点、平均仓位、风险指标、失败结果与验证局限。
实战交易由人完成，复盘记录预期和实际差异。

本地定稿是已发布版本的审计副本，日常阅读只用飞书。后续更新创建新的定稿路径与
document_id，关联新证据；可以新建飞书版本文档，或更新原远端文档后记录新凭据。
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
  "source_paths": ["data/history/601985/prices.csv", "data/history/601985/manifest.json"],
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
- 文件必须位于工作区 research/data 内，不能引用 scratch 或可覆盖的 latest；
  登记器计算正文和来源 SHA256。
- pending 不能填写 wiki_url；仅定稿后登记。登录或发布失败时保留 pending，
  不伪造链接，不转为消息推送。metadata JSON 只是登记输入，可临时放 scratch。

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

## 清理与隐私

放弃的未发布研究可以整体删除；同时移除对应 pending 登记、运行记录与独占的
中间产物。先检查其他文档、策略和实验的引用，不能留下悬空路径，也不能删掉共享
数据。已发布文档和保留实验的证据继续保留，负面结果不能因表现差而单独删除。

2026-10-07 已按重新开始维护的要求清空旧研究与迁移待办；旧内容可从 Git 提交
`3202ef0` 查阅。当前不预设研究结论、启用策略或候选池，也不声称旧报告已发布。

私人持仓、成本和计划不进入通用 library。当前私有仓库允许同步 private，
仍禁止密码、Token、App Secret、钥匙串内容和完整身份凭据。飞书文档继承的
可见范围需适合其内容；不扩大分享范围。公开仓库前先清理历史个人数据。
