"""数据层：AKShare 采集 + 本地 Parquet 缓存。"""

from .akshare_source import fetch_daily, get_daily, load_universe, normalize_daily
from .store import ParquetStore

__all__ = [
    "ParquetStore",
    "fetch_daily",
    "get_daily",
    "load_universe",
    "normalize_daily",
]
