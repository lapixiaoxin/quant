"""波段筛选指标：把"适合做波段"翻译成可计算的量。

指标按**周期**计算（日线或周线），周期决定了年化因子与回溯窗口：
``daily`` 用 252 个交易日/年，``weekly`` 用 52 个交易周/年。所有指标只依赖
行情序列、不含未来函数；回溯窗口由调用方传入的 ``DataFrame`` 范围决定。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# 各周期的每年根数，决定年化因子与窗口长度
PERIODS_PER_YEAR = {"daily": 252, "weekly": 52}
# 计算趋势结构（收盘站上均线占比）所用的均线长度
TREND_WINDOW = {"daily": 60, "weekly": 20}


def resample(df: pd.DataFrame, period: str = "daily") -> pd.DataFrame:
    """把日线重采样到指定周期；``daily`` 原样返回，``weekly`` 取周线。"""
    if period == "daily":
        return df.reset_index(drop=True)

    data = df.copy()
    data["date"] = pd.to_datetime(data["date"])
    weekly = (
        data.set_index("date")
        .resample("W-FRI")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    return weekly.reset_index()


def max_drawdown(close: pd.Series) -> float:
    """最大回撤，负值。"""
    if len(close) < 2:
        return float("nan")
    cum = close / close.iloc[0]
    return float((cum / cum.cummax() - 1).min())


def longest_underwater_bars(close: pd.Series) -> int:
    """最长水下根数：未回到前高的最长连续根数（日线为天，周线为周）。"""
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


def bar_amplitude(df: pd.DataFrame) -> pd.Series:
    """单根振幅 ``(最高 - 最低) / 前收``；日线即日内振幅，周线即周振幅。"""
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


def swing_metrics(
    df: pd.DataFrame,
    *,
    period: str = "daily",
    swing_threshold: float = 0.15,
) -> dict[str, float]:
    """计算单个标的的波段相关指标。

    :param df: 日线行情，需含 ``date/open/high/low/close`` 且按日期升序。
    :param period: ``daily`` 或 ``weekly``，指标在该周期上计算。
    :param swing_threshold: zigzag 拐点阈值，按周期口径给定。
    """
    if period not in PERIODS_PER_YEAR:
        raise ValueError(f"不支持的周期: {period!r}，可选 {sorted(PERIODS_PER_YEAR)}")

    data = resample(df, period)
    periods_per_year = PERIODS_PER_YEAR[period]
    close = data["close"].astype(float)
    returns = close.pct_change().dropna()
    years = max(len(returns) / periods_per_year, 1e-9)

    swings = zigzag_swings(close, threshold=swing_threshold)
    amplitude = bar_amplitude(data)

    recent = close.tail(periods_per_year)
    distance_from_high = float(recent.iloc[-1] / recent.max() - 1) if len(recent) > 1 else float("nan")

    variance_ratio = float("nan")
    if len(returns) > 10:
        variance_ratio = float(returns.rolling(5).sum().var() / (5 * returns.var()))

    moving_average = close.rolling(TREND_WINDOW[period]).mean()
    trend_ratio = float((close > moving_average).mean())

    return {
        "bars": float(len(data)),
        "annual_volatility": float(returns.std(ddof=1) * np.sqrt(periods_per_year))
        if len(returns) > 1
        else float("nan"),
        "median_amplitude": float(amplitude.median()) if len(amplitude) else float("nan"),
        "swing_count": float(len(swings)),
        "swings_per_year": float(len(swings) / years),
        "avg_swing_amplitude": float(np.mean([abs(s) for s in swings])) if swings else float("nan"),
        "autocorr_1": float(returns.autocorr(1)) if len(returns) > 2 else float("nan"),
        "variance_ratio_5": variance_ratio,
        "max_drawdown": max_drawdown(close),
        "longest_underwater_bars": float(longest_underwater_bars(close)),
        "distance_from_52w_high": distance_from_high,
        "trend_ratio": trend_ratio,
    }
