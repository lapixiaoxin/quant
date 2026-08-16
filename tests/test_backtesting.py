from __future__ import annotations

import unittest
from datetime import date, timedelta

from quant_monitor.application.backtesting import BacktestService
from quant_monitor.domain.backtesting import BacktestSignal, BacktestSpecification
from quant_monitor.domain.models import DailyBar, Instrument, InstrumentType


class TrackingModel:
    minimum_bars = 2

    def __init__(self) -> None:
        self.history_dates: list[tuple[date, ...]] = []

    def generate_signal(
        self,
        instrument: Instrument,
        history: tuple[DailyBar, ...],
        parameters: dict,
    ) -> BacktestSignal:
        del instrument, parameters
        self.history_dates.append(
            tuple(item.trading_date for item in history)
        )
        return BacktestSignal(
            trading_date=history[-1].trading_date,
            target_weight=1.0,
            reason="测试保持满仓",
        )


def flat_bars() -> tuple[DailyBar, ...]:
    first_day = date(2026, 1, 1)
    return tuple(
        DailyBar(
            trading_date=first_day + timedelta(days=index),
            open=100,
            close=100,
            high=100,
            low=100,
            volume=1_000,
            amount=100_000,
            amplitude_pct=0,
            change_pct=0,
            turnover_pct=0,
        )
        for index in range(4)
    )


def instrument() -> Instrument:
    return Instrument(
        symbol="510300",
        name="测试 ETF",
        exchange="SH",
        instrument_type=InstrumentType.ETF,
        strategy_profile_ids=("default",),
        research_profile_id="core",
        notification_policy_id="silent",
        history_days=300,
    )


class BacktestingContractTest(unittest.TestCase):
    def test_specification_freezes_model_version_and_costs(self) -> None:
        specification = BacktestSpecification(
            symbol="510300",
            model_id="dividend_rotation",
            model_version="1.0.0",
            parameters_fingerprint="sha256:test-parameters",
            start_date=date(2020, 1, 1),
            end_date=date(2025, 12, 31),
            commission_bps=3.0,
            slippage_bps=2.0,
        )

        self.assertEqual(specification.model_version, "1.0.0")
        self.assertEqual(specification.commission_bps, 3.0)

    def test_specification_rejects_invalid_date_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "开始日期"):
            BacktestSpecification(
                symbol="510300",
                model_id="model",
                model_version="1.0.0",
                parameters_fingerprint="sha256:test-parameters",
                start_date=date(2026, 1, 2),
                end_date=date(2026, 1, 1),
            )

    def test_specification_requires_parameters_fingerprint(self) -> None:
        with self.assertRaisesRegex(ValueError, "参数指纹"):
            BacktestSpecification(
                symbol="510300",
                model_id="model",
                model_version="1.0.0",
                parameters_fingerprint="",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 2),
            )

    def test_long_only_signal_rejects_leverage(self) -> None:
        with self.assertRaisesRegex(ValueError, "目标仓位"):
            BacktestSignal(
                trading_date=date(2026, 1, 1),
                target_weight=1.2,
                reason="测试越界",
            )

    def test_simulation_uses_only_prior_bars_and_charges_costs(self) -> None:
        bars = flat_bars()
        model = TrackingModel()
        specification = BacktestSpecification(
            symbol="510300",
            model_id="tracking",
            model_version="1.0.0",
            parameters_fingerprint="sha256:test",
            start_date=bars[0].trading_date,
            end_date=bars[-1].trading_date,
            initial_cash=1_000,
            commission_bps=100,
            slippage_bps=0,
        )

        result = BacktestService._simulate(
            instrument(),
            bars,
            specification,
            model,
            {},
        )

        self.assertEqual(
            model.history_dates,
            [
                (bars[0].trading_date, bars[1].trading_date),
                (
                    bars[0].trading_date,
                    bars[1].trading_date,
                    bars[2].trading_date,
                ),
            ],
        )
        self.assertEqual(
            result.equity_curve[0].trading_date,
            bars[2].trading_date,
        )
        self.assertEqual(result.metrics.trade_count, 1)
        self.assertAlmostEqual(
            result.equity_curve[-1].equity,
            1_000 / 1.01,
        )
        self.assertLess(result.metrics.total_return, 0)


if __name__ == "__main__":
    unittest.main()
