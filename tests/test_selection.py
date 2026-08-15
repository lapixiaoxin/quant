from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from quant_monitor.application.selection import SelectionService
from quant_monitor.domain.models import (
    DailyBar,
    Instrument,
    InstrumentType,
    MarketBundle,
    MarketQuote,
)
from quant_monitor.domain.selection import (
    CandidateMetadata,
    SelectionCandidate,
    SelectionRules,
    SelectionUniverse,
    evaluate_candidate,
)
from quant_monitor.infrastructure.selection_config import load_selection_universe
from quant_monitor.interfaces.selection_reporting import build_selection_report


def candidate(symbol: str, *, complete: bool = True) -> SelectionCandidate:
    metadata = CandidateMetadata(
        tracking_index="测试指数" if complete else "",
        tracking_index_code="TEST" if complete else "",
        management_fee_pct=0.5 if complete else None,
        custody_fee_pct=0.1 if complete else None,
        fund_size_cny=2_000_000_000 if complete else None,
        tracking_error_pct=0.02 if complete else None,
        tracking_error_as_of=date(2026, 8, 14) if complete else None,
        as_of=date(2026, 8, 14) if complete else None,
        source_urls=("https://example.com/source",) if complete else (),
    )
    return SelectionCandidate(
        symbol=symbol,
        name=f"候选 {symbol}",
        exchange="SH",
        instrument_type=InstrumentType.ETF,
        metadata=metadata,
    )


def market_bundle(
    symbol: str,
    *,
    amount: float = 30_000_000,
) -> MarketBundle:
    first_day = date(2025, 1, 1)
    bars = tuple(
        DailyBar(
            trading_date=first_day + timedelta(days=index),
            open=1 + index * 0.001,
            close=1 + index * 0.001,
            high=1.01 + index * 0.001,
            low=0.99 + index * 0.001,
            volume=1_000_000,
            amount=amount,
            amplitude_pct=2.0,
            change_pct=0.1,
            turnover_pct=1.0,
        )
        for index in range(250)
    )
    return MarketBundle(
        quote=MarketQuote(
            symbol=symbol,
            name=f"候选 {symbol}",
            price=bars[-1].close,
            high=bars[-1].high,
            low=bars[-1].low,
            open=bars[-1].open,
            previous_close=bars[-2].close,
            volume=bars[-1].volume,
            amount=bars[-1].amount,
            total_market_value=0,
            circulating_market_value=0,
            change_pct=0.001,
            amplitude_pct=0.02,
            price_precision=3,
        ),
        bars=bars,
        source="测试行情源",
    )


class FakeMarketData:
    def fetch(self, instrument: Instrument, limit: int) -> MarketBundle:
        if instrument.symbol == "FAIL":
            raise RuntimeError("测试行情失败")
        return market_bundle(instrument.symbol, amount=limit * 100_000)


class FakeHistoryRepository:
    def __init__(self) -> None:
        self.saved: list[str] = []

    def save_bundle(
        self,
        instrument: Instrument,
        bundle: MarketBundle,
        fetched_at: datetime,
    ) -> None:
        del bundle, fetched_at
        self.saved.append(instrument.symbol)


class FakeResearchRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.packet = None

    def save_selection_packet(self, universe_id: str, packet: dict) -> Path:
        self.packet = packet
        return self.root / f"{universe_id}.json"


class SelectionTest(unittest.TestCase):
    def test_metadata_requires_source_and_tracking_error_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "metadata_as_of"):
            CandidateMetadata(management_fee_pct=0.5)
        with self.assertRaisesRegex(ValueError, "tracking_error_as_of"):
            CandidateMetadata(
                tracking_error_pct=0.5,
                as_of=date(2026, 8, 14),
                source_urls=("https://example.com/source",),
            )

    def test_candidate_requires_metadata_before_final_eligibility(self) -> None:
        rules = SelectionRules(
            required_metadata=(
                "tracking_index_code",
                "total_fee_pct",
                "fund_size_cny",
                "tracking_error_pct",
            )
        )

        result = evaluate_candidate(
            candidate("515100", complete=False),
            market_bundle("515100"),
            rules,
        )

        self.assertEqual(result.status, "needs_research")
        self.assertIn("total_fee_pct", result.evidence_gaps)
        self.assertEqual(result.exclusions, ())

    def test_hard_liquidity_gate_excludes_candidate(self) -> None:
        result = evaluate_candidate(
            candidate("560520"),
            market_bundle("560520", amount=100_000),
            SelectionRules(min_average_amount_cny=10_000_000),
        )

        self.assertEqual(result.status, "excluded")
        self.assertIn("日均成交额低于门槛", result.exclusions[0])

    def test_missing_liquidity_is_evidence_gap_not_product_failure(self) -> None:
        result = evaluate_candidate(
            candidate("515100"),
            market_bundle("515100", amount=0),
            SelectionRules(min_average_amount_cny=10_000_000),
        )

        self.assertEqual(result.status, "needs_research")
        self.assertEqual(result.exclusions, ())
        self.assertIn("average_amount_20d_cny", result.evidence_gaps)

    def test_loads_versioned_candidate_universe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "universe.toml"
            path.write_text(
                """
schema_version = 1
universe_id = "test-etf"
name = "测试 ETF"
objective = "验证候选池"
instrument_type = "etf"
history_days = 250
shortlist_size = 1

[rules]
min_history_bars = 120
required_metadata = ["total_fee_pct"]

[[candidates]]
symbol = "515100"
name = "候选一"
exchange = "SH"
management_fee_pct = 0.5
custody_fee_pct = 0.1
metadata_as_of = 2026-08-14
source_urls = ["https://example.com/source"]

[[candidates]]
symbol = "512890"
name = "候选二"
exchange = "SH"
""",
                encoding="utf-8",
            )

            universe = load_selection_universe(path)

            self.assertEqual(universe.universe_id, "test-etf")
            self.assertEqual(len(universe.candidates), 2)
            self.assertEqual(
                universe.candidates[0].metadata.total_fee_pct,
                0.6,
            )

    def test_service_keeps_one_candidate_failure_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = FakeResearchRepository(root)
            history = FakeHistoryRepository()
            universe = SelectionUniverse(
                universe_id="test",
                name="测试候选池",
                objective="验证失败隔离",
                instrument_type=InstrumentType.ETF,
                history_days=250,
                shortlist_size=1,
                rules=SelectionRules(),
                candidates=(candidate("515100"), candidate("FAIL")),
            )
            service = SelectionService(
                settings=SimpleNamespace(timezone="Asia/Shanghai"),
                market_data=FakeMarketData(),
                history_repository=history,
                repository=repository,
                clock=lambda: datetime(
                    2026,
                    8,
                    15,
                    tzinfo=timezone(timedelta(hours=8)),
                ),
            )

            _, packet = service.prepare(universe)

            self.assertEqual(history.saved, ["515100"])
            self.assertEqual(packet["summary"]["candidate_count"], 2)
            self.assertEqual(packet["summary"]["data_error"], 1)
            failed = next(
                item for item in packet["candidates"] if item["symbol"] == "FAIL"
            )
            self.assertEqual(failed["status"], "data_error")

    def test_html_report_escapes_candidate_content(self) -> None:
        packet = {
            "as_of": "2026-08-15T14:00:00+08:00",
            "universe": {
                "id": "test",
                "name": "<测试候选池>",
                "objective": "比较 & 验证",
            },
            "summary": {
                "candidate_count": 1,
                "needs_research": 1,
                "market_ranking_scope": "仅供研究",
            },
            "candidates": [
                {
                    "symbol": "515100",
                    "name": "<script>alert(1)</script>",
                    "status": "needs_research",
                    "metadata": {"as_of": "2026-06-29"},
                    "metrics": {
                        "average_amount_20d": 12_000_000,
                        "average_amount_20d_source": "verified_metadata",
                    },
                    "exclusions": [],
                    "evidence_gaps": ["tracking_error_pct"],
                    "market_score": None,
                    "market_rank": None,
                }
            ],
            "data_quality": {"limitations": ["来源 < 待核验"]},
        }

        html = build_selection_report(packet)

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("比较 &amp; 验证", html)
        self.assertIn("2026-06-29", html)
        self.assertIn("元数据核验", html)


if __name__ == "__main__":
    unittest.main()
