"""回测结果 HTML 报告。"""

from __future__ import annotations

from html import escape
from pathlib import Path

from ..domain.backtesting import BacktestResult
from ..domain.control_plane import StrategyRecord
from .site_navigation import ASSET_VERSION, build_site_header


def _pct(value: float | None) -> str:
    return "暂无" if value is None else f"{value * 100:.2f}%"


def _validation_label(value: str) -> str:
    return {
        "pending": "待验证",
        "passed": "已通过",
        "failed": "失败",
    }.get(value, value)


def build_backtest_report(
    result: BacktestResult,
    strategy: StrategyRecord,
) -> str:
    metrics = result.metrics
    rows = "\n".join(
        f"""
        <tr>
          <td>{item.trading_date.isoformat()}</td>
          <td>{item.equity:,.2f}</td>
          <td>{item.cash:,.2f}</td>
          <td>{item.position_value:,.2f}</td>
          <td>{item.target_weight:.0%}</td>
        </tr>
        """.strip()
        for item in result.equity_curve[-20:]
    )
    warnings = "".join(
        f"<li>{escape(item)}</li>" for item in result.warnings
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(strategy.name)}回测 · Quant Monitor</title>
  <link rel="stylesheet"
    href="../../../docs/assets/docs.css?v={ASSET_VERSION}">
</head>
<body>
{build_site_header("../../../", "strategy")}
  <main class="page">
    <section class="hero">
      <div>
        <p class="eyebrow">Backtest Validation</p>
        <h1>{escape(strategy.name)}回测</h1>
        <p class="hero-copy">
          使用前一交易日及更早数据生成目标仓位，在下一交易日开盘执行。
          结果用于验证策略版本，不是线上交易指令。
        </p>
      </div>
      <aside class="hero-meta">
        <dl>
          <div><dt>策略版本</dt><dd>{escape(strategy.version)}</dd></div>
          <div><dt>标的</dt><dd>{escape(result.specification.symbol)}</dd></div>
          <div>
            <dt>区间</dt>
            <dd>{result.specification.start_date} 至
              {result.specification.end_date}</dd>
          </div>
        </dl>
      </aside>
    </section>
    <section class="section">
      <div class="section-head">
        <p class="section-label">结果</p>
        <div><h2>收益必须与风险和成本同时阅读</h2></div>
      </div>
      <div class="metric-row">
        <div class="metric">
          <strong>{_pct(metrics.total_return)}</strong><span>策略总收益</span>
        </div>
        <div class="metric">
          <strong>{_pct(metrics.benchmark_return)}</strong><span>同期持有基准</span>
        </div>
        <div class="metric">
          <strong>{_pct(metrics.max_drawdown)}</strong><span>最大回撤</span>
        </div>
        <div class="metric">
          <strong>{metrics.trade_count}</strong><span>交易次数</span>
        </div>
        <div class="metric">
          <strong>{_pct(metrics.excess_return)}</strong><span>超额收益</span>
        </div>
        <div class="metric">
          <strong>{_pct(metrics.annualized_return)}</strong><span>年化收益</span>
        </div>
        <div class="metric">
          <strong>{_pct(metrics.annualized_volatility)}</strong>
          <span>年化波动</span>
        </div>
        <div class="metric">
          <strong>{metrics.turnover:.2f}x</strong><span>累计换手</span>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <p class="section-label">冻结契约</p>
        <div>
          <h2>版本、成本和执行时点可复现</h2>
          <p class="section-intro">
            策略验证状态不会由单次回测自动修改，仍需按验收门槛人工复核。
          </p>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>模型</th><th>参数指纹</th><th>初始资金</th>
              <th>佣金</th><th>滑点</th><th>验证状态</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>{escape(result.specification.model_id)}
                {escape(result.specification.model_version)}</td>
              <td><code>{escape(result.specification.parameters_fingerprint)}</code></td>
              <td>{result.specification.initial_cash:,.2f}</td>
              <td>{result.specification.commission_bps:.2f} bps</td>
              <td>{result.specification.slippage_bps:.2f} bps</td>
              <td>
                <span class="status conditional">
                  {escape(_validation_label(strategy.validation_state.value))}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <p class="section-label">执行</p>
        <div><h2>最近 20 个交易日权益状态</h2></div>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>日期</th><th>权益</th><th>现金</th><th>持仓市值</th><th>目标仓位</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <p class="section-label">限制</p>
        <div><h2>当前验证边界</h2></div>
      </div>
      <ul>{warnings}</ul>
    </section>
  </main>
  <footer class="site-footer">
    <div class="footer-inner">
      <span>回测结果用于研究验证，不构成自动交易指令。</span>
      <span>{escape(strategy.record_id)}</span>
    </div>
  </footer>
  <script
    src="../../../docs/assets/navigation.js?v={ASSET_VERSION}"></script>
</body>
</html>
"""


def write_backtest_report(
    path: Path,
    result: BacktestResult,
    strategy: StrategyRecord,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_backtest_report(result, strategy),
        encoding="utf-8",
    )
    return path
