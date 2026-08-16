"""五个核心业务模块的静态管理页面。"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from ..config import Settings
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
    runs = {
        item["universe_id"]: item
        for item in control["selection_runs"]
    }
    rows: list[str] = []
    for path in sorted((root / "research" / "universes").glob("*.toml")):
        universe = load_selection_universe(path)
        run = runs.get(universe.universe_id) or _legacy_selection_run(
            root,
            universe.universe_id,
        )
        status = str(run.get("status", "pending"))
        report_path = str(run.get("report_path", ""))
        link = (
            f'../../{escape(report_path)}'
            if report_path
            else f"../universes/{escape(path.name)}"
        )
        rows.append(
            f"""
        <tr data-catalog-row
          data-horizon="{universe.horizon.value}"
          data-status="{status}"
          data-theme="{escape(universe.theme)}">
          <td><a href="{link}"><strong>{escape(universe.name)}</strong></a>
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
            ("completed", "running", "failed", "pending", "legacy"),
        ),
    ),
)}
      <div class="table-wrap">
        <table data-catalog="selections">
          <thead><tr><th>候选池</th><th>期限</th><th>主题</th><th>创建</th><th>候选</th><th>短名单</th><th>状态</th></tr></thead>
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


def _legacy_selection_run(root: Path, universe_id: str) -> dict[str, Any]:
    packet_path = (
        root / "data" / "selections" / "latest" / f"{universe_id}.json"
    )
    report_path = packet_path.with_suffix(".html")
    if not packet_path.exists() or not report_path.exists():
        return {}
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    summary = packet.get("summary", {})
    if not isinstance(summary, dict):
        return {}
    return {
        "status": "legacy",
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


def _strategy_page(
    settings: Settings,
    catalog: StrategyCatalog,
    control: dict[str, Any],
) -> str:
    rows = []
    for item in catalog.records:
        profile = settings.strategy_profiles[item.profile_id]
        bound = all(
            item.profile_id
            in settings.instrument_for(symbol).strategy_profile_ids
            for symbol in item.symbols
        )
        rows.append(
            f"""
        <tr data-catalog-row
          data-lifecycle="{item.lifecycle.value}"
          data-validation="{item.validation_state.value}"
          data-horizon="{item.horizon.value}">
          <td><strong>{escape(item.name)}</strong>
            <small>{escape(item.record_id)}</small></td>
          <td>{escape(",".join(item.symbols))}</td>
          <td>{escape(item.version)}</td>
          <td>
            <span class="status {_status_class(item.lifecycle.value)}">
              {escape(_status(item.lifecycle.value))}
            </span>
          </td>
          <td>{escape(_status(item.horizon.value))}</td>
          <td>
            <span class="status {_status_class(item.validation_state.value)}">
              {escape(_status(item.validation_state.value))}
            </span>
          </td>
          <td>{item.enabled_at or "未启用"}</td>
          <td>{"一致" if bound else "配置不一致"}</td>
          <td><code>{escape(profile.strategy_id)}</code></td>
        </tr>
            """.strip()
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
      <div class="table-wrap">
        <table class="management-table" data-catalog="strategies">
          <thead><tr><th>策略</th><th>标的</th><th>版本</th><th>状态</th><th>期限</th><th>验证</th><th>启用时间</th><th>配置</th><th>算法</th></tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
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
            "候选初筛",
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
    elif item.category in {"选择报告", "候选初筛"}:
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
