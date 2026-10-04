"""研究快照的只读历史仓储；不向日常行情主库写入不完整数据。"""

from __future__ import annotations

import csv
import hashlib
import math
from datetime import date, datetime
from pathlib import Path

from ..domain.models import (
    DailyBar,
    HistorySummary,
    Instrument,
    MarketBundle,
    ValuationObservation,
)


class FrozenCSVHistoryRepository:
    """以已冻结 SHA256 的不复权 CSV 实现历史仓储契约。"""

    def __init__(self, path: Path, symbol: str, sha256: str) -> None:
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            raise ValueError("冻结行情 SHA256 不一致，拒绝回测")
        self._symbol = symbol
        self._bars = []
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    self._bars.append(DailyBar(
                        trading_date=date.fromisoformat(row["date"]),
                        open=float(row["raw_open_yuan"]),
                        close=float(row["raw_close_yuan"]),
                        high=float(row["raw_high_yuan"]),
                        low=float(row["raw_low_yuan"]),
                        volume=float(row["volume_lots"]) * 100,
                        amount=math.nan, amplitude_pct=math.nan,
                        change_pct=math.nan, turnover_pct=math.nan,
                    ))
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError("冻结行情 CSV 字段缺失或格式无效") from error
        if not self._bars:
            raise ValueError("冻结行情 CSV 为空")

    def load_bars(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
    ) -> tuple[DailyBar, ...]:
        if symbol != self._symbol:
            raise ValueError("冻结快照不包含请求的标的")
        if limit is not None and limit <= 0:
            raise ValueError("日线条数限制必须为正数")
        bars = tuple(
            bar for bar in self._bars
            if (start_date is None or bar.trading_date >= start_date)
            and (end_date is None or bar.trading_date <= end_date)
        )
        return bars[-limit:] if limit else bars

    def summarize(self, symbol: str) -> HistorySummary:
        bars = self.load_bars(symbol)
        return HistorySummary(
            symbol, len(bars), bars[0].trading_date, bars[-1].trading_date,
            "冻结 CSV：不复权，成交额及换手率缺失", None,
        )

    def save_bundle(
        self, instrument: Instrument, bundle: MarketBundle, fetched_at: datetime,
    ) -> None:
        raise ValueError("冻结研究仓储不允许写入行情")

    def save_valuation_observations(
        self,
        observations: tuple[ValuationObservation, ...],
        fetched_at: datetime,
    ) -> None:
        raise ValueError("冻结研究仓储不允许写入估值")

    def load_valuation_observations(
        self,
        valuation_symbol: str,
        *,
        metric: str,
        weighting: str,
        history_window: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[ValuationObservation, ...]:
        raise ValueError("价格研究快照没有历史估值，拒绝替代估值回测")
