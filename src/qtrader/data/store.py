"""本地行情存储：按标的分文件缓存为 Parquet。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


class ParquetStore:
    """极简 Parquet 缓存，避免每次回测都联网重抓。

    缓存按 ``adjust`` 分文件，不同复权口径互不覆盖。
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path(self, symbol: str, freq: str = "1d", adjust: str = "") -> Path:
        """缓存路径。``adjust`` 为空时沿用 ``{symbol}.parquet``，否则追加复权标记。"""
        name = f"{symbol}.parquet" if not adjust else f"{symbol}.{adjust}.parquet"
        return self.root / "bars" / freq / name

    def has(self, symbol: str, freq: str = "1d", adjust: str = "") -> bool:
        return self.path(symbol, freq, adjust).exists()

    def save(self, symbol: str, df: pd.DataFrame, freq: str = "1d", adjust: str = "") -> Path:
        target = self.path(symbol, freq, adjust)
        target.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(target, index=False)
        return target

    def load(self, symbol: str, freq: str = "1d", adjust: str = "") -> Optional[pd.DataFrame]:
        target = self.path(symbol, freq, adjust)
        if not target.exists():
            return None
        return pd.read_parquet(target)
