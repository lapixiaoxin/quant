"""数据层：AKShare 采集 + 本地 Parquet 缓存。"""

from .akshare_source import fetch_daily, get_daily, load_universe, normalize_daily
from .bulk import SyncResult, coverage_summary, read_meta, sync_symbols
from .etf_source import (
    fetch_etf_daily,
    fetch_etf_snapshot,
    get_etf_daily,
    load_etf_universe,
)
from .store import ParquetStore

__all__ = [
    "ParquetStore",
    "SyncResult",
    "coverage_summary",
    "fetch_daily",
    "fetch_etf_daily",
    "fetch_etf_snapshot",
    "get_daily",
    "get_etf_daily",
    "load_etf_universe",
    "load_universe",
    "normalize_daily",
    "read_meta",
    "sync_symbols",
]
