from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from quant_monitor.application.monitoring import MonitoringService
from quant_monitor.config import load_settings
from quant_monitor.domain.models import (
    DailyBar,
    Instrument,
    MarketBundle,
    MarketQuote,
)
from quant_monitor.domain.strategies import StrategyRegistry
from quant_monitor.infrastructure.history import SQLiteMarketHistoryRepository
from quant_monitor.infrastructure.storage import FileResearchRepository
from quant_monitor.infrastructure.strategy_catalog import StrategyCatalog

CONFIG = """
[app]
data_dir = "data"
log_dir = "logs"

[product_types.etf]
strategy_profiles = ["dividend_default"]
research_profile = "etf_core"
notification_policy = "silent"
history_days = 300

[strategy_profiles.dividend_default]
strategy = "dividend_low_vol"
parameters = { attention_drawdown = -0.06 }

[research_profiles.etf_core]
skill = "instrument-analyst"
sections = ["趋势", "风险"]
focus = ["大类默认关注"]
source_priorities = ["官方来源"]
max_sources = 3
instructions = ["默认指令"]

[notification_policies.silent]
enabled = false
channels = []
events = []

[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
research_focus = ["标的个性关注"]
research_instructions = ["标的个性指令"]
"""


class FakeMarketData:
    def __init__(self, bundle: MarketBundle) -> None:
        self.bundle = bundle
        self.calls: list[tuple[str, int]] = []

    def fetch(self, instrument: Instrument, limit: int) -> MarketBundle:
        self.calls.append((instrument.symbol, limit))
        return self.bundle


class WindowedMarketData:
    def __init__(self, bundle: MarketBundle) -> None:
        self.bundle = bundle
        self.calls: list[tuple[str, int]] = []

    def fetch(self, instrument: Instrument, limit: int) -> MarketBundle:
        self.calls.append((instrument.symbol, limit))
        return MarketBundle(
            quote=self.bundle.quote,
            bars=self.bundle.bars[-limit:],
            source=self.bundle.source,
        )


def market_bundle(count: int = 30) -> MarketBundle:
    last_day = date(2026, 8, 15)
    bars = tuple(
        DailyBar(
            trading_date=last_day - timedelta(days=count - 1 - index),
            open=1 + index * 0.01,
            close=1 + index * 0.01,
            high=1.01 + index * 0.01,
            low=0.99 + index * 0.01,
            volume=1_000_000,
            amount=0 if index == count - 1 else 10_000_000,
            amplitude_pct=2.0,
            change_pct=0.5,
            turnover_pct=1.0,
        )
        for index in range(count)
    )
    quote = MarketQuote(
        symbol="510300",
        name="测试 ETF",
        price=bars[-1].close,
        high=bars[-1].high,
        low=bars[-1].low,
        open=bars[-1].open,
        previous_close=bars[-2].close,
        volume=2_000_000,
        amount=23_000_000,
        total_market_value=1_000_000_000,
        circulating_market_value=1_000_000_000,
        change_pct=0.01,
        amplitude_pct=0.02,
        price_precision=3,
        quote_time="2026-08-15 14:00:00",
    )
    return MarketBundle(quote=quote, bars=bars, source="测试行情源")


class MonitoringTest(unittest.TestCase):
    def test_prepares_schema_v5_and_persists_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text(CONFIG, encoding="utf-8")
            settings = load_settings(root, config_path)
            provider = FakeMarketData(market_bundle())
            repository = FileResearchRepository(settings.data_dir)
            history_repository = SQLiteMarketHistoryRepository(
                settings.data_dir / "history" / "market.sqlite3"
            )
            service = MonitoringService(
                settings=settings,
                market_data=provider,
                history_repository=history_repository,
                repository=repository,
                strategies=StrategyRegistry.default(),
                clock=lambda: datetime(
                    2026,
                    8,
                    15,
                    14,
                    0,
                    tzinfo=timezone(timedelta(hours=8)),
                ),
            )

            latest_path, packet = service.prepare("510300", evaluate_strategies=True)
            persisted = json.loads(latest_path.read_text(encoding="utf-8"))

            self.assertEqual(provider.calls, [("510300", 300)])
            self.assertEqual(packet["schema_version"], 5)
            self.assertEqual(
                packet["strategy_plan"][0]["profile_id"],
                "dividend_default",
            )
            self.assertEqual(
                packet["analysis_plan"]["cycles"],
                ["daily", "moving_average"],
            )
            self.assertEqual(packet["data_quality"]["sync_mode"], "full")
            self.assertEqual(packet["instrument"]["type"], "etf")
            self.assertEqual(
                packet["instrument"]["strategy_profiles"],
                ["dividend_default"],
            )
            self.assertEqual(
                packet["assessments"][0]["id"],
                "dividend_low_vol",
            )
            self.assertEqual(
                packet["assessments"][0]["profile_id"],
                "dividend_default",
            )
            self.assertEqual(
                packet["research_plan"]["focus"],
                ["大类默认关注", "标的个性关注"],
            )
            self.assertNotIn("notification_plan", packet)
            self.assertEqual(
                packet["metrics"]["liquidity"]["latest_amount"],
                23_000_000,
            )
            history = history_repository.load_bars("510300")
            self.assertEqual(len(history), 30)
            self.assertEqual(history[-1].amount, 23_000_000)
            self.assertEqual(persisted, packet)
            snapshots = list((root / "data" / "snapshots").rglob("*.json"))
            self.assertEqual(len(snapshots), 1)
            self.assertTrue((root / "data" / "latest" / "510300.prompt.txt").exists())

    def test_uses_incremental_overlap_and_repairs_recent_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text(CONFIG, encoding="utf-8")
            settings = load_settings(root, config_path)
            source_bundle = market_bundle(301)
            provider = WindowedMarketData(source_bundle)
            repository = FileResearchRepository(settings.data_dir)
            history_repository = SQLiteMarketHistoryRepository(
                settings.data_dir / "history" / "market.sqlite3"
            )
            now = datetime(
                2026,
                8,
                15,
                14,
                0,
                tzinfo=timezone(timedelta(hours=8)),
            )
            service = MonitoringService(
                settings=settings,
                market_data=provider,
                history_repository=history_repository,
                repository=repository,
                strategies=StrategyRegistry.default(),
                clock=lambda: now,
            )

            _, first_packet = service.prepare("510300")
            missing_date = source_bundle.bars[-10].trading_date
            with sqlite3.connect(history_repository.database_path) as connection:
                connection.execute(
                    """
                    DELETE FROM daily_bars
                    WHERE symbol = ? AND trading_date = ?
                    """,
                    ("510300", missing_date.isoformat()),
                )
            history_repository.save_bundle(
                settings.instrument_for("510300"),
                MarketBundle(
                    quote=source_bundle.quote,
                    bars=(source_bundle.bars[0],),
                    source=source_bundle.source,
                ),
                now,
            )

            _, second_packet = service.prepare("510300")
            stored_dates = {
                item.trading_date
                for item in history_repository.load_bars(
                    "510300",
                    limit=300,
                )
            }

            self.assertEqual(first_packet["data_quality"]["sync_mode"], "full")
            self.assertEqual(
                provider.calls,
                [("510300", 300), ("510300", 40)],
            )
            self.assertEqual(
                second_packet["data_quality"]["sync_mode"],
                "incremental",
            )
            self.assertEqual(
                second_packet["data_quality"]["repaired_history_dates"],
                [missing_date.isoformat()],
            )
            self.assertIn(missing_date, stored_dates)
            self.assertEqual(
                len(list((settings.data_dir / "snapshots").rglob("*.json"))),
                2,
            )

    def test_data_preparation_is_independent_of_strategy_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.toml"
            config.write_text(CONFIG, encoding="utf-8")
            settings = load_settings(root, config)
            provider = FakeMarketData(market_bundle())
            service = MonitoringService(
                settings,
                provider,
                SQLiteMarketHistoryRepository(root / "market.sqlite3"),
                FileResearchRepository(settings.data_dir),
                StrategyRegistry.default(),
                StrategyCatalog(1, ()),
            )
            _, packet = service.prepare("510300")
            self.assertEqual(packet["assessments"], [])
            self.assertEqual(packet["strategy_plan"], [])
            self.assertFalse(packet["data_quality"]["strategy_evaluated"])
            with self.assertRaisesRegex(ValueError, "启用版本"):
                service.prepare("510300", evaluate_strategies=True)
            self.assertEqual(len(provider.calls), 1)

    def test_repairs_history_to_configured_start_then_resumes_incremental(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_bundle = market_bundle(557)
            history_start = source_bundle.bars[0].trading_date
            config_path = root / "config.toml"
            config_path.write_text(
                CONFIG.replace(
                    'type = "etf"\n',
                    f'type = "etf"\nhistory_start_date = {history_start}\n',
                ),
                encoding="utf-8",
            )
            settings = load_settings(root, config_path)
            provider = WindowedMarketData(source_bundle)
            repository = FileResearchRepository(settings.data_dir)
            history_repository = SQLiteMarketHistoryRepository(
                settings.data_dir / "history" / "market.sqlite3"
            )
            now = datetime(
                2026,
                8,
                15,
                14,
                0,
                tzinfo=timezone(timedelta(hours=8)),
            )
            history_repository.save_bundle(
                settings.instrument_for("510300"),
                MarketBundle(
                    quote=source_bundle.quote,
                    bars=source_bundle.bars[-300:],
                    source=source_bundle.source,
                ),
                now,
            )
            service = MonitoringService(
                settings=settings,
                market_data=provider,
                history_repository=history_repository,
                repository=repository,
                strategies=StrategyRegistry.default(),
                clock=lambda: now,
            )

            first = service.sync_history("510300")
            second = service.sync_history("510300")

            self.assertEqual(provider.calls, [("510300", 1_000), ("510300", 40)])
            self.assertEqual(first.sync_mode, "full")
            self.assertEqual(first.summary.first_date, history_start)
            self.assertEqual(first.summary.bar_count, 557)
            self.assertEqual(second.sync_mode, "incremental")


if __name__ == "__main__":
    unittest.main()
