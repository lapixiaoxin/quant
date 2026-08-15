"""候选池确定性初筛 HTML 报告。"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

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
  <title>{_text(universe["name"])}候选初筛</title>
  <link rel="stylesheet" href="../../../docs/assets/docs.css?v=0.7.0">
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="../../../index.html">Quant Monitor</a>
      <nav class="site-nav" aria-label="全局导航">
        <a href="../../../index.html">工作台</a>
        <details class="nav-dropdown">
          <summary>使用指南</summary>
          <div class="nav-menu">
            <a href="../../../docs/index.html">
              <strong>文档总览</strong><small>能力、入口与阅读路径</small>
            </a>
            <a href="../../../docs/install.html">
              <strong>安装部署</strong><small>新设备、凭证与常驻服务</small>
            </a>
            <a href="../../../docs/operations.html">
              <strong>运行运维</strong><small>命令、日志与故障处理</small>
            </a>
          </div>
        </details>
        <details class="nav-dropdown">
          <summary>系统设计</summary>
          <div class="nav-menu">
            <a href="../../../docs/capabilities.html">
              <strong>能力边界</strong><small>已支持、条件支持与明确限制</small>
            </a>
            <a href="../../../docs/architecture.html">
              <strong>架构设计</strong><small>模块、数据流与扩展契约</small>
            </a>
            <a href="../../../docs/refactor-report.html">
              <strong>升级报告</strong><small>工程演进过程与验证证据</small>
            </a>
          </div>
        </details>
        <details class="nav-dropdown align-right is-current">
          <summary aria-current="true">研究中心</summary>
          <div class="nav-menu">
            <a href="../../../research/index.html">
              <strong>研究总览</strong><small>研究资产与隐私分层入口</small>
            </a>
            <a href="../../../research/selections/index.html"
              aria-current="location">
              <strong>候选筛选</strong><small>发现同类标的并形成短名单</small>
            </a>
            <a href="../../../research/instruments/index.html">
              <strong>标的档案</strong><small>按代码沉淀讨论与判断</small>
            </a>
            <a href="../../../research/library/index.html">
              <strong>通用经验</strong><small>复核并脱敏的跨标的方法</small>
            </a>
            <a href="../../../research/methods/storage-backtesting.html">
              <strong>数据与回测</strong><small>历史存储与验证纪律</small>
            </a>
            <a href="../../../research/templates/discussion-report.html">
              <strong>讨论模板</strong><small>统一事实、结论与失效条件</small>
            </a>
          </div>
        </details>
        <a href="../../../data/dashboard/index.html">投资看板</a>
      </nav>
    </div>
  </header>
  <main class="page">
    <section class="hero">
      <div>
        <p class="eyebrow">Candidate Screening</p>
        <h1>{_text(universe["name"])}候选初筛</h1>
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
      <span>候选初筛是研究材料，不构成投资建议或自动交易指令。</span>
      <span>{_text(universe["id"])}</span>
    </div>
  </footer>
  <script src="../../../docs/assets/navigation.js?v=0.7.0"></script>
</body>
</html>
"""


def write_selection_report(path: Path, packet: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_selection_report(packet), encoding="utf-8")
    return path
