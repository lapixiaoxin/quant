from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from quant_monitor.domain.models import (
    DailyBar,
    Instrument,
    InstrumentType,
    MarketBundle,
    MarketQuote,
)
from quant_monitor.infrastructure.history import SQLiteMarketHistoryRepository


def instrument() -> Instrument:
    return Instrument(
        symbol="000300",
        name="沪深300",
        exchange="SH",
        instrument_type=InstrumentType.INDEX,
        strategy_profile_ids=("index_default",),
        research_profile_id="index_core",
        notification_policy_id="silent",
        history_days=500,
    )


def bundle(source: str, *, amount: float, last_close: float) -> MarketBundle:
    bars = (
        DailyBar(
            trading_date=date(2026, 8, 13),
            open=4.0,
            close=4.1,
            high=4.2,
            low=3.9,
            volume=100,
            amount=amount,
            amplitude_pct=7.0,
            change_pct=2.5,
            turnover_pct=1.2 if amount else 0,
        ),
        DailyBar(
            trading_date=date(2026, 8, 14),
            open=4.1,
            close=last_close,
            high=4.3,
            low=4.0,
            volume=120,
            amount=amount,
            amplitude_pct=7.5,
            change_pct=1.0,
            turnover_pct=1.3 if amount else 0,
        ),
    )
    quote = MarketQuote(
        symbol="000300",
        name="沪深300",
        price=last_close,
        high=4.3,
        low=4.0,
        open=4.1,
        previous_close=4.1,
        volume=120,
        amount=amount,
        total_market_value=0,
        circulating_market_value=0,
        change_pct=0.01,
        amplitude_pct=0.075,
        price_precision=2,
    )
    return MarketBundle(quote=quote, bars=bars, source=source)


class SQLiteMarketHistoryRepositoryTest(unittest.TestCase):
    def test_rejects_database_from_newer_program_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            SQLiteMarketHistoryRepository(path)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    INSERT INTO schema_migrations (version, applied_at)
                    VALUES (2, '2026-08-15T00:00:00+00:00')
                    """
                )

            with self.assertRaisesRegex(RuntimeError, "高于当前程序"):
                SQLiteMarketHistoryRepository(path)

    def test_upsert_is_idempotent_and_preserves_richer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteMarketHistoryRepository(
                Path(directory) / "history.sqlite3"
            )
            fetched_at = datetime(2026, 8, 15, tzinfo=timezone.utc)

            repository.save_bundle(
                instrument(),
                bundle("完整源", amount=1_000_000, last_close=4.2),
                fetched_at,
            )
            repository.save_bundle(
                instrument(),
                bundle("降级源", amount=0, last_close=4.25),
                fetched_at,
            )

            bars = repository.load_bars("000300")
            summary = repository.summarize("000300")

            self.assertEqual(len(bars), 2)
            self.assertEqual(bars[-1].close, 4.25)
            self.assertEqual(bars[-1].amount, 1_000_000)
            self.assertEqual(bars[-1].turnover_pct, 1.3)
            self.assertEqual(summary.bar_count, 2)
            self.assertEqual(summary.first_date, date(2026, 8, 13))
            self.assertEqual(summary.last_source, "降级源")

    def test_limit_returns_latest_bars_in_ascending_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteMarketHistoryRepository(
                Path(directory) / "history.sqlite3"
            )
            repository.save_bundle(
                instrument(),
                bundle("测试源", amount=1, last_close=4.2),
                datetime(2026, 8, 15, tzinfo=timezone.utc),
            )

            bars = repository.load_bars("000300", limit=1)

            self.assertEqual(
                [item.trading_date for item in bars],
                [date(2026, 8, 14)],
            )


if __name__ == "__main__":
    unittest.main()
