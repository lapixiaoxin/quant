"""现金回测的执行边界、因果性与冻结输入验收。"""

from __future__ import annotations

import hashlib
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from quant_monitor.application.backtest_study import (
    candidate_parameters,
    choose_candidate,
)
from quant_monitor.domain.backtesting.swing import (
    CashDividend,
    ExecutionCosts,
    PriceSwingModel,
    adjusted_signal_window,
    simulate_swing,
)
from quant_monitor.domain.models import DailyBar, Instrument, InstrumentType
from quant_monitor.infrastructure.frozen_history import FrozenCSVHistoryRepository
from quant_monitor.interfaces.cli import _parser


def instrument() -> Instrument:
    return Instrument("601985", "测试", "SH", InstrumentType.STOCK, (), "", "", 100)


def bar(index: int, *, opening: float = 10, high: float = 10.1,
        low: float = 9.9, close: float = 10, volume: float = 100000) -> DailyBar:
    return DailyBar(
        date(2025, 1, 1) + timedelta(days=index), opening, close, high, low,
        volume, math.nan, math.nan, math.nan, math.nan,
    )


class SwingExecutionTests(unittest.TestCase):
    def run_case(self, active: list[DailyBar], **kwargs):
        bars = tuple(bar(i) for i in range(70)) + tuple(active)
        parameters = kwargs.pop("parameters", dict(
            mode="fixed", entry=10, take=0.3, stop=0.2,
            weight=0.4, risk_fraction=0.5, max_hold=20,
        ))
        return simulate_swing(
            instrument(), bars, active[0].trading_date, active[-1].trading_date,
            parameters, initial_cash=10000, **kwargs,
        )

    def test_round_lots_minimum_fees_and_cash_conservation(self):
        result = self.run_case(
            [bar(70), bar(71)], costs=ExecutionCosts(slippage_yuan=0),
        )
        buy, sell = result.fills
        self.assertEqual(buy.quantity, 400)
        self.assertAlmostEqual(buy.fee, 5.04)
        self.assertAlmostEqual(sell.fee, 7.04)
        self.assertAlmostEqual(result.curve[-1].equity, 10000 - 12.08)
        self.assertEqual(result.curve[-1].shares, 0)

    def test_t1_blocks_same_day_profit_and_stop_then_exits_next_open(self):
        result = self.run_case([
            bar(70, high=10.5, low=9.7),
            bar(71, opening=9.5, high=9.6, low=9.4, close=9.5),
            bar(72),
        ])
        self.assertEqual([fill.side for fill in result.fills], ["buy", "sell"])
        self.assertEqual(result.fills[1].trading_date, bar(71).trading_date)
        self.assertEqual(result.fills[1].reason, "延迟止损")
        self.assertEqual(result.fills[1].price, 9.49)

    def test_double_touch_is_stop_first_but_open_target_is_known_first(self):
        result = self.run_case([bar(70), bar(71, high=10.5, low=9.7), bar(72)])
        self.assertEqual(result.fills[1].reason, "双触止损")
        self.assertEqual(result.diagnostics["double_touch"], 1)
        opening = self.run_case([
            bar(70), bar(71, opening=10.4, high=10.5, low=9.7, close=10), bar(72),
        ])
        self.assertEqual(opening.fills[1].reason, "开盘止盈")

    def test_limit_touch_alone_is_unfilled(self):
        result = self.run_case([
            bar(70, opening=10.1, high=10.2, low=10, close=10.1), bar(71),
        ])
        self.assertEqual(result.fills, ())
        self.assertEqual(result.diagnostics["unfilled_orders"], 1)

    def test_dividend_is_once_and_not_double_counted_with_adjustment(self):
        dividend = CashDividend(bar(71).trading_date, 1.0, "测试来源")
        result = self.run_case(
            [
                bar(70), bar(71, opening=9, high=9.1, low=8.9, close=9),
                bar(72, opening=9, high=9.1, low=8.9, close=9),
            ],
            parameters=dict(mode="hold", weight=0.4),
            dividends=(dividend,), costs=ExecutionCosts(slippage_yuan=0),
        )
        self.assertEqual(result.metrics["net_dividends_yuan"], 320)
        self.assertAlmostEqual(result.curve[-1].equity, 9908.124)
        self.assertEqual(len(result.fills), 2)

    def test_ex_dividend_moves_old_stop_without_spurious_sale(self):
        result = self.run_case(
            [bar(70), bar(71, opening=9, high=9.1, low=8.9, close=9), bar(72)],
            dividends=(CashDividend(bar(71).trading_date, 1, "测试"),),
        )
        self.assertEqual(result.fills[1].trading_date, bar(72).trading_date)
        self.assertNotIn("止损", result.fills[1].reason)

    def test_locked_day_delays_stop_and_reports_unliquidated_end(self):
        result = self.run_case([
            bar(70), bar(71, opening=9.7, high=9.7, low=9.7, close=9.7),
            bar(72, opening=9.5, high=9.6, low=9.4, close=9.5),
        ])
        self.assertEqual(result.fills[-1].reason, "延迟止损")
        locked_end = self.run_case([
            bar(70), bar(71, opening=9.7, high=9.7, low=9.7, close=9.7),
        ])
        self.assertEqual(locked_end.metrics["open_shares"], 400)

    def test_position_sizing_includes_costs_in_risk_budget(self):
        result = self.run_case(
            [bar(70), bar(71)], parameters=dict(
                mode="fixed", entry=10, take=0.3, stop=0.2,
                weight=0.4, risk_fraction=0.005,
            ),
        )
        buy = result.fills[0]
        costs = ExecutionCosts()
        planned_risk = buy.quantity * 0.21 + buy.fee
        planned_risk += costs.fee(buy.quantity, 9.8, sell=True)
        self.assertLessEqual(planned_risk, 50)
        self.assertEqual(buy.quantity % 100, 0)

    def test_two_losses_pause_ten_sessions(self):
        active = [
            bar(70), bar(71, low=9.7), bar(72), bar(73, low=9.7),
        ] + [bar(i) for i in range(74, 86)]
        result = self.run_case(active)
        buys = [fill.trading_date for fill in result.fills if fill.side == "buy"]
        self.assertEqual(buys, [bar(70).trading_date, bar(72).trading_date,
                               bar(84).trading_date])
        self.assertGreaterEqual(result.diagnostics["cooldown_days"], 10)

    def test_time_exit_and_terminal_day_do_not_create_t0_trades(self):
        result = self.run_case(
            [bar(i) for i in range(70, 75)], parameters=dict(
                mode="fixed", entry=10, take=0.3, stop=0.2,
                weight=0.4, risk_fraction=0.5, max_hold=2,
            ),
        )
        self.assertEqual(result.fills[1].trading_date, bar(72).trading_date)
        self.assertEqual(result.fills[1].reason, "时间退出")
        self.assertTrue(all(
            fill.trading_date != bar(74).trading_date
            for fill in result.fills if fill.side == "buy"
        ))

    def test_future_prices_do_not_change_past_fills(self):
        active = [bar(70), bar(71, high=10.5)] + [bar(i) for i in range(72, 77)]
        first = self.run_case(active)
        changed = self.run_case(active[:5] + [
            bar(75, opening=20, high=21, low=19, close=20), bar(76),
        ])
        self.assertEqual(
            [fill for fill in first.fills if fill.trading_date < bar(75).trading_date],
            [
                fill for fill in changed.fills
                if fill.trading_date < bar(75).trading_date
            ],
        )
        history = tuple(bar(i) for i in range(70))
        future = CashDividend(bar(80).trading_date, 1, "测试")
        self.assertEqual(adjusted_signal_window(history, (future,)), history)

    def test_invalid_history_and_parameters_are_rejected(self):
        for active in (
            [bar(70), bar(70)],
            [bar(70), replace(bar(71), close=math.nan)],
            [bar(70), replace(bar(71), low=11)],
        ):
            with self.assertRaises(ValueError):
                self.run_case(active)
        for parameters in (
            dict(mode="unknown"), dict(mode="fixed", max_hold=0),
            dict(mode="fixed", entry=math.nan), dict(mode="fixed", weight=2),
        ):
            with self.assertRaises(ValueError):
                PriceSwingModel().validate_parameters(parameters)


class StudyContractTests(unittest.TestCase):
    def test_selection_does_not_replace_failed_validation_with_hindsight(self):
        def metrics(gain, rounds=3):
            return dict(
                total_return=gain, max_drawdown=-0.01, fees_yuan=10,
                completed_rounds=rounds, open_shares=0,
            )
        training = {"a": metrics(0.03), "b": metrics(0.02), "c": metrics(-0.01)}
        validation = {"a": metrics(-0.01), "b": metrics(-0.02), "c": metrics(0.20)}
        selected, shortlist, passed = choose_candidate(training, validation)
        self.assertEqual(selected, "a")
        self.assertEqual(shortlist, ("a", "b"))
        self.assertFalse(passed)
        validation["b"] = metrics(0.01, 2)
        self.assertEqual(choose_candidate(training, validation)[0], "b")

    def test_frozen_grid_and_cli_modes(self):
        parameters = candidate_parameters(dict(
            entry=[8.7, 8.8, 8.9], take=[0.2, 0.3], max_hold=[5, 20],
            pullback_atr=[0.5, 1], take_atr=[2, 3],
        ))
        self.assertEqual(len(parameters), 28)
        parsed = _parser().parse_args(["backtest", "--study", "study.json"])
        self.assertEqual(str(parsed.study), "study.json")

    def test_frozen_csv_hash_empty_input_and_missing_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "prices.csv"
            path.write_text("date,raw_open_yuan\n2025-01-01,10\n")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                FrozenCSVHistoryRepository(path, "601985", "bad")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "字段"):
                FrozenCSVHistoryRepository(path, "601985", digest)


if __name__ == "__main__":
    unittest.main()
