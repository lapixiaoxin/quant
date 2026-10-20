"""AKShare 数据源：抓取日线并归一为 AKQuant 可用的规范列。

AKQuant 的 ``dataframe_to_bars`` 需要 ``date/open/high/low/close/volume`` 六列，
AKShare ``stock_zh_a_daily`` 的原生列名恰好一致，这里只做清洗与排序。

复权口径由 ``adjust`` 参数控制，默认 ``""``（不复权）。高分红标的回测请显式传
``"qfq"``，否则除权除息跳空会导致收益被低估、回撤被高估。
"""

from __future__ import annotations

import pandas as pd

from ..settings import get_settings
from .store import ParquetStore

CANONICAL = ["date", "open", "high", "low", "close", "volume"]


def normalize_daily(df: pd.DataFrame) -> pd.DataFrame:
    """裁剪为标准列、按日期升序、去重。"""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out[CANONICAL]
    out = out.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return out


def fetch_daily(symbol: str, start: str, end: str, adjust: str = "") -> pd.DataFrame:
    """联网抓取单只标的日线。``symbol`` 用 AKShare 口径，如 ``sh600000``。

    :param adjust: 复权方式，``""`` 不复权 / ``"qfq"`` 前复权 / ``"hfq"`` 后复权。
    """
    import akshare as ak

    raw = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end, adjust=adjust)
    return normalize_daily(raw)


def get_daily(
    symbol: str,
    start: str,
    end: str,
    refresh: bool = False,
    adjust: str = "",
) -> pd.DataFrame:
    """读取日线：优先本地缓存，缺失或 ``refresh`` 时联网抓取并落盘。

    缓存按 ``adjust`` 分文件存放，不同复权口径互不覆盖。
    """
    store = ParquetStore(get_settings().data_dir)
    cached = None if refresh else store.load(symbol, adjust=adjust)
    if cached is not None:
        window = cached[(cached["date"] >= pd.Timestamp(start)) & (cached["date"] <= pd.Timestamp(end))]
        if not window.empty:
            return window.reset_index(drop=True)
    fresh = fetch_daily(symbol, start, end, adjust=adjust)
    store.save(symbol, fresh, adjust=adjust)
    return fresh


def load_universe(
    symbols: list[str],
    start: str,
    end: str,
    refresh: bool = False,
    adjust: str = "",
) -> dict[str, pd.DataFrame]:
    """批量读取，返回 ``{symbol: df}``，可直接喂给 ``run_backtest``。"""
    return {s: get_daily(s, start, end, refresh=refresh, adjust=adjust) for s in symbols}
