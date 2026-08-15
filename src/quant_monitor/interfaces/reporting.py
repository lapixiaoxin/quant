"""Markdown 基础报告渲染与数据包校验。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

CURRENT_SCHEMA_VERSION = 3


def _validate_schema(packet: dict[str, Any]) -> None:
    version = packet.get("schema_version")
    if version != CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"不支持的数据包版本 {version!r}，"
            f"当前要求 schema_version={CURRENT_SCHEMA_VERSION}"
        )


def instrument_view(packet: dict[str, Any]) -> dict[str, Any]:
    """读取并校验标的信息。"""

    _validate_schema(packet)
    instrument = packet.get("instrument")
    if not isinstance(instrument, dict):
        raise ValueError("数据包缺少 instrument 信息")
    return instrument


def assessments_view(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """读取并校验策略判断列表。"""

    _validate_schema(packet)
    assessments = packet.get("assessments")
    if (
        isinstance(assessments, list)
        and assessments
        and all(isinstance(item, dict) for item in assessments)
    ):
        return assessments
    raise ValueError("数据包缺少 assessments 信息")


def _pct(value: float | None) -> str:
    return "暂无" if value is None else f"{value * 100:.2f}%"


def _money(value: float | None) -> str:
    if value is None:
        return "暂无"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿元"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万元"
    return f"{value:.2f}元"


def build_base_report(packet: dict[str, Any]) -> str:
    """从确定性数据包生成不依赖大模型的基础研究报告。"""

    instrument = instrument_view(packet)
    quote = packet["quote"]
    metrics = packet["metrics"]
    portfolio = packet["portfolio"]
    assessments = assessments_view(packet)
    mas = metrics["moving_averages"]
    drawdowns = metrics["drawdowns"]
    returns = metrics["returns"]

    lines = [
        f"# {instrument['name']}（{instrument['symbol']}）盘中决策简报",
        "",
        f"> 采集时间：{packet['as_of']}；"
        f"行情交易日：{metrics['latest_trading_date']}",
        "",
        "## 当前判断",
        "",
        f"- 趋势状态：**{metrics['trend_state']}**",
    ]
    for assessment in assessments:
        name = assessment.get("name", assessment.get("id", "未标注"))
        lines.append(
            f"- {name}：**{assessment['level']}**"
            f"（规则分 {assessment['score']}/100）"
        )
        lines.extend(f"  - 依据：{reason}" for reason in assessment["reasons"])
    lines.extend(
        [
            "",
            "## 行情与趋势",
            "",
            f"- 当前价格：{quote.get('price') or '暂无'}",
            f"- 当日涨跌：{_pct(quote.get('change_pct'))}",
            f"- 5/20/60 日收益：{_pct(returns['5d'])} / "
            f"{_pct(returns['20d'])} / {_pct(returns['60d'])}",
            f"- MA20/MA60/MA120：{mas['ma20']} / {mas['ma60']} / "
            f"{mas['ma120']}",
            f"- 20/60/120 日高点回撤："
            f"{_pct(drawdowns['from_high_20d'])} / "
            f"{_pct(drawdowns['from_high_60d'])} / "
            f"{_pct(drawdowns['from_high_120d'])}",
            f"- 20 日年化波动率："
            f"{_pct(metrics['risk']['annualized_volatility_20d'])}",
            f"- 当前成交额：{_money(quote.get('amount'))}",
        ]
    )
    tracking_index = instrument.get("tracking_index")
    if tracking_index:
        lines.extend(
            [
                "",
                "## 标的信息",
                "",
                f"- 跟踪指数：{tracking_index}"
                f"（{instrument.get('tracking_index_code', '暂无代码')}）",
                "- 基本面、估值、成分变化与市场环境由研究代理联网补充。",
            ]
        )
    research_plan = packet.get("research_plan", {})
    if research_plan:
        lines.extend(
            [
                "",
                "## 后续研究计划",
                "",
                f"- 研究画像：{research_plan.get('profile_id', '未标注')}",
                f"- 报告章节：{'、'.join(research_plan.get('sections', []))}",
            ]
        )
        lines.extend(
            f"- 重点关注：{item}"
            for item in research_plan.get("focus", [])
        )
    if portfolio.get("enabled"):
        market_price = quote.get("price")
        average_cost = portfolio.get("average_cost", 0)
        position_return = (
            market_price / average_cost - 1
            if market_price is not None and average_cost > 0
            else None
        )
        lines.extend(
            [
                "",
                "## 持仓上下文",
                "",
                f"- 持有份额：{portfolio['shares']:.2f}",
                f"- 平均成本：{average_cost:.4f}",
                f"- 持仓收益：{_pct(position_return)}",
                f"- 计划总投入：{_money(portfolio['planned_total_amount'])}",
            ]
        )
    lines.extend(
        [
            "",
            "## 数据质量",
            "",
            f"- 行情来源：{packet['data_quality']['market_source']}",
            f"- 行情时间戳："
            f"{packet['data_quality'].get('market_timestamp') or '未提供'}",
            f"- 历史样本：{packet['data_quality']['history_bars']} 个交易日",
            f"- 生成时间：{datetime.fromisoformat(packet['as_of']).isoformat()}",
            "- 本报告是监控与研究材料，不构成收益承诺或自动交易指令。",
        ]
    )
    return "\n".join(lines) + "\n"
