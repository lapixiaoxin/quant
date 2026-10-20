"""ETF 数据源：候选池快照 + 日线历史。

ETF 与个股走不同接口：个股用 ``stock_zh_a_daily``，ETF 用
``fund_etf_category_sina``（池）与 ``fund_etf_hist_sina``（历史）。
东财的 ``fund_etf_hist_em`` 支持复权与日期区间，但部分网络下不可用，故不采用。

已知限制：新浪 ETF 历史是**不复权**价，ETF 分红会造成除息跳空。ETF 分红幅度
通常小于高分红个股，但做长周期指标时仍需知晓这一偏差。缓存单独放在
``data/etf/bars/`` 下，与个股行情隔离。
"""

from __future__ import annotations

import pandas as pd

from ..settings import get_settings
from .akshare_source import CANONICAL, normalize_daily
from .store import ParquetStore

SNAPSHOT_RENAME = {
    "代码": "symbol",
    "名称": "name",
    "成交额": "amount",
    "成交量": "volume",
    "最新价": "price",
}

NUMERIC_COLUMNS = ["amount", "volume", "price"]


def fetch_etf_snapshot() -> pd.DataFrame:
    """全市场 ETF 快照（新浪源），列名归一。"""
    import akshare as ak

    raw = ak.fund_etf_category_sina(symbol="ETF基金")
    missing = sorted(set(SNAPSHOT_RENAME) - set(raw.columns))
    if missing:
        raise RuntimeError(f"ETF 快照字段缺失，接口可能已变更: {missing}")

    out = raw[list(SNAPSHOT_RENAME)].rename(columns=SNAPSHOT_RENAME).copy()
    for col in NUMERIC_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["symbol"] = out["symbol"].astype(str)
    out["name"] = out["name"].astype(str)
    return out


def fetch_etf_daily(symbol: str) -> pd.DataFrame:
    """抓取单只 ETF 的**全部**历史日线（新浪源，不复权）。"""
    import akshare as ak

    raw = ak.fund_etf_hist_sina(symbol=symbol)
    return normalize_daily(raw)


def get_etf_daily(
    symbol: str,
    start: str,
    end: str,
    refresh: bool = False,
) -> pd.DataFrame:
    """读取 ETF 日线：优先本地缓存，缺失或 ``refresh`` 时联网抓取并落盘。

    新浪接口不接收日期区间，因此抓取全历史后按窗口裁剪。
    """
    store = ParquetStore(get_settings().data_dir / "etf")
    cached = None if refresh else store.load(symbol)
    if cached is None:
        cached = fetch_etf_daily(symbol)
        store.save(symbol, cached)

    window = cached[
        (cached["date"] >= pd.Timestamp(start)) & (cached["date"] <= pd.Timestamp(end))
    ]
    return window[CANONICAL].reset_index(drop=True)


def load_etf_universe(
    symbols: list[str],
    start: str,
    end: str,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """批量读取 ETF 日线，返回 ``{symbol: df}``。"""
    return {s: get_etf_daily(s, start, end, refresh=refresh) for s in symbols}
