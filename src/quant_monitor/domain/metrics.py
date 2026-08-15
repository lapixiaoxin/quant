"""与具体投资策略无关的行情指标计算。"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from typing import Any

from .models import DailyBar


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def simple_return(values: Sequence[float], periods: int) -> float | None:
    if periods <= 0 or len(values) <= periods or values[-periods - 1] == 0:
        return None
    return values[-1] / values[-periods - 1] - 1


def moving_average(values: Sequence[float], periods: int) -> float | None:
    if periods <= 0 or len(values) < periods:
        return None
    return statistics.fmean(values[-periods:])


def annualized_volatility(
    values: Sequence[float], periods: int = 20
) -> float | None:
    if len(values) < periods + 1:
        return None
    window = values[-periods - 1 :]
    returns = [
        window[index] / window[index - 1] - 1
        for index in range(1, len(window))
        if window[index - 1] != 0
    ]
    if len(returns) < 2:
        return None
    return statistics.stdev(returns) * math.sqrt(242)


def drawdown_from_high(values: Sequence[float], periods: int) -> float | None:
    if not values:
        return None
    window = values[-periods:] if len(values) >= periods else values
    high = max(window)
    return None if high == 0 else values[-1] / high - 1


def max_drawdown(values: Sequence[float], periods: int) -> float | None:
    if not values:
        return None
    window = values[-periods:] if len(values) >= periods else values
    peak = window[0]
    worst = 0.0
    for value in window:
        peak = max(peak, value)
        if peak:
            worst = min(worst, value / peak - 1)
    return worst


def _trend_state(
    close: float,
    ma20: float | None,
    ma60: float | None,
    ma120: float | None,
) -> str:
    if ma20 is None or ma60 is None:
        return "数据不足"
    if ma120 is not None and close > ma20 > ma60 > ma120:
        return "强势上涨"
    if close > ma20 > ma60:
        return "温和上涨"
    if close < ma20 < ma60 and (ma120 is None or ma60 < ma120):
        return "明显下跌"
    if close < ma20 < ma60:
        return "温和下跌"
    return "震荡"


def calculate_metrics(bars: Sequence[DailyBar]) -> dict[str, Any]:
    """基于至少 20 根日线生成可复核的通用技术与流动性指标。"""

    if len(bars) < 20:
        raise ValueError("至少需要 20 根日线数据")
    closes = [bar.close for bar in bars]
    amounts = [bar.amount for bar in bars]
    volumes = [bar.volume for bar in bars]
    latest = bars[-1]

    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    ma120 = moving_average(closes, 120)
    recent_amounts = amounts[-20:]
    amount_ma20 = (
        moving_average(amounts, 20)
        if sum(value > 0 for value in recent_amounts) >= 15
        else None
    )
    volume_ma20 = moving_average(volumes, 20)
    result: dict[str, Any] = {
        "latest_trading_date": latest.trading_date.isoformat(),
        "latest_close": latest.close,
        "returns": {
            f"{period}d": _round(simple_return(closes, period))
            for period in (1, 5, 20, 60, 120, 242)
        },
        "moving_averages": {
            "ma20": _round(ma20),
            "ma60": _round(ma60),
            "ma120": _round(ma120),
            "distance_to_ma20": _round(latest.close / ma20 - 1) if ma20 else None,
            "distance_to_ma60": _round(latest.close / ma60 - 1) if ma60 else None,
            "distance_to_ma120": (
                _round(latest.close / ma120 - 1) if ma120 else None
            ),
        },
        "drawdowns": {
            f"from_high_{period}d": _round(drawdown_from_high(closes, period))
            for period in (20, 60, 120, 242)
        },
        "max_drawdowns": {
            f"{period}d": _round(max_drawdown(closes, period))
            for period in (20, 60, 120, 242)
        },
        "risk": {
            "annualized_volatility_20d": _round(
                annualized_volatility(closes, 20)
            ),
            "amplitude_latest_pct": latest.amplitude_pct,
        },
        "liquidity": {
            "latest_amount": latest.amount,
            "amount_ma20": _round(amount_ma20, 2),
            "amount_ratio_to_ma20": (
                _round(latest.amount / amount_ma20) if amount_ma20 else None
            ),
            "latest_volume": latest.volume,
            "volume_ma20": _round(volume_ma20, 2),
            "volume_ratio_to_ma20": (
                _round(latest.volume / volume_ma20) if volume_ma20 else None
            ),
        },
        "trend_state": _trend_state(latest.close, ma20, ma60, ma120),
    }
    return result
