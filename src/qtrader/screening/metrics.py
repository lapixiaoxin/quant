"""波段筛选指标：把"适合做波段"翻译成可计算的量。

所有指标只依赖行情序列，不引入任何未来函数；窗口由调用方通过传入的
``DataFrame`` 决定（通常是最近 N 年的前复权日线）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def annualized_volatility(returns: pd.Series) -> float:
    """年化波动率。"""
    if len(returns) < 2:
        return float("nan")
    return float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS))


def max_drawdown(close: pd.Series) -> float:
    """最大回撤，负值。"""
    if len(close) < 2:
        return float("nan")
    cum = close / close.iloc[0]
    return float((cum / cum.cummax() - 1).min())


def longest_underwater_days(close: pd.Series) -> int:
    """最长水下交易日数：未回到前高的最长连续天数。"""
    if len(close) < 2:
        return 0
    cum = close / close.iloc[0]
    peak = cum.cummax()
    under = (cum < peak * 0.999).to_numpy()
    longest = run = 0
    for flag in under:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return int(longest)


def daily_amplitude(df: pd.DataFrame) -> pd.Series:
    """日内振幅 ``(最高 - 最低) / 前收``。"""
    return ((df["high"] - df["low"]) / df["close"].shift(1)).dropna()


def zigzag_swings(close: pd.Series, threshold: float = 0.15) -> list[float]:
    """阈值 zigzag，返回每段波段涨跌幅。

    只有相对拐点涨跌超过 ``threshold`` 才确认拐点，用于统计"值得做的波段"。
    """
    values = close.to_numpy(dtype=float)
    if len(values) < 3:
        return []

    pivots: list[int] = [0]
    direction = 0
    last = values[0]
    for i in range(1, len(values)):
        change = values[i] / last - 1
        if direction == 0:
            if change >= threshold:
                direction, last = 1, values[i]
                pivots.append(i)
            elif change <= -threshold:
                direction, last = -1, values[i]
                pivots.append(i)
        elif direction == 1:
            if values[i] > last:
                last = values[i]
                pivots[-1] = i
            elif change <= -threshold:
                direction, last = -1, values[i]
                pivots.append(i)
        else:
            if values[i] < last:
                last = values[i]
                pivots[-1] = i
            elif change >= threshold:
                direction, last = 1, values[i]
                pivots.append(i)

    return [values[pivots[i + 1]] / values[pivots[i]] - 1 for i in range(len(pivots) - 1)]


def swing_metrics(df: pd.DataFrame, threshold: float = 0.15, high_window: int = 250) -> dict[str, float]:
    """计算单个标的的波段相关指标。

    :param df: 行情 DataFrame，需含 ``date/open/high/low/close`` 且按日期升序。
    :param threshold: zigzag 拐点阈值，默认 15%。
    :param high_window: 计算"距 52 周高点"所用的最近交易日数。
    """
    data = df.reset_index(drop=True)
    close = data["close"].astype(float)
    returns = close.pct_change().dropna()
    years = max(len(returns) / TRADING_DAYS, 1e-9)

    swings = zigzag_swings(close, threshold=threshold)
    amplitude = daily_amplitude(data)

    recent = close.tail(high_window)
    distance_from_high = float(recent.iloc[-1] / recent.max() - 1) if len(recent) > 1 else float("nan")

    variance_ratio = float("nan")
    if len(returns) > 10:
        variance_ratio = float(returns.rolling(5).sum().var() / (5 * returns.var()))

    return {
        "bars": float(len(data)),
        "annual_volatility": annualized_volatility(returns),
        "median_daily_amplitude": float(amplitude.median()) if len(amplitude) else float("nan"),
        "swing_count": float(len(swings)),
        "swings_per_year": float(len(swings) / years),
        "avg_swing_amplitude": float(np.mean([abs(s) for s in swings])) if swings else float("nan"),
        "autocorr_1d": float(returns.autocorr(1)) if len(returns) > 2 else float("nan"),
        "variance_ratio_5": variance_ratio,
        "max_drawdown": max_drawdown(close),
        "longest_underwater_days": float(longest_underwater_days(close)),
        "distance_from_52w_high": distance_from_high,
    }
