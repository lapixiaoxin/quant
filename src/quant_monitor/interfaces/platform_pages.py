"""五个核心业务模块的静态管理页面。"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from ..config import Settings, StrategyProfileConfig
from ..domain.control_plane import StrategyRecord
from ..domain.factors import FactorRegistry
from ..infrastructure.control_repository import SQLiteControlPlaneRepository
from ..infrastructure.selection_config import load_selection_universe
from ..infrastructure.strategy_catalog import StrategyCatalog
from .portal import PortalEntry, discover_portal_entries, readable_href
from .research_report_pages import report_html_path
from .site_navigation import ASSET_VERSION, build_site_header


def _json_list(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    return [str(item) for item in value] if isinstance(value, list) else []


def _status(value: str) -> str:
    labels = {
        "active": "启用",
        "draft": "草稿",
        "retired": "弃用",
        "pending": "待验证",
        "passed": "已通过",
        "failed": "失败",
        "completed": "已完成",
        "partial": "部分完成",
        "running": "运行中",
        "screened": "待深度研究",
        "sent": "已发送",
        "not_requested": "未要求发送",
        "available": "可用",
        "reserved": "预留",
        "short": "短期",
        "long": "长期",
        "manual": "人工",
        "scheduled": "定时",
        "remote": "飞书远程",
        "base": "确定性基础",
        "traecli": "TraeCode",
        "deterministic": "确定性计算",
        "strategy": "策略注入",
        "external": "外部扩展",
        "legacy": "历史索引",
        "strategy_report": "策略报告",
        "base_report": "基础报告",
        "selection": "选择报告",
        "eligible": "通过硬门槛",
        "needs_research": "待补证据",
        "excluded": "已淘汰",
        "data_error": "数据失败",
        "feishu": "飞书",
    }
    return labels.get(value, value or "未知")


def _status_class(value: str) -> str:
    if value in {"active", "passed", "completed", "sent", "available"}:
        return "ok"
    if value in {
        "draft",
        "pending",
        "partial",
        "running",
        "screened",
        "reserved",
        "not_requested",
        "legacy",
    }:
        return "conditional"
    return "no"


def _page(
    *,
    title: str,
    current: str,
    content: str,
) -> str:
    module_numbers = {
        "selection": "01",
        "strategy": "02",
        "analysis": "03",
        "reports": "04",
        "channels": "05",
    }
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · Quant Monitor</title>
  <link rel="stylesheet"
    href="../../docs/assets/docs.css?v={ASSET_VERSION}">
</head>
<body class="module-page module-{escape(current)}">
{build_site_header("../../", current)}
  <main class="page control-page">
    <section class="control-heading">
      <span class="module-index">{module_numbers[current]}</span>
      <h1>{escape(title)}</h1>
    </section>
{content}
  </main>
  <script
    src="../../docs/assets/navigation.js?v={ASSET_VERSION}"></script>
  <script src="../../docs/assets/catalog.js?v={ASSET_VERSION}"></script>
</body>
</html>
"""


def _filter_bar(
    catalog_id: str,
    selects: tuple[tuple[str, str, tuple[str, ...]], ...],
) -> str:
    select_html = "\n".join(
        f"""
        <label>
          <span>{escape(label)}</span>
          <select data-field="{escape(field)}">
            <option value="">全部</option>
            {"".join(
                f'<option value="{escape(item)}">{escape(_status(item))}</option>'
                for item in options
            )}
          </select>
        </label>
        """.strip()
        for label, field, options in selects
    )
    return f"""
      <form class="catalog-filters" data-catalog-filters="{catalog_id}">
        <label class="catalog-search">
          <span>搜索</span>
          <input data-field="text" type="search"
            placeholder="代码、名称、ID 或路径">
        </label>
{select_html}
        <button type="reset">重置</button>
        <output data-catalog-count="{catalog_id}"></output>
      </form>
    """.strip()


def _selection_page(
    root: Path,
    control: dict[str, Any],
) -> str:
    runs: dict[str, dict[str, Any]] = {}
    for item in control["selection_runs"]:
        runs.setdefault(item["universe_id"], item)
    rows: list[str] = []
    for path in sorted((root / "research" / "universes").glob("*.toml")):
        universe = load_selection_universe(path)
        run = runs.get(universe.universe_id) or _legacy_selection_run(
            root,
            universe.universe_id,
        )
        status = _selection_status(root, run)
        report_path = str(run.get("report_path", ""))
        report_ready = bool(
            status == "completed"
            and report_path
            and (root / report_path).is_file()
        )
        name = (
            f'<a href="../../{escape(report_path)}">'
            f"<strong>{escape(universe.name)}</strong></a>"
            if report_ready
            else f"<strong>{escape(universe.name)}</strong>"
        )
        rows.append(
            f"""
        <tr data-catalog-row
          data-horizon="{universe.horizon.value}"
          data-status="{status}"
          data-theme="{escape(universe.theme)}">
          <td>{name}
            <small>{escape(universe.universe_id)}</small></td>
          <td>{escape(_status(universe.horizon.value))}</td>
          <td>{escape(universe.theme)}</td>
          <td>{universe.created_at or "未标注"}</td>
          <td>{run.get("candidate_count", len(universe.candidates))}</td>
          <td>{run.get("shortlist_count", "待运行")}</td>
          <td>
            <span class="status {_status_class(status)}">
              {escape(_status(status))}
            </span>
          </td>
        </tr>
            """.strip()
        )
    content = f"""
    <section class="section">
      <div class="section-head">
        <h2>候选池</h2>
      </div>
{_filter_bar(
    "selections",
    (
        ("期限", "horizon", ("short", "long")),
        (
            "状态",
            "status",
            ("completed", "screened", "running", "failed", "pending"),
        ),
    ),
)}
      <div class="table-wrap">
        <table class="management-table" data-catalog="selections">
          <thead><tr><th>候选池</th><th>期限</th><th>主题</th><th>创建</th><th>候选</th><th>初筛合格</th><th>状态</th></tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>
    </section>
    """
    return _page(
        title="标的选择",
        current="selection",
        content=content,
    )


def _selection_status(root: Path, run: dict[str, Any]) -> str:
    status = str(run.get("status", "pending"))
    report_path = str(run.get("report_path", ""))
    if status not in {"completed", "screened"}:
        return status
    report = root / report_path
    if not report.is_file():
        return "screened"
    if status == "completed":
        return status
    try:
        requested_at = datetime.fromisoformat(str(run["requested_at"]))
    except (KeyError, ValueError):
        return "screened"
    report_at = datetime.fromtimestamp(
        report.stat().st_mtime,
        tz=requested_at.tzinfo,
    )
    return "completed" if report_at >= requested_at else status


def _legacy_selection_run(root: Path, universe_id: str) -> dict[str, Any]:
    packet_path = (
        root / "data" / "selections" / "latest" / f"{universe_id}.json"
    )
    if not packet_path.exists():
        return {}
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    summary = packet.get("summary", {})
    if not isinstance(summary, dict):
        return {}
    requested_at_raw = str(packet.get("as_of", ""))
    try:
        requested_at = datetime.fromisoformat(requested_at_raw)
    except ValueError:
        return {}
    report_path = (
        root
        / "research"
        / "selections"
        / universe_id
        / f"{requested_at:%Y-%m-%d}-selection.html"
    )
    return {
        "status": "screened",
        "requested_at": requested_at_raw,
        "candidate_count": summary.get("candidate_count", "未知"),
        "shortlist_count": summary.get("eligible", "未索引"),
        "report_path": str(report_path.relative_to(root)),
    }


def _backtest_row(item: dict[str, Any]) -> str:
    status = str(item["status"])
    run_id = escape(str(item["run_id"]))
    result_path = escape(str(item["result_path"]))
    run_cell = (
        f'<a href="../../{result_path}">{run_id}</a>'
        if status == "completed"
        else f"<strong>{run_id}</strong>"
    )
    return f"""
        <tr data-catalog-row data-status="{escape(status)}">
          <td>{run_cell}</td>
          <td>{escape(str(item['symbol']))}</td>
          <td>{escape(str(item['strategy_record_id']))}</td>
          <td>
            <span class="status {_status_class(status)}">
              {escape(_status(status))}
            </span>
          </td>
          <td>{_pct_value(item.get("total_return"))}</td>
          <td>{_pct_value(item.get("max_drawdown"))}</td>
          <td>{_value_or(item.get("trade_count"), "暂无")}</td>
        </tr>
    """.strip()


def _strategy_parameter_list(
    parameters: dict[str, Any],
    *,
    label_overrides: dict[str, str] | None = None,
) -> str:
    labels = {
        "strategy_id": "线上策略",
        "deep_drawdown": "深度回撤",
        "attention_drawdown": "关注回撤",
        "mild_drawdown": "温和回撤",
        "near_high": "接近高位",
        "high_volatility": "高波动率",
        "full_score": "高关注分数",
        "watch_score": "观察分数",
        "full_weight": "高关注回测仓位",
        "watch_weight": "观察回测仓位",
        "minimum_history_observations": "最少估值观察数",
        "expensive_percentile": "偏贵分位上限",
        "first_add_percentile": "第一增配分位",
        "second_add_percentile": "第二增配分位",
        "full_add_percentile": "充分增配分位",
        "minimum_weight": "最低研究仓位",
        "base_weight": "核心研究仓位",
        "first_add_weight": "第一增配仓位",
        "second_add_weight": "第二增配仓位",
        "first_add_drawdown": "第一回撤确认",
        "second_add_drawdown": "第二回撤确认",
        "full_add_drawdown": "充分回撤确认",
        "dividend_cut_limit": "分红削减失效线",
        "rebalance_interval_days": "最短再平衡交易日",
    }
    percentage_keys = {
        "deep_drawdown",
        "attention_drawdown",
        "mild_drawdown",
        "near_high",
        "high_volatility",
        "full_weight",
        "watch_weight",
        "expensive_percentile",
        "first_add_percentile",
        "second_add_percentile",
        "full_add_percentile",
        "minimum_weight",
        "base_weight",
        "first_add_weight",
        "second_add_weight",
        "first_add_drawdown",
        "second_add_drawdown",
        "full_add_drawdown",
        "dividend_cut_limit",
    }
    if label_overrides:
        labels.update(label_overrides)
    rows = []
    for key, value in parameters.items():
        if key in percentage_keys and isinstance(value, (int, float)):
            rendered = f"{float(value) * 100:.2f}%"
        elif isinstance(value, (dict, list, tuple)):
            rendered = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
            )
        else:
            rendered = str(value)
        rows.append(
            "<div>"
            f"<dt>{escape(labels.get(key, key))}</dt>"
            f"<dd>{escape(rendered)}</dd>"
            "</div>"
        )
    if not rows:
        return '<p class="strategy-empty">未配置可调参数</p>'
    return f'<dl class="strategy-parameters">{"".join(rows)}</dl>'


def _parameter(
    parameters: dict[str, Any],
    key: str,
    default: float | int,
) -> float:
    return float(parameters.get(key, default))


def _pct(parameter: float) -> str:
    return f"{parameter:.0%}"


def _dynamic_strategy_details(
    profile_parameters: dict[str, Any],
    backtest_parameters: dict[str, Any],
) -> str:
    expensive = _parameter(
        profile_parameters,
        "expensive_percentile",
        0.20,
    )
    first = _parameter(
        profile_parameters,
        "first_add_percentile",
        0.70,
    )
    second = _parameter(
        profile_parameters,
        "second_add_percentile",
        0.85,
    )
    full = _parameter(
        profile_parameters,
        "full_add_percentile",
        0.95,
    )
    minimum_weight = _parameter(
        profile_parameters,
        "minimum_weight",
        0.20,
    )
    base_weight = _parameter(profile_parameters, "base_weight", 0.30)
    first_weight = _parameter(
        profile_parameters,
        "first_add_weight",
        0.50,
    )
    second_weight = _parameter(
        profile_parameters,
        "second_add_weight",
        0.75,
    )
    full_weight = _parameter(profile_parameters, "full_weight", 1.00)
    first_drawdown = _parameter(
        profile_parameters,
        "first_add_drawdown",
        -0.05,
    )
    second_drawdown = _parameter(
        profile_parameters,
        "second_add_drawdown",
        -0.10,
    )
    full_drawdown = _parameter(
        profile_parameters,
        "full_add_drawdown",
        -0.15,
    )
    minimum_observations = int(
        profile_parameters.get("minimum_history_observations", 726)
    )
    dividend_cut = _parameter(
        profile_parameters,
        "dividend_cut_limit",
        -0.15,
    )
    interval = int(
        backtest_parameters.get("rebalance_interval_days", 20)
    )
    valuation_symbol = escape(
        str(backtest_parameters.get("valuation_symbol", "未配置"))
    )
    rows = (
        (
            f"0–{_pct(expensive)}",
            "估值偏贵",
            _pct(minimum_weight),
            "不要求",
            "不新增动态仓位",
        ),
        (
            f"{_pct(expensive)}–{_pct(first)}",
            "核心观察",
            _pct(base_weight),
            "不要求",
            "保留核心研究敞口",
        ),
        (
            f"{_pct(first)}–{_pct(second)}",
            "第一增配区",
            _pct(first_weight),
            f"242日回撤 ≤ {_pct(first_drawdown)}",
            f"未确认则保持 {_pct(base_weight)}",
        ),
        (
            f"{_pct(second)}–{_pct(full)}",
            "第二增配区",
            _pct(second_weight),
            f"242日回撤 ≤ {_pct(second_drawdown)}",
            f"未确认则降为 {_pct(first_weight)}",
        ),
        (
            f"{_pct(full)}–100%",
            "极端低估区",
            _pct(full_weight),
            f"242日回撤 ≤ {_pct(full_drawdown)}",
            f"未确认则降为 {_pct(second_weight)}",
        ),
    )
    decision_rows = "".join(
        "<tr>"
        f"<td><strong>{band}</strong></td>"
        f"<td>{state}</td>"
        f"<td><strong>{weight}</strong></td>"
        f"<td>{drawdown}</td>"
        f"<td>{fallback}</td>"
        "</tr>"
        for band, state, weight, drawdown, fallback in rows
    )
    execution_rows = (
        (
            "再平衡间隔",
            f"{interval} 个交易日",
            "约每月评估一次；期间保持上次目标仓位。",
            "rebalance_interval_days",
        ),
        (
            "估值来源标的",
            valuation_symbol,
            "510720 跟踪的上证国有企业红利指数代码。",
            "valuation_symbol",
        ),
        (
            "估值统计窗口",
            "滚动 3 年",
            "使用来源逐日发布的三年历史分位，不用全样本未来数据重算。",
            "valuation_history_window",
        ),
        (
            "估值加权口径",
            "市值加权",
            "按成分股市值汇总指数股息率；不同加权口径不能混用。",
            "valuation_weighting",
        ),
        (
            "信号时点",
            "时点一致",
            "只使用当时已经公开的数据，信号次一交易日开盘执行。",
            "valuation_timing",
        ),
        (
            "数据缺失",
            "拒绝运行",
            "缺少同日股息率或历史不足时停止，不用价格回撤代替。",
            "missing_valuation_policy",
        ),
        (
            "基本面门禁",
            "指数规则代理",
            "本轮以指数连续分红和支付率筛选规则近似，尚未逐日回放财务数据。",
            "fundamental_guard_mode",
        ),
    )
    execution_html = "".join(
        "<tr>"
        f"<td><strong>{label}</strong><small>{key}</small></td>"
        f"<td>{value}</td><td>{description}</td>"
        "</tr>"
        for label, value, description, key in execution_rows
    )
    return f"""
            <section class="strategy-reading-guide">
              <h3>判断顺序</h3>
              <ol class="strategy-flow">
                <li><span>1</span><strong>先看历史分位</strong>
                  <small>分位越高，当前股息率相对历史越高。</small></li>
                <li><span>2</span><strong>映射目标仓位</strong>
                  <small>先按分位找到对应档位。</small></li>
                <li><span>3</span><strong>检查回撤确认</strong>
                  <small>只有高分位且价格已有回撤，才完成增配。</small></li>
                <li><span>4</span><strong>通过基本面门禁</strong>
                  <small>分红或盈利恶化时禁止越跌越加。</small></li>
              </ol>
            </section>
            <section class="strategy-decision-section">
              <div class="strategy-section-heading">
                <h3>分位、仓位和回撤对应表</h3>
                <p>目标仓位是策略预算内部的研究敞口，不是总账户仓位。</p>
              </div>
              <div class="table-wrap">
                <table class="strategy-decision-table">
                  <thead><tr><th>股息率历史分位</th><th>状态</th>
                    <th>目标仓位</th><th>回撤确认</th>
                    <th>未确认时</th></tr></thead>
                  <tbody>{decision_rows}</tbody>
                </table>
              </div>
            </section>
            <section class="strategy-guard-section">
              <div class="strategy-section-heading">
                <h3>增配前必须通过的门禁</h3>
                <p>任一关键输入不可靠，都不输出积极方向。</p>
              </div>
              <dl class="strategy-guard-list">
                <div><dt>{minimum_observations} 个观察值</dt>
                  <dd>股息率历史至少约三年，避免短样本分位失真。</dd></div>
                <div><dt>{_pct(dividend_cut)} 分红削减线</dt>
                  <dd>达到该幅度视为基本面失效，只保留最低研究仓位。</dd></div>
                <div><dt>数据陈旧或缺失</dt>
                  <dd>直接阻断判断，不降级成“价格跌了就买”。</dd></div>
              </dl>
            </section>
            <section class="strategy-execution-section">
              <div class="strategy-section-heading">
                <h3>回测如何执行</h3>
                <p>这里描述历史模拟口径，不代表实盘订单。</p>
              </div>
              <div class="table-wrap">
                <table class="strategy-execution-table">
                  <thead><tr><th>项目</th><th>当前设置</th>
                    <th>实际含义</th></tr></thead>
                  <tbody>{execution_html}</tbody>
                </table>
              </div>
            </section>
            <section class="strategy-glossary">
              <div class="strategy-section-heading">
                <h3>术语速查</h3>
              </div>
              <dl>
                <div><dt>股息率</dt>
                  <dd>指数成分股预期年度现金分红相对当前价格的比例。</dd></div>
                <div><dt>历史分位</dt>
                  <dd>当前股息率在历史样本中的位置；70%表示高于约七成历史观察值。</dd></div>
                <div><dt>242日回撤</dt>
                  <dd>当前价格相对最近约一年最高收盘价的跌幅。</dd></div>
                <div><dt>目标仓位</dt>
                  <dd>策略预算中计划暴露于该标的的比例，不等于总资产配置比例。</dd></div>
                <div><dt>时点一致</dt>
                  <dd>历史某天只能使用那天已经公开的信息，防止未来数据泄漏。</dd></div>
                <div><dt>参数指纹</dt>
                  <dd>参数内容的哈希摘要，用于识别回测后参数是否被改动。</dd></div>
              </dl>
              <details class="strategy-raw-parameters">
                <summary>查看原始参数名</summary>
                {_strategy_parameter_list(
                    profile_parameters,
                    label_overrides={
                        "full_weight": "充分增配仓位",
                    },
                )}
              </details>
            </section>
    """.strip()


def _strategy_datetime(value: datetime | None) -> str:
    return value.isoformat(sep=" ", timespec="minutes") if value else "未设置"


def _strategy_record(
    item: StrategyRecord,
    profile: StrategyProfileConfig,
    *,
    bound: bool,
    operational: bool,
    configured: bool = True,
) -> str:
    backtest_model = (
        f"{item.backtest_model_id} v{item.backtest_model_version}"
        if item.backtest_model_id
        else "未绑定"
    )
    if bound and operational:
        configuration_status = "配置一致"
        configuration_class = "ok"
    elif bound:
        configuration_status = "研究标的停用"
        configuration_class = "conditional"
    elif configured:
        configuration_status = "尚未绑定"
        configuration_class = "conditional"
    else:
        configuration_status = "草案未配置"
        configuration_class = "conditional"
    if profile.strategy_id == "dividend_yield_dynamic":
        detail_content = _dynamic_strategy_details(
            profile.parameters,
            item.backtest_parameters,
        )
    else:
        detail_content = f"""
            <div class="strategy-detail-columns">
              <section>
                <h3>判断参数</h3>
                {_strategy_parameter_list(profile.parameters)}
              </section>
              <section>
                <h3>回测执行参数</h3>
                {_strategy_parameter_list(item.backtest_parameters)}
                <p class="strategy-boundary">
                  回测仓位仅用于历史模拟，不代表实盘仓位或自动交易指令。
                </p>
              </section>
            </div>
        """.strip()
    return f"""
        <details class="strategy-record" data-catalog-row
          data-lifecycle="{item.lifecycle.value}"
          data-validation="{item.validation_state.value}"
          data-horizon="{item.horizon.value}">
          <summary>
            <span class="strategy-record-title">
              <strong>{escape(item.name)}</strong>
              <small>{escape(item.record_id)}</small>
            </span>
            <span class="strategy-record-facts">
              <span><small>标的</small>
                <strong>{escape("、".join(item.symbols))}</strong></span>
              <span><small>版本</small>
                <strong>{escape(item.version)}</strong></span>
              <span><small>期限</small>
                <strong>{escape(_status(item.horizon.value))}</strong></span>
            </span>
            <span class="strategy-record-state">
              <span class="status {_status_class(item.lifecycle.value)}">
                {escape(_status(item.lifecycle.value))}
              </span>
              <span
                class="status {_status_class(item.validation_state.value)}">
                {escape(_status(item.validation_state.value))}
              </span>
              <span class="status {configuration_class}">
                {configuration_status}
              </span>
              <span class="strategy-expand">详情</span>
            </span>
          </summary>
          <div class="strategy-record-body">
            <section class="strategy-thesis">
              <h3>一句话逻辑</h3>
              <p>{escape(item.thesis)}</p>
            </section>
            {detail_content}
            <dl class="strategy-record-metadata">
              <div><dt>策略画像</dt>
                <dd><code>{escape(item.profile_id)}</code></dd></div>
              <div><dt>线上算法</dt>
                <dd><code>{escape(profile.strategy_id)}</code></dd></div>
              <div><dt>回测模型</dt>
                <dd><code>{escape(backtest_model)}</code></dd></div>
              <div><dt>创建时间</dt>
                <dd>{escape(_strategy_datetime(item.created_at))}</dd></div>
              <div><dt>启用时间</dt>
                <dd>{escape(_strategy_datetime(item.enabled_at))}</dd></div>
              <div><dt>弃用时间</dt>
                <dd>{escape(_strategy_datetime(item.retired_at))}</dd></div>
              <div class="strategy-fingerprint"><dt>参数指纹</dt>
                <dd><code>{escape(item.parameters_fingerprint)}</code></dd></div>
            </dl>
          </div>
        </details>
    """.strip()


def _strategy_page(
    settings: Settings,
    catalog: StrategyCatalog,
    control: dict[str, Any],
) -> str:
    rows = []
    instruments = {
        instrument.symbol: instrument
        for instrument in settings.instruments
    }
    for item in catalog.records:
        configured_profile = settings.strategy_profiles.get(item.profile_id)
        strategy_parameters = item.backtest_parameters.get(
            "strategy_parameters",
            {},
        )
        if not isinstance(strategy_parameters, dict):
            strategy_parameters = {}
        profile = configured_profile or StrategyProfileConfig(
            profile_id=item.profile_id,
            strategy_id=str(
                item.backtest_parameters.get("strategy_id", "未配置")
            ),
            parameters=dict(strategy_parameters),
        )
        bound = configured_profile is not None and all(
            symbol in instruments
            and item.profile_id in instruments[symbol].strategy_profile_ids
            for symbol in item.symbols
        )
        operational = bound and all(
            instruments[symbol].enabled for symbol in item.symbols
        )
        rows.append(
            _strategy_record(
                item,
                profile,
                bound=bound,
                operational=operational,
                configured=configured_profile is not None,
            )
        )
    backtests = "".join(
        _backtest_row(item) for item in control["backtest_runs"]
    )
    content = f"""
    <section class="section">
      <div class="section-head">
        <h2>策略版本</h2>
      </div>
{_filter_bar(
    "strategies",
    (
        ("生命周期", "lifecycle", ("draft", "active", "retired")),
        ("验证", "validation", ("pending", "passed", "failed")),
        ("期限", "horizon", ("short", "long")),
    ),
)}
      <div class="strategy-record-list" data-catalog="strategies">
        {"".join(rows)}
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <h2>回测记录</h2>
      </div>
{_filter_bar("backtests", (("状态", "status", ("running", "completed", "failed")),))}
      <div class="table-wrap">
        <table data-catalog="backtests">
          <thead><tr><th>运行</th><th>标的</th><th>策略记录</th><th>状态</th><th>收益</th><th>回撤</th><th>交易数</th></tr></thead>
          <tbody>{backtests or _empty_row(7, "暂无回测记录")}</tbody>
        </table>
      </div>
    </section>
    """
    return _page(
        title="策略与回测",
        current="strategy",
        content=content,
    )


def _pct_value(value: object) -> str:
    return "暂无" if value is None else f"{float(value) * 100:.2f}%"


def _value_or(value: object, fallback: str) -> str:
    return fallback if value is None else escape(str(value))


def _empty_row(columns: int, message: str) -> str:
    return (
        f'<tr data-catalog-row><td colspan="{columns}">'
        f"{escape(message)}</td></tr>"
    )


def _analysis_page(
    control: dict[str, Any],
    factors: FactorRegistry,
) -> str:
    rows = "".join(
        f"""
        <tr data-catalog-row
          data-trigger="{escape(str(item['trigger']))}"
          data-status="{escape(str(item['status']))}"
          data-mode="{escape(str(item['mode']))}">
          <td><strong>{escape(str(item['request_id']))}</strong>
            <small>{escape(str(item['requested_at']))}</small></td>
          <td>{escape("、".join(_json_list(item["symbols_json"])))}</td>
          <td>{escape(_status(str(item["trigger"])))}</td>
          <td>{escape("、".join(_json_list(item["cycles_json"])))}</td>
          <td>{escape(_status(str(item["mode"])))}</td>
          <td>
            <span class="status {_status_class(str(item['status']))}">
              {escape(_status(str(item['status'])))}
            </span>
          </td>
        </tr>
        """.strip()
        for item in control["analysis_runs"]
    )
    factor_rows = "".join(
        f"""
        <tr data-catalog-row
          data-availability="{item.availability}"
          data-source="{item.source_kind}">
          <td>
            <strong>{escape(item.name)}</strong>
            <small>{escape(item.factor_id)}</small>
          </td>
          <td>{escape(_status(item.source_kind))}</td>
          <td>
            <span class="status {_status_class(item.availability)}">
              {escape(_status(item.availability))}
            </span>
          </td>
          <td>{escape(item.description)}</td>
        </tr>
        """.strip()
        for item in factors.all
    )
    content = f"""
    <section class="section">
      <div class="section-head">
        <h2>分析任务</h2>
      </div>
{_filter_bar(
    "analysis",
    (
        ("触发", "trigger", ("manual", "scheduled", "remote")),
        ("状态", "status", ("running", "completed", "partial", "failed")),
        ("模式", "mode", ("base", "traecli")),
    ),
)}
      <div class="table-wrap">
        <table data-catalog="analysis">
          <thead><tr><th>任务</th><th>标的</th><th>触发</th><th>周期</th><th>模式</th><th>状态</th></tr></thead>
          <tbody>{rows or _empty_row(6, "暂无分析记录")}</tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <h2>分析因子</h2>
      </div>
{_filter_bar(
    "factors",
    (
        ("可用性", "availability", ("available", "reserved")),
        ("来源", "source", ("deterministic", "strategy", "external")),
    ),
)}
      <div class="table-wrap">
        <table data-catalog="factors">
          <thead><tr><th>因子</th><th>来源</th><th>状态</th><th>说明</th></tr></thead>
          <tbody>{factor_rows}</tbody>
        </table>
      </div>
    </section>
    """
    return _page(
        title="分析作业",
        current="analysis",
        content=content,
    )


def _report_page(
    root: Path,
    control: dict[str, Any],
) -> str:
    indexed_paths = {
        (
            report_html_path(Path(str(item["path"]))).as_posix()
            if str(item["path"]).lower().endswith(".md")
            else str(item["path"])
        )
        for item in control["reports"]
    }
    rows: list[str] = []
    for item in control["reports"]:
        cycles = "、".join(_json_list(item["cycles_json"]))
        channels = "、".join(_json_list(item["channels_json"])) or "网页"
        report_path = str(item["path"])
        if report_path.lower().endswith(".md"):
            report_path = report_html_path(Path(report_path)).as_posix()
        href = f"../../{report_path}"
        rows.append(
            f"""
        <tr data-catalog-row
          data-symbol="{escape(str(item['symbol']))}"
          data-type="{escape(str(item['report_type']))}"
          data-delivery="{escape(str(item['delivery_status']))}">
          <td>
            <a href="{escape(href, quote=True)}">
              <strong>{escape(str(item['title']))}</strong>
            </a>
            <small>{escape(str(item['report_id']))}</small>
          </td>
          <td>{escape(str(item['symbol']))}</td>
          <td>{escape(_status(str(item['report_type'])))}</td>
          <td>{escape(cycles)}</td>
          <td>{escape(str(item['generated_at']))}</td>
          <td>{escape(channels)}</td>
          <td>
            <span
              class="status {_status_class(str(item['delivery_status']))}">
              {escape(_status(str(item['delivery_status'])))}
            </span>
          </td>
        </tr>
            """.strip()
        )
    legacy = [
        item
        for item in discover_portal_entries(root)
        if item.category in {
            "标的报告",
            "选择报告",
            "标的档案",
        }
        and item.href not in indexed_paths
    ]
    rows.extend(_legacy_report_row(item) for item in legacy)
    content = f"""
    <section class="section">
      <div class="section-head">
        <h2>报告</h2>
      </div>
{_filter_bar(
    "reports",
    (
        ("类型", "type", ("strategy_report", "base_report", "selection", "legacy")),
        (
            "发布",
            "delivery",
            ("sent", "partial", "failed", "not_requested", "legacy"),
        ),
    ),
)}
      <div class="table-wrap">
        <table class="management-table" data-catalog="reports">
          <thead><tr><th>报告</th><th>标的</th><th>类型</th><th>周期</th><th>时间</th><th>渠道</th><th>发布</th></tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>
    </section>
    """
    return _page(
        title="报告中心",
        current="reports",
        content=content,
    )


def _legacy_report_row(item: PortalEntry) -> str:
    symbol = next(
        (
            part
            for part in item.href.replace("-", "/").split("/")
            if part.isdigit() and len(part) == 6
        ),
        "",
    )
    href = readable_href(item.href, root_prefix="../../")
    if item.category == "标的报告":
        report_type = (
            "base_report"
            if "-base" in item.href
            else "strategy_report"
        )
        type_label = _status(report_type)
    elif item.category == "选择报告":
        report_type = "selection"
        type_label = "选择报告"
    else:
        report_type = "legacy"
        type_label = "历史报告"
    return f"""
        <tr data-catalog-row data-symbol="{symbol}"
          data-type="{report_type}" data-delivery="legacy">
          <td>
            <a href="{escape(href, quote=True)}">
              <strong>{escape(item.title)}</strong>
            </a>
            <small>{escape(item.href)}</small>
          </td>
          <td>{escape(symbol or "未索引")}</td>
          <td>{escape(type_label)}</td>
          <td>未索引</td>
          <td>{escape(item.published)}</td>
          <td>网页</td>
          <td><span class="status conditional">历史</span></td>
        </tr>
    """.strip()


def _channel_page(settings: Settings) -> str:
    channel_rows = "".join(
        f"""
        <tr data-catalog-row
          data-type="{escape(item.channel_type)}"
          data-status="{'active' if item.enabled else 'retired'}">
          <td><strong>{escape(item.channel_id)}</strong></td>
          <td>{escape(_status(item.channel_type))}</td>
          <td>
            <span class="status {'ok' if item.enabled else 'no'}">
              {'启用' if item.enabled else '停用'}
            </span>
          </td>
          <td>{_channel_role(item.channel_type)}</td>
        </tr>
        """.strip()
        for item in settings.notification_channels.values()
    )
    policy_rows = "".join(
        f"""
        <tr data-catalog-row data-status="{'active' if item.enabled else 'retired'}">
          <td><strong>{escape(item.policy_id)}</strong></td>
          <td>{'、'.join(item.events) or '无'}</td>
          <td>{'、'.join(item.channels) or '无'}</td>
          <td>
            <span class="status {'ok' if item.enabled else 'no'}">
              {'启用' if item.enabled else '停用'}
            </span>
          </td>
        </tr>
        """.strip()
        for item in settings.notification_policies.values()
    )
    content = f"""
    <section class="section">
      <div class="section-head">
        <h2>发送通道</h2>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>通道</th><th>类型</th><th>状态</th><th>职责</th></tr></thead>
          <tbody>{channel_rows or '<tr><td colspan="4">暂无通道</td></tr>'}</tbody>
        </table>
      </div>
    </section>
    <section class="section">
      <div class="section-head">
        <h2>通知策略</h2>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>策略</th><th>事件</th><th>通道</th><th>状态</th></tr></thead>
          <tbody>{policy_rows}</tbody>
        </table>
      </div>
    </section>
    """
    return _page(
        title="渠道与通知",
        current="channels",
        content=content,
    )


def _channel_role(channel_type: str) -> str:
    return "飞书报告与远程命令" if channel_type == "feishu" else "扩展通道"


def write_platform_pages(
    root: Path,
    settings: Settings,
    catalog: StrategyCatalog,
    control_repository: SQLiteControlPlaneRepository,
    factors: FactorRegistry,
) -> tuple[Path, ...]:
    catalog.validate_settings(settings)
    snapshot = control_repository.export_snapshot()
    pages = {
        root / "research" / "selections" / "index.html": _selection_page(
            root,
            snapshot,
        ),
        root / "research" / "strategies" / "index.html": _strategy_page(
            settings,
            catalog,
            snapshot,
        ),
        root / "research" / "analysis" / "index.html": _analysis_page(
            snapshot,
            factors,
        ),
        root / "research" / "reports" / "index.html": _report_page(
            root,
            snapshot,
        ),
        root / "research" / "channels" / "index.html": _channel_page(settings),
    }
    for path, content in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tuple(pages)
