"""资金分账、前日加仓门禁与已有冻结回测的回归验收。"""

from __future__ import annotations

import json
import math
import unittest
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

from quant_monitor.application.capital_study import CapitalStudyService
from quant_monitor.domain.backtesting.capital import (
    combine_sleeves,
    prior_holding_dates,
)
from quant_monitor.domain.backtesting.swing import (
    CashDividend,
    ExecutionCosts,
    simulate_swing,
)
from quant_monitor.domain.models import DailyBar, Instrument, InstrumentType
from quant_monitor.infrastructure.frozen_history import FrozenCSVHistoryRepository

ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = dict(
    mode="fixed", entry=10, take=0.3, stop=0.2,
    weight=1.0, risk_fraction=1.0, max_hold=20,
)
INSTRUMENT = Instrument(
    "601985", "测试", "SH", InstrumentType.STOCK, (), "", "", 100,
)


def bar(index: int, *, high: float = 10.1, low: float = 9.9) -> DailyBar:
    return DailyBar(
        date(2025, 1, 1) + timedelta(days=index), 10, 10, high, low,
        100000, math.nan, math.nan, math.nan, math.nan,
    )


class CapitalTests(unittest.TestCase):
    def simulate(self, bars, cash=4000, **kwargs):
        return simulate_swing(
            INSTRUMENT, bars, bars[70].trading_date, bars[-1].trading_date,
            PARAMETERS, initial_cash=cash, **kwargs,
        )

    def test_reserve_is_counted_once_and_sleeves_cannot_borrow(self):
        bars = tuple(bar(i) for i in range(74))
        results = {
            "a": self.simulate(bars, cash=4000),
            "small": self.simulate(bars, cash=900),
        }
        result = combine_sleeves(results, {"a": 4000, "small": 900}, bars, 10000)
        self.assertEqual(results["a"].fills[0].quantity, 300)
        self.assertEqual(results["small"].fills, ())
        self.assertEqual(result.metrics["reserve_cash_yuan"], 5100)
        for index, point in enumerate(result.curve):
            self.assertAlmostEqual(
                point.equity,
                5100 + sum(child.curve[index].equity for child in results.values()),
            )
            self.assertGreaterEqual(point.cash, 5100)
        self.assertAlmostEqual(
            result.metrics["net_profit_yuan"],
            sum(fill.net_pnl for fill in result.fills if fill.side == "sell"),
        )

    def test_add_order_uses_previous_holding_even_when_main_sells_today(self):
        bars = tuple(bar(i) for i in range(70)) + (
            bar(70), bar(71, high=10.5), bar(72), bar(73),
        )
        primary = self.simulate(bars)
        allowed = prior_holding_dates(primary)
        self.assertNotIn(bar(70).trading_date, allowed)
        self.assertIn(bar(71).trading_date, allowed)
        self.assertNotIn(bar(72).trading_date, allowed)
        secondary = self.simulate(bars, allowed_entry_dates=allowed)
        self.assertEqual(secondary.fills[0].trading_date, bar(71).trading_date)
        self.assertEqual(primary.fills[1].side, "sell")
        self.assertEqual(primary.fills[1].trading_date, bar(71).trading_date)
        self.assertEqual(
            self.simulate(bars, allowed_entry_dates=frozenset()).fills, (),
        )

    def test_dividend_and_fees_are_not_duplicated_in_portfolio(self):
        bars = tuple(bar(i) for i in range(74))
        dividend = CashDividend(bar(71).trading_date, 0.1, "测试来源")
        results = {
            name: self.simulate(bars, dividends=(dividend,))
            for name in ("a", "b")
        }
        result = combine_sleeves(results, {"a": 4000, "b": 4000}, bars, 10000)
        self.assertAlmostEqual(result.metrics["net_dividends_yuan"], 48)
        self.assertAlmostEqual(
            result.metrics["fees_yuan"],
            sum(child.metrics["fees_yuan"] for child in results.values()),
        )
        self.assertAlmostEqual(
            result.metrics["blocked_sale_shock_19pct"],
            -result.metrics["max_weight"] * 0.19,
        )

    def test_unliquidated_or_inconsistent_sleeve_rejects_whole_result(self):
        bars = tuple(bar(i) for i in range(74))
        normal = self.simulate(bars)
        locked = bars[:-1] + (replace(bars[-1], high=10, low=10),)
        with self.assertRaisesRegex(ValueError, "未能清算"):
            combine_sleeves({"a": self.simulate(locked)}, {"a": 4000}, locked, 10000)
        bad = replace(
            normal, curve=(replace(normal.curve[0], cash=-1),) + normal.curve[1:],
        )
        with self.assertRaisesRegex(ValueError, "无效"):
            combine_sleeves({"a": bad}, {"a": 4000}, bars, 10000)
        with self.assertRaisesRegex(ValueError, "不守恒"):
            combine_sleeves({"a": normal}, {"a": 4100}, bars, 10000)
        with self.assertRaisesRegex(ValueError, "超过总资金"):
            combine_sleeves({"a": normal}, {"a": 11000}, bars, 10000)
        with self.assertRaisesRegex(ValueError, "日期不一致"):
            combine_sleeves(
                {"a": normal, "b": replace(normal, curve=normal.curve[1:])},
                {"a": 4000, "b": 4000}, bars, 10000,
            )

    def test_v1_frozen_fills_and_metrics_remain_unchanged(self):
        fixture = json.loads(
            (ROOT / "tests/fixtures/cash-swing-v1.json").read_text(encoding="utf-8"),
        )
        history = FrozenCSVHistoryRepository(
            ROOT / fixture["history_path"], "601985", fixture["history_sha256"],
        )
        result = simulate_swing(
            INSTRUMENT, history.load_bars("601985"),
            date.fromisoformat(fixture["start"]), date.fromisoformat(fixture["end"]),
            fixture["parameters"], initial_cash=fixture["initial_cash_yuan"],
            costs=ExecutionCosts(**fixture["costs"]),
            dividends=tuple(CashDividend(
                date.fromisoformat(item["ex_date"]), item["per_share"], item["source"],
            ) for item in fixture["dividends"]),
        )
        expected = fixture["expected"]
        self.assertEqual(result.metrics, expected["metrics"])
        self.assertEqual(
            [{**asdict(fill), "trading_date": fill.trading_date.isoformat()}
             for fill in result.fills], expected["fills"],
        )


class CapitalServiceTests(unittest.TestCase):
    def setUp(self):
        self.bars = tuple(bar(i) for i in range(80))
        self.spec = dict(
            study_schema_version=2, model_id="cash_equity_swing", model_version="1.0.0",
            initial_cash_yuan=10000, reference_configuration="one",
            components={"main": PARAMETERS}, dividends=[], costs={},
            configurations=[dict(
                id="one", label="测试",
                sleeves=[dict(id="a", component="main", fraction=0.4)],
            )],
            **dict(zip(
                ("start", "train_end", "validation_start", "validation_end",
                 "holdout_start", "end"),
                (bar(i).trading_date.isoformat() for i in (70, 72, 73, 75, 76, 79)),
            )),
        )

    def load_bars(self, symbol, *, end_date=None):
        return self.bars

    def test_calendar_annualization_and_stress_are_separate(self):
        packet = CapitalStudyService(self).run(INSTRUMENT, self.spec)
        metrics = packet["comparisons"]["one"]["full"]["metrics"]
        self.assertEqual(metrics["calendar_days"], 10)
        self.assertAlmostEqual(
            metrics["annualized_return"], (1 + metrics["total_return"]) ** 36.525 - 1,
        )
        self.assertIsNone(
            packet["comparisons"]["one"]["holdout"]["metrics"]["annualized_return"],
        )
        self.assertLess(
            packet["slippage_stress"]["one"]["full"]["metrics"]["total_return"],
            metrics["total_return"],
        )

    def test_forward_dependencies_and_overspend_are_rejected(self):
        sleeves = self.spec["configurations"][0]["sleeves"]
        sleeves[0]["requires_previous_holding"] = "future"
        with self.assertRaisesRegex(ValueError, "依赖"):
            CapitalStudyService(self).run(INSTRUMENT, self.spec)
        del sleeves[0]["requires_previous_holding"]
        sleeves.extend([dict(id="b", component="main", fraction=0.7)])
        with self.assertRaisesRegex(ValueError, "超过总资金"):
            CapitalStudyService(self).run(INSTRUMENT, self.spec)


if __name__ == "__main__":
    unittest.main()
