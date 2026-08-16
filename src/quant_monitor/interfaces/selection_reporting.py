"""候选选择作业的可选机器筛选明细。"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from .site_navigation import ASSET_VERSION, build_site_header

STATUS_LABELS = {
    "eligible": "通过初筛",
    "needs_research": "待补证据",
    "excluded": "未过硬门槛",
    "data_error": "数据失败",
}
AMOUNT_SOURCE_LABELS = {
    "market_history": "行情计算",
    "verified_metadata": "元数据核验",
}


def _text(value: object) -> str:
    return escape("" if value is None else str(value))


def _number(value: object, digits: int = 2) -> str:
    if value is None:
        return "待补"
    return f"{float(value):,.{digits}f}"


def _percent(value: object) -> str:
    if value is None:
        return "待补"
    return f"{float(value) * 100:.2f}%"


def _fee_percent(value: object) -> str:
    if value is None:
        return "待补"
    return f"{float(value):.4f}%"


def _candidate_row(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata", {})
    metrics = candidate.get("metrics", {})
    reasons = [
        *candidate.get("exclusions", []),
        *[f"缺少 {item}" for item in candidate.get("evidence_gaps", [])],
    ]
    reason_text = "；".join(reasons) or "硬门槛和必需证据均完整"
    score = candidate.get("market_score")
    rank = candidate.get("market_rank")
    market_rank = f"{rank} / {_number(score)}" if rank and score is not None else "-"
    return f"""
      <tr>
        <td><strong>{_text(candidate.get("symbol"))}</strong><br>
          <small>{_text(candidate.get("name"))}</small></td>
        <td>{_text(STATUS_LABELS.get(candidate.get("status"), "未知"))}</td>
        <td>{_text(metadata.get("tracking_index") or "待核验")}</td>
        <td>{_text(metadata.get("as_of") or "待补")}</td>
        <td>{_fee_percent(metadata.get("total_fee_pct"))}</td>
        <td>{_number(metadata.get("fund_size_cny"), 0)}</td>
        <td>{_number(metrics.get("average_amount_20d"), 0)}<br>
          <small>{_text(AMOUNT_SOURCE_LABELS.get(
              metrics.get("average_amount_20d_source"),
              "来源待补",
          ))}</small></td>
        <td>{_fee_percent(metadata.get("tracking_error_pct"))}</td>
        <td>{_percent(metrics.get("annualized_volatility_20d"))}</td>
        <td>{_percent(metrics.get("max_drawdown_242d"))}</td>
        <td>{_text(market_rank)}</td>
        <td>{_text(reason_text)}</td>
      </tr>
    """.strip() + "\n"


def build_selection_report(packet: dict[str, Any]) -> str:
    universe = packet["universe"]
    summary = packet["summary"]
    rows = "".join(_candidate_row(item) for item in packet["candidates"])
    limitations = "".join(
        f"<li>{_text(item)}</li>"
        for item in packet.get("data_quality", {}).get("limitations", [])
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_text(universe["name"])}机器筛选明细</title>
  <link rel="stylesheet"
    href="../../../docs/assets/docs.css?v={ASSET_VERSION}">
</head>
<body>
{build_site_header("../../../", "selection")}
  <main class="page">
    <section class="hero">
      <div>
        <p class="eyebrow">Candidate Screening</p>
        <h1>{_text(universe["name"])}机器筛选明细</h1>
        <p class="hero-copy">{_text(universe["objective"])}</p>
      </div>
      <aside class="hero-meta">
        <dl>
          <div><dt>数据时间</dt><dd>{_text(packet["as_of"])}</dd></div>
          <div><dt>候选数量</dt><dd>{summary["candidate_count"]}</dd></div>
          <div><dt>待补证据</dt><dd>{summary["needs_research"]}</dd></div>
        </dl>
      </aside>
    </section>
    <section class="section">
      <div class="section-head">
        <p class="section-label">初筛结果</p>
        <div>
          <h2>先过硬门槛，再做深度研究</h2>
          <p class="section-intro">{_text(summary["market_ranking_scope"])}</p>
        </div>
      </div>
      <div class="table-wrap">
        <table class="selection-table">
          <thead>
            <tr>
              <th>候选</th><th>状态</th><th>跟踪指数</th><th>元数据日期</th>
              <th>显性持续费率</th>
              <th>规模（元）</th><th>20日均额（元）</th><th>跟踪误差</th>
              <th>20日波动</th><th>一年回撤</th><th>市场排名 / 分</th>
              <th>理由与缺口</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <p class="section-label">限制</p>
        <div><h2>不能从这张表直接得出买入结论</h2></div>
      </div>
      <ul>{limitations}</ul>
      <div class="notice">
        下一步必须由 instrument-selector Skill 补齐费率、规模、跟踪误差、
        指数规则、成分暴露和来源时间，再形成短名单及淘汰理由。
      </div>
    </section>
  </main>
  <footer class="site-footer">
    <div class="footer-inner">
      <span>机器筛选明细不构成投资建议或自动交易指令。</span>
      <span>{_text(universe["id"])}</span>
    </div>
  </footer>
  <script
    src="../../../docs/assets/navigation.js?v={ASSET_VERSION}"></script>
</body>
</html>
"""


def write_selection_report(path: Path, packet: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_selection_report(packet), encoding="utf-8")
    return path
