from __future__ import annotations

import json
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
from quant_monitor.infrastructure.storage import FileResearchRepository


class FakeMarketData:
    def __init__(self, bundle: MarketBundle) -> None:
        self.bundle = bundle
        self.calls: list[tuple[str, int]] = []

    def fetch(self, instrument: Instrument, limit: int) -> MarketBundle:
        self.calls.append((instrument.symbol, limit))
        return self.bundle


def market_bundle() -> MarketBundle:
    last_day = date(2026, 8, 15)
    bars = tuple(
        DailyBar(
            trading_date=last_day - timedelta(days=29 - index),
            open=1 + index * 0.01,
            close=1 + index * 0.01,
            high=1.01 + index * 0.01,
            low=0.99 + index * 0.01,
            volume=1_000_000,
            amount=0 if index == 29 else 10_000_000,
            amplitude_pct=2.0,
            change_pct=0.5,
            turnover_pct=1.0,
        )
        for index in range(30)
    )
    quote = MarketQuote(
        symbol="515100",
        name="测试 ETF",
        price=1.29,
        high=1.30,
        low=1.28,
        open=1.285,
        previous_close=1.28,
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
    def test_prepares_schema_v3_and_persists_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text(
                """
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
symbol = "515100"
name = "测试 ETF"
type = "etf"
research_focus = ["标的个性关注"]
research_instructions = ["标的个性指令"]
""",
                encoding="utf-8",
            )
            settings = load_settings(root, config_path)
            provider = FakeMarketData(market_bundle())
            repository = FileResearchRepository(settings.data_dir)
            service = MonitoringService(
                settings=settings,
                market_data=provider,
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

            latest_path, packet = service.prepare("515100")
            persisted = json.loads(latest_path.read_text(encoding="utf-8"))

            self.assertEqual(provider.calls, [("515100", 300)])
            self.assertEqual(packet["schema_version"], 3)
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
            self.assertEqual(
                packet["notification_plan"]["policy_id"],
                "silent",
            )
            self.assertEqual(
                packet["metrics"]["liquidity"]["latest_amount"],
                23_000_000,
            )
            self.assertEqual(persisted, packet)
            snapshots = list((root / "data" / "snapshots").rglob("*.json"))
            self.assertEqual(len(snapshots), 1)
            self.assertTrue(
                (root / "data" / "latest" / "515100.prompt.txt").exists()
            )


if __name__ == "__main__":
    unittest.main()
