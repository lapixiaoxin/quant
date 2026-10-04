"""独立子账户组合：不互借资金，不按收盘结果决定当天开仓。"""

from __future__ import annotations

import math
import statistics
from dataclasses import replace
from datetime import date

from ..models import DailyBar
from .swing import CashPoint, SwingResult


def prior_holding_dates(result: SwingResult) -> frozenset[date]:
    """前日收盘仍有主仓，才允许本日的第二批限价单。"""
    return frozenset(
        current.trading_date
        for previous, current in zip(result.curve, result.curve[1:])
        if previous.shares > 0
    )


def combine_sleeves(
    results: dict[str, SwingResult],
    budgets: dict[str, float],
    bars: tuple[DailyBar, ...],
    initial_cash: float,
) -> SwingResult:
    """保留现金只计一次；任一子账户无法清算时拒绝输出完成结果。"""
    if not results or results.keys() != budgets.keys():
        raise ValueError("子账户结果与预算必须非空且一一对应")
    if not math.isfinite(initial_cash) or initial_cash <= 0 or any(
        not math.isfinite(value) or value <= 0 for value in budgets.values()
    ):
        raise ValueError("组合与子账户预算必须是有限正数")
    reserve = initial_cash - sum(budgets.values())
    if reserve < -1e-7:
        raise ValueError("子账户预算合计超过总资金")
    reserve = max(0.0, reserve)
    dates = tuple(point.trading_date for point in next(iter(results.values())).curve)
    if len(dates) < 2 or list(dates) != sorted(set(dates)):
        raise ValueError("组合日期必须严格升序且至少两日")
    closes = {bar.trading_date: bar.close for bar in bars}
    for name, result in results.items():
        if tuple(point.trading_date for point in result.curve) != dates:
            raise ValueError(f"子账户 {name} 的交易日期不一致")
        if result.curve[-1].shares or result.metrics["open_shares"]:
            raise ValueError(f"子账户 {name} 期末未能清算，不得作为完整收益")
        for point in result.curve:
            if (
                point.trading_date not in closes
                or not math.isfinite(point.cash) or point.cash < -1e-7
                or not math.isfinite(point.equity) or point.equity <= 0
                or point.shares < 0 or point.shares % 100
            ):
                raise ValueError(f"子账户 {name} 的现金、持仓或估值无效")
            expected = point.cash + point.shares * closes[point.trading_date]
            if not math.isclose(point.equity, expected, abs_tol=1e-6):
                raise ValueError(f"子账户 {name} 的权益不守恒")
        expected_end = budgets[name] + sum(
            fill.net_pnl for fill in result.fills if fill.side == "sell"
        )
        if not math.isclose(result.curve[-1].equity, expected_end, abs_tol=1e-6):
            raise ValueError(f"子账户 {name} 的初始预算与逐笔盈亏不守恒")
    curve = []
    for index, day in enumerate(dates):
        cash = reserve + sum(result.curve[index].cash for result in results.values())
        shares = sum(result.curve[index].shares for result in results.values())
        equity = cash + shares * closes[day]
        curve.append(CashPoint(
            day, equity, cash, shares, shares * closes[day] / equity,
        ))
    # 同日子账户之间没有资金转移，顺序仅用于审计展示。
    fills = tuple(sorted(
        (
            replace(fill, sleeve=name)
            for name, result in results.items() for fill in result.fills
        ),
        key=lambda fill: (fill.trading_date, fill.sleeve, fill.side),
    ))
    values = [initial_cash] + [point.equity for point in curve]
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    peak, drawdown = initial_cash, 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    closed = [fill for fill in fills if fill.side == "sell"]
    metrics = dict(
        total_return=values[-1] / initial_cash - 1,
        net_profit_yuan=values[-1] - initial_cash,
        max_drawdown=drawdown,
        annualized_volatility=statistics.stdev(returns) * math.sqrt(242),
        average_weight=statistics.fmean(point.weight for point in curve),
        max_weight=max(point.weight for point in curve),
        trade_count=len(fills), completed_rounds=len(closed),
        win_rate=(
            sum(fill.net_pnl > 0 for fill in closed) / len(closed) if closed else None
        ),
        average_holding_days=(
            statistics.fmean(fill.holding_days for fill in closed) if closed else None
        ),
        fees_yuan=sum(fill.fee for fill in fills),
        net_dividends_yuan=sum(
            result.metrics["net_dividends_yuan"] for result in results.values()
        ),
        turnover=sum(fill.quantity * fill.price for fill in fills) / initial_cash,
        ending_equity_yuan=values[-1], open_shares=curve[-1].shares,
        reserve_cash_yuan=reserve,
        blocked_sale_shock_10pct=-max(point.weight for point in curve) * 0.10,
        blocked_sale_shock_19pct=-max(point.weight for point in curve) * 0.19,
    )
    diagnostics = {
        key: sum(result.diagnostics.get(key, 0) for result in results.values())
        for key in set().union(*(result.diagnostics for result in results.values()))
    }
    return SwingResult(metrics, tuple(curve), fills, diagnostics)
