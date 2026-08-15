"""从最新数据包生成无需服务器的静态投资看板。"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from .reporting import assessments_view, instrument_view


def _text(value: Any) -> str:
    return html.escape(str(value))


def _pct(value: Any) -> str:
    return "暂无" if value is None else f"{float(value) * 100:+.2f}%"


def _price(value: Any) -> str:
    return "暂无" if value is None else f"{float(value):.4f}".rstrip("0").rstrip(".")


def _tone(value: Any) -> str:
    if value is None or float(value) == 0:
        return "flat"
    return "positive" if float(value) > 0 else "negative"


def _render_instrument(packet: dict[str, Any]) -> str:
    instrument = instrument_view(packet)
    assessments = assessments_view(packet)
    assessment = assessments[0]
    quote = packet.get("quote", {})
    metrics = packet.get("metrics", {})
    returns = metrics.get("returns", {})
    drawdowns = metrics.get("drawdowns", {})
    score = max(0, min(100, int(assessment.get("score", 0))))
    reason_items = "".join(
        f"<li><strong>{_text(item.get('name', item.get('id', '策略')))}：</strong>"
        f"{_text(reason)}</li>"
        for item in assessments
        for reason in item.get("reasons", [])
    )
    strategy_names = " / ".join(
        str(item.get("name", item.get("id", "未标注")))
        for item in assessments
    )
    research_focus = packet.get("research_plan", {}).get("focus", [])
    focus_items = "".join(f"<li>{_text(item)}</li>" for item in research_focus)
    as_of = datetime.fromisoformat(str(packet["as_of"]))
    return f"""
      <article class="instrument">
        <header class="instrument-head">
          <div>
            <p class="symbol">{_text(instrument.get("symbol", ""))}</p>
            <h2>{_text(instrument.get("name", ""))}</h2>
          </div>
          <div class="quote">
            <strong>{_price(quote.get("price"))}</strong>
            <span class="{_tone(quote.get("change_pct"))}">
              {_pct(quote.get("change_pct"))}
            </span>
          </div>
        </header>
        <div class="summary-grid">
          <section class="assessment">
            <p class="label">策略判断</p>
            <div class="assessment-row">
              <strong>{_text(assessment.get("level", "暂无判断"))}</strong>
              <span>{score} / 100</span>
            </div>
            <div class="score-track" aria-label="规则评分 {score}">
              <span style="width:{score}%"></span>
            </div>
            <p class="strategy">{_text(strategy_names)}</p>
          </section>
          <dl class="metrics">
            <div><dt>趋势</dt><dd>{_text(metrics.get("trend_state", "暂无"))}</dd></div>
            <div><dt>20日收益</dt><dd class="{_tone(returns.get("20d"))}">
              {_pct(returns.get("20d"))}</dd></div>
            <div><dt>60日收益</dt><dd class="{_tone(returns.get("60d"))}">
              {_pct(returns.get("60d"))}</dd></div>
            <div><dt>60日回撤</dt><dd>{_pct(drawdowns.get("from_high_60d"))}</dd></div>
          </dl>
        </div>
        <div class="evidence">
          <p class="label">判断依据</p>
          <ul>{reason_items or "<li>当前策略未给出具体依据</li>"}</ul>
        </div>
        <div class="evidence research-focus">
          <p class="label">个性化关注</p>
          <ul>{focus_items or "<li>使用产品类别默认研究画像</li>"}</ul>
        </div>
        <footer>
          <span>交易日 {_text(metrics.get("latest_trading_date", "暂无"))}</span>
          <span>{_text(packet.get("data_quality", {}).get("market_source", ""))}</span>
          <time datetime="{_text(packet["as_of"])}">{as_of:%Y-%m-%d %H:%M}</time>
        </footer>
      </article>
    """.strip() + "\n"


def build_dashboard(packets: list[dict[str, Any]]) -> str:
    """渲染完整 HTML；输入为空时仍输出可诊断页面。"""

    valid: list[str] = []
    errors: list[str] = []
    for packet in packets:
        try:
            valid.append(_render_instrument(packet))
        except (KeyError, TypeError, ValueError) as error:
            errors.append(str(error))
    body = "".join(valid)
    if not body:
        body = """
          <section class="empty">
            <h2>暂无可展示的数据</h2>
            <p>先运行 <code>./quant daily --symbol &lt;代码&gt;</code>。</p>
          </section>
        """
    error_html = (
        f'\n    <p class="warning">有 {len(errors)} 个数据包无法解析。</p>'
        if errors
        else ""
    )
    generated_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>投资观察台</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #20231f;
      --muted: #6a7068;
      --line: #dfe3dd;
      --surface: #ffffff;
      --canvas: #f4f6f2;
      --green: #177245;
      --red: #b13c36;
      --amber: #aa6b10;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--canvas);
      color: var(--ink);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .topbar {{ background: #1f2923; color: white; border-bottom: 4px solid #d5a334; }}
    .topbar-inner, main {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; }}
    .topbar-inner {{
      min-height: 72px; display: flex; align-items: center;
      justify-content: space-between; gap: 24px;
    }}
    h1 {{ margin: 0; font-size: 22px; letter-spacing: 0; }}
    .topbar p {{ margin: 0; color: #cdd4cf; font-size: 13px; }}
    main {{ padding: 28px 0 56px; }}
    .overview {{
      display: flex; align-items: baseline; justify-content: space-between;
      gap: 24px; margin-bottom: 14px;
    }}
    .overview h2 {{ margin: 0; font-size: 15px; }}
    .overview span {{ color: var(--muted); font-size: 13px; }}
    .instruments {{ display: grid; gap: 14px; }}
    .instrument {{
      background: var(--surface); border: 1px solid var(--line);
      border-radius: 6px; overflow: hidden;
    }}
    .instrument-head {{
      display: flex; justify-content: space-between; align-items: center;
      gap: 24px; padding: 18px 20px; border-bottom: 1px solid var(--line);
    }}
    .symbol, .label {{
      margin: 0 0 3px; color: var(--muted); font-size: 12px; font-weight: 650;
    }}
    .instrument h2 {{ margin: 0; font-size: 18px; letter-spacing: 0; }}
    .quote {{ display: flex; align-items: baseline; gap: 10px; white-space: nowrap; }}
    .quote strong {{ font-size: 24px; font-variant-numeric: tabular-nums; }}
    .positive {{ color: var(--red); }}
    .negative {{ color: var(--green); }}
    .flat {{ color: var(--muted); }}
    .summary-grid {{
      display: grid; grid-template-columns: minmax(240px, .8fr) minmax(420px, 1.2fr);
      border-bottom: 1px solid var(--line);
    }}
    .assessment {{ padding: 18px 20px; border-right: 1px solid var(--line); }}
    .assessment-row {{ display: flex; justify-content: space-between; gap: 12px; }}
    .assessment-row strong {{ font-size: 16px; }}
    .assessment-row span {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
    .score-track {{ height: 6px; margin: 12px 0 8px; background: #e8ebe6; }}
    .score-track span {{ display: block; height: 100%; background: var(--amber); }}
    .strategy {{ margin: 0; color: var(--muted); font-size: 12px; }}
    .metrics {{
      margin: 0; padding: 18px 20px; display: grid;
      grid-template-columns: repeat(4, minmax(88px, 1fr)); gap: 14px;
    }}
    .metrics div {{ min-width: 0; }}
    dt {{ color: var(--muted); font-size: 12px; }}
    dd {{ margin: 4px 0 0; font-weight: 650; font-variant-numeric: tabular-nums; }}
    .evidence {{ padding: 16px 20px; }}
    .evidence ul {{ margin: 6px 0 0; padding-left: 18px; color: #444b45; }}
    footer {{
      display: flex; flex-wrap: wrap; gap: 8px 20px; padding: 10px 20px;
      background: #fafbf9; border-top: 1px solid var(--line);
      color: var(--muted); font-size: 12px;
    }}
    .empty {{
      padding: 42px 24px; background: white; border: 1px solid var(--line);
      text-align: center;
    }}
    .empty h2 {{ margin-top: 0; }}
    code {{ padding: 2px 5px; background: #edf0eb; border-radius: 3px; }}
    .warning {{ color: #8a4b00; }}
    @media (max-width: 760px) {{
      .topbar-inner, .overview, .instrument-head {{ align-items: flex-start; }}
      .topbar-inner, .overview {{
        flex-direction: column; justify-content: center; gap: 2px;
      }}
      .instrument-head {{ gap: 12px; }}
      .summary-grid {{ grid-template-columns: 1fr; }}
      .assessment {{ border-right: 0; border-bottom: 1px solid var(--line); }}
      .metrics {{ grid-template-columns: repeat(2, minmax(100px, 1fr)); }}
      .quote {{ flex-direction: column; align-items: flex-end; gap: 0; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <h1>投资观察台</h1>
      <p>研究与监控，不执行交易</p>
    </div>
  </header>
  <main>
    <div class="overview">
      <h2>最新标的</h2>
      <span>生成于 {_text(generated_at)}</span>
    </div>{error_html}
    <div class="instruments">{body}</div>
  </main>
</body>
</html>
"""


def write_dashboard(path: Path, packets: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_dashboard(packets), encoding="utf-8")
    return path
