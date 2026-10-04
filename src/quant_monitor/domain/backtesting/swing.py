"""可复现的现金股票日线研究：前日信号、整手、T+1 与保守撮合。"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from ..models import DailyBar, Instrument
from .models import BacktestSignal


@dataclass(frozen=True)
class CashDividend:
    ex_date: date
    per_share: float
    source: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.per_share) or self.per_share <= 0:
            raise ValueError("现金分红必须为有限正数")
        if not self.source:
            raise ValueError("现金分红必须有可追溯来源")


@dataclass(frozen=True)
class ExecutionCosts:
    slippage_yuan: float = 0.01
    commission_rate: float = 0.0003
    minimum_commission_yuan: float = 5.0
    transfer_rate: float = 0.00001
    sell_stamp_rate: float = 0.0005
    dividend_tax_rate: float = 0.20

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(value) or value < 0
            for value in self.__dict__.values()
        ) or self.dividend_tax_rate > 1:
            raise ValueError("费用必须是有限非负数，股息税率不能超过 1")

    def fee(self, quantity: int, price: float, *, sell: bool) -> float:
        """佣金和税费合计，单位元。"""
        notional = quantity * price
        return (
            max(self.minimum_commission_yuan, notional * self.commission_rate)
            + notional * (self.transfer_rate + (self.sell_stamp_rate if sell else 0))
        )


@dataclass(frozen=True)
class SwingSignal(BacktestSignal):
    entry_limit: float | None
    take_distance: float
    stop_distance: float
    exit_core: bool


class PriceSwingModel:
    """单一版本下注册的固定价、ATR 回归、原草案和买持对照。"""

    model_id = "cash_equity_swing"
    model_version = "1.0.0"
    minimum_bars = 70
    modes = {"fixed", "atr", "previous", "hold"}

    def validate_parameters(self, parameters: dict[str, Any]) -> None:
        allowed = {
            "mode", "weight", "core_weight", "risk_fraction", "entry",
            "take", "stop", "pullback_atr", "take_atr", "max_hold", "trend",
        }
        if set(parameters) - allowed:
            raise ValueError("波段参数包含未知字段")
        if parameters.get("mode") not in self.modes:
            raise ValueError("未注册的现金股票研究模型")
        for key, value in parameters.items():
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError(f"波段参数 {key} 必须是有限数")
        weight = parameters.get("weight", 0.4)
        core = parameters.get("core_weight", 0.0)
        if not 0 < weight <= 1 or not 0 <= core <= 1 or weight + core > 1:
            raise ValueError("波段与底仓仓位必须在 0 至 1 内且合计不超过 1")
        if not 0 < parameters.get("risk_fraction", 0.005) <= 1:
            raise ValueError("单轮风险比例必须在 0 至 1 内")
        hold = parameters.get("max_hold", 20)
        if isinstance(hold, bool) or not isinstance(hold, int) or hold < 1:
            raise ValueError("持有期限必须是正整数交易日")
        if not isinstance(parameters.get("trend", False), bool):
            raise ValueError("趋势过滤必须是布尔值")
        for key in ("entry", "take", "stop", "pullback_atr", "take_atr"):
            if key in parameters and parameters[key] <= 0:
                raise ValueError(f"波段参数 {key} 必须为正数")

    def generate_signal(
        self,
        instrument: Instrument,
        history: Sequence[DailyBar],
        parameters: dict[str, Any],
    ) -> SwingSignal:
        if len(history) < self.minimum_bars:
            raise ValueError("波段信号需要至少 70 根已完成日线")
        last = history[-1]
        ma60 = statistics.fmean(item.close for item in history[-60:])
        previous_ma = statistics.fmean(item.close for item in history[-61:-1])
        slope_ok = ma60 >= statistics.fmean(
            item.close for item in history[-70:-10]
        )
        exit_core = last.close < ma60 and history[-2].close < previous_ma
        mode = parameters["mode"]
        entry: float | None = float(parameters.get("entry", 8.70))
        take = float(parameters.get("take", 0.30))
        stop = float(parameters.get("stop", 0.20))
        reason = "固定限价"
        if mode == "atr":
            atr = statistics.fmean(
                max(
                    history[i].high - history[i].low,
                    abs(history[i].high - history[i - 1].close),
                    abs(history[i].low - history[i - 1].close),
                )
                for i in range(len(history) - 14, len(history))
            )
            entry = statistics.fmean(item.close for item in history[-20:])
            entry -= parameters.get("pullback_atr", 1.0) * atr
            take = parameters.get("take_atr", 2.0) * atr
            stop = 1.5 * atr
            if atr <= 0:
                entry = None
            reason = "均线回归限价"
        elif mode == "previous":
            entry = 8.75 if (
                last.low <= 8.75 and last.high >= 8.70
                and last.close > history[-2].high and slope_ok
            ) else None
            take, stop = 0.30, 0.20
            reason = "原 v0.1 反转确认"
        elif mode == "hold":
            take, stop = 0.0, 0.0
            reason = "买入持有对照"
        if parameters.get("trend", False) and not slope_ok:
            entry = None
        if entry is not None:
            entry = math.floor((entry + 1e-9) * 100) / 100
        return SwingSignal(
            last.trading_date, float(parameters.get("weight", 0.4)),
            reason, entry, take, stop, exit_core,
        )


@dataclass(frozen=True)
class Fill:
    trading_date: date
    side: str
    sleeve: str
    quantity: int
    price: float
    fee: float
    reason: str
    net_pnl: float | None = None
    holding_days: int | None = None


@dataclass(frozen=True)
class CashPoint:
    trading_date: date
    equity: float
    cash: float
    shares: int
    weight: float


@dataclass(frozen=True)
class SwingResult:
    metrics: dict[str, Any]
    curve: tuple[CashPoint, ...]
    fills: tuple[Fill, ...]
    diagnostics: dict[str, int]


@dataclass
class _Lot:
    sleeve: str
    quantity: int
    entry_index: int
    entry_price: float
    entry_fee: float
    stop: float
    take: float | None
    dividends: float = 0.0
    pending_stop: bool = False


def adjusted_signal_window(
    bars: Sequence[DailyBar], dividends: Sequence[CashDividend],
) -> tuple[DailyBar, ...]:
    """仅消除信号时点已经发生的现金除息，不读取未来复权因子。"""
    end = bars[-1].trading_date
    result = []
    for bar in bars[-70:]:
        adjustment = sum(
            item.per_share for item in dividends
            if bar.trading_date < item.ex_date <= end
        )
        result.append(replace(
            bar, open=bar.open - adjustment, close=bar.close - adjustment,
            high=bar.high - adjustment, low=bar.low - adjustment,
        ))
    return tuple(result)


def _market_price(bar: DailyBar, price: float, slippage: float) -> float:
    return round(min(bar.high, max(bar.low, price + slippage)), 2)


def simulate_swing(
    instrument: Instrument,
    bars: tuple[DailyBar, ...],
    start: date,
    end: date,
    parameters: dict[str, Any],
    *,
    dividends: tuple[CashDividend, ...] = (),
    costs: ExecutionCosts | None = None,
    initial_cash: float = 100_000.0,
    allowed_entry_dates: frozenset[date] | None = None,
) -> SwingResult:
    """纯函数；所有行情、日期、参数与费用由调用者显式提供。"""
    costs = costs or ExecutionCosts()
    model = PriceSwingModel()
    model.validate_parameters(parameters)
    if start > end or not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("回测日期或初始现金无效")
    dates = [bar.trading_date for bar in bars]
    if dates != sorted(set(dates)):
        raise ValueError("日线必须日期唯一且严格升序")
    for bar in bars:
        values = (bar.open, bar.close, bar.high, bar.low, bar.volume)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("日线包含非有限数")
        if not (
            0 < bar.low <= min(bar.open, bar.close)
            <= max(bar.open, bar.close) <= bar.high and bar.volume >= 0
        ):
            raise ValueError("日线 OHLC 或成交量不合法")
    actions = {item.ex_date: item.per_share for item in dividends}
    if len(actions) != len(dividends):
        raise ValueError("现金分红日期重复")
    indices = [i for i, bar in enumerate(bars) if start <= bar.trading_date <= end]
    if len(indices) < 2 or indices[0] < model.minimum_bars:
        raise ValueError("回测至少需要 2 日样本和此前 70 日预热")
    if any(start <= day <= end and day not in dates for day in actions):
        raise ValueError("区间内现金分红日在行情中缺失")

    cash = initial_cash
    lots: list[_Lot] = []
    fills: list[Fill] = []
    curve: list[CashPoint] = []
    loss_streak = 0
    cooldown_until = -1
    diagnostics = dict(
        entry_orders=0, unfilled_orders=0, unaffordable_orders=0,
        double_touch=0, t1_stop=0, blocked_days=0, cooldown_days=0,
    )
    net_dividends = 0.0
    mode = parameters["mode"]
    core_weight = float(parameters.get("core_weight", 0.0))

    for index in indices:
        bar = bars[index]
        last_day = index == indices[-1]
        tradable = bar.volume > 0 and bar.high > bar.low
        dividend = actions.get(bar.trading_date, 0.0)
        if dividend:
            for lot in lots:
                income = lot.quantity * dividend * (1 - costs.dividend_tax_rate)
                cash += income
                net_dividends += income
                lot.dividends += income
                if mode != "hold":
                    lot.stop -= dividend
                    if lot.take is not None:
                        lot.take -= dividend
        signal = model.generate_signal(
            instrument, adjusted_signal_window(bars[:index], dividends), parameters,
        )
        exited = False
        for lot in tuple(lots):
            age = index - lot.entry_index
            stop_hit = mode != "hold" and bar.low <= lot.stop
            if not tradable:
                lot.pending_stop = lot.pending_stop or stop_hit
                continue
            price: float | None = None
            reason = ""
            if lot.pending_stop or (mode != "hold" and bar.open <= lot.stop):
                price = _market_price(bar, bar.open, -costs.slippage_yuan)
                reason = "延迟止损" if lot.pending_stop else "跳空止损"
            elif lot.sleeve == "core" and signal.exit_core:
                price = _market_price(bar, bar.open, -costs.slippage_yuan)
                reason = "底仓均线退出"
            elif lot.take is not None and bar.open >= lot.take:
                price = max(
                    lot.take, _market_price(bar, bar.open, -costs.slippage_yuan),
                )
                reason = "开盘止盈"
            else:
                take_hit = lot.take is not None and (
                    bar.high >= lot.take + costs.slippage_yuan - 1e-9
                )
                if stop_hit:
                    diagnostics["double_touch"] += int(take_hit)
                    price = _market_price(bar, lot.stop, -costs.slippage_yuan)
                    reason = "双触止损" if take_hit else "止损"
                elif take_hit:
                    price, reason = lot.take, "止盈"
                elif (
                    mode != "hold" and lot.sleeve == "swing"
                    and age >= parameters.get("max_hold", 20)
                ):
                    price = _market_price(bar, bar.close, -costs.slippage_yuan)
                    reason = "时间退出"
                elif last_day:
                    price = _market_price(bar, bar.close, -costs.slippage_yuan)
                    reason = "样本结束清算"
            if price is None:
                continue
            fee = costs.fee(lot.quantity, price, sell=True)
            cash += lot.quantity * price - fee
            pnl = (
                lot.quantity * (price - lot.entry_price)
                - lot.entry_fee - fee + lot.dividends
            )
            fills.append(Fill(
                bar.trading_date, "sell", lot.sleeve, lot.quantity, price,
                fee, reason, pnl, age,
            ))
            lots.remove(lot)
            exited = True
            if lot.sleeve == "swing" and mode != "hold":
                loss_streak = loss_streak + 1 if pnl < 0 else 0
                if loss_streak >= 2:
                    cooldown_until, loss_streak = index + 10, 0

        if not tradable:
            diagnostics["blocked_days"] += 1
        cooling = index <= cooldown_until
        diagnostics["cooldown_days"] += int(cooling)
        can_enter = (
            not last_day and not exited and tradable and not dividend
            and not cooling and signal.entry_limit is not None
            and (
                allowed_entry_dates is None
                or bar.trading_date in allowed_entry_dates
            )
        )
        if can_enter:
            available = [("swing", signal.target_weight)]
            if core_weight:
                available.insert(0, ("core", core_weight))
            for sleeve, weight in available:
                if any(lot.sleeve == sleeve for lot in lots):
                    continue
                diagnostics["entry_orders"] += 1
                limit = signal.entry_limit
                if mode == "hold":
                    price = _market_price(bar, bar.open, costs.slippage_yuan)
                elif bar.open <= limit:
                    price = min(
                        limit, _market_price(bar, bar.open, costs.slippage_yuan),
                    )
                elif bar.low <= limit - costs.slippage_yuan + 1e-9:
                    price = limit
                else:
                    diagnostics["unfilled_orders"] += 1
                    continue
                equity = cash + sum(lot.quantity for lot in lots) * bar.open
                stop = round(max(0.01, price - signal.stop_distance), 2)
                take = (
                    round(price + signal.take_distance, 2)
                    if sleeve == "swing" and mode != "hold" else None
                )
                quantity = math.floor(min(equity * weight, cash) / price / 100) * 100
                while quantity > 0:
                    buy_fee = costs.fee(quantity, price, sell=False)
                    risk = quantity * (price - stop + costs.slippage_yuan)
                    risk += buy_fee + costs.fee(quantity, stop, sell=True)
                    affordable = quantity * price + buy_fee <= cash
                    within_risk = (
                        mode == "hold" or sleeve == "core"
                        or risk <= equity * parameters.get("risk_fraction", 0.005)
                    )
                    # 波段加仓也不能借底仓上涨突破总仓位上限。
                    total_value = (
                        sum(lot.quantity for lot in lots) * bar.open
                        + quantity * price
                    )
                    within_weight = total_value <= (
                        equity * (signal.target_weight + core_weight) + 1e-7
                    )
                    if affordable and within_risk and within_weight:
                        break
                    quantity -= 100
                if not quantity:
                    diagnostics["unaffordable_orders"] += 1
                    continue
                cash -= quantity * price + buy_fee
                lot = _Lot(sleeve, quantity, index, price, buy_fee, stop, take)
                if mode != "hold" and bar.low <= stop:
                    lot.pending_stop = True
                    diagnostics["t1_stop"] += 1
                lots.append(lot)
                fills.append(Fill(
                    bar.trading_date, "buy", sleeve, quantity, price,
                    buy_fee, signal.reason,
                ))
        shares = sum(lot.quantity for lot in lots)
        equity = cash + shares * bar.close
        curve.append(CashPoint(
            bar.trading_date, equity, cash, shares, shares * bar.close / equity,
        ))
        if cash < -1e-7:
            raise ValueError("现金账户出现负余额")

    values = [initial_cash] + [point.equity for point in curve]
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    peak, drawdown = initial_cash, 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    closed = [fill for fill in fills if fill.side == "sell"]
    volatility = statistics.stdev(returns) * math.sqrt(242)
    metrics = dict(
        total_return=values[-1] / initial_cash - 1,
        max_drawdown=drawdown, annualized_volatility=volatility,
        average_weight=statistics.fmean(point.weight for point in curve),
        max_weight=max(point.weight for point in curve),
        trade_count=len(fills), completed_rounds=len(closed),
        win_rate=(
            sum(fill.net_pnl > 0 for fill in closed) / len(closed)
            if closed else None
        ),
        average_holding_days=(
            statistics.fmean(fill.holding_days for fill in closed)
            if closed else None
        ),
        fees_yuan=sum(fill.fee for fill in fills),
        net_dividends_yuan=net_dividends,
        turnover=sum(fill.quantity * fill.price for fill in fills) / initial_cash,
        ending_equity_yuan=values[-1], open_shares=curve[-1].shares,
    )
    return SwingResult(metrics, tuple(curve), tuple(fills), diagnostics)
