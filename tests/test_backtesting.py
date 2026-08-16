from __future__ import annotations

import unittest
from datetime import date, timedelta

from quant_monitor.application.backtesting import BacktestService
from quant_monitor.domain.backtesting import (
    BacktestSignal,
    BacktestSpecification,
    DividendYieldPercentileAllocationModel,
)
from quant_monitor.domain.models import (
    DailyBar,
    Instrument,
    InstrumentType,
    ValuationObservation,
)
from quant_monitor.domain.strategies.etf import DividendYieldDynamicStrategy


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


class DividendYieldBacktestModelTest(unittest.TestCase):
    def setUp(self) -> None:
        first_day = date(2024, 1, 1)
        self.bars = tuple(
            DailyBar(
                trading_date=first_day + timedelta(days=index),
                open=100,
                close=(
                    90
                    if index == 241
                    else 100
                ),
                high=100,
                low=90,
                volume=1_000,
                amount=100_000,
                amplitude_pct=0,
                change_pct=0,
                turnover_pct=0,
            )
            for index in range(270)
        )
        filler_start = first_day - timedelta(days=800)
        valuation_dates = {
            filler_start + timedelta(days=index)
            for index in range(727)
        }
        valuation_dates.update(item.trading_date for item in self.bars)
        observations = tuple(
            ValuationObservation(
                valuation_symbol="000151",
                observation_date=observation_date,
                metric="dividend_yield",
                weighting="market_cap_weighted",
                history_window="y3",
                value=0.065,
                percentile=(
                    0.10
                    if observation_date >= self.bars[261].trading_date
                    else 0.75
                ),
                percentile_20_value=0.05,
                percentile_50_value=0.06,
                percentile_80_value=0.07,
                source="测试估值",
                source_url="https://example.com",
            )
            for observation_date in sorted(valuation_dates)
        )
        self.model = DividendYieldPercentileAllocationModel(
            DividendYieldDynamicStrategy(),
            observations,
        )
        self.parameters = {
            "profile_id": "dynamic",
            "rebalance_interval_days": 20,
            "valuation_timing": "point_in_time",
            "missing_valuation_policy": "reject",
            "fundamental_guard_mode": "index_methodology_proxy",
            "strategy_parameters": {
                "minimum_history_observations": 726,
                "expensive_percentile": 0.20,
                "first_add_percentile": 0.70,
                "second_add_percentile": 0.85,
                "full_add_percentile": 0.95,
                "minimum_weight": 0.20,
                "base_weight": 0.30,
                "first_add_weight": 0.50,
                "second_add_weight": 0.75,
                "full_weight": 1.00,
                "first_add_drawdown": -0.05,
                "second_add_drawdown": -0.10,
                "full_add_drawdown": -0.15,
                "dividend_cut_limit": -0.15,
            },
        }

    def test_maps_percentile_and_drawdown_to_target_weight(self) -> None:
        signal = self.model.generate_signal(
            instrument(),
            self.bars[:242],
            self.parameters,
        )

        self.assertEqual(signal.target_weight, 0.50)
        self.assertIn("历史分位 75.00%", signal.reason)
        self.assertIn("242日回撤 -10.00%", signal.reason)

    def test_keeps_target_between_twenty_day_rebalances(self) -> None:
        before_next_rebalance = self.model.generate_signal(
            instrument(),
            self.bars[:261],
            self.parameters,
        )
        on_next_rebalance = self.model.generate_signal(
            instrument(),
            self.bars[:262],
            self.parameters,
        )

        self.assertEqual(before_next_rebalance.target_weight, 0.50)
        self.assertEqual(on_next_rebalance.target_weight, 0.20)

    def test_rejects_non_point_in_time_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "point_in_time"):
            self.model.validate_parameters(
                {
                    **self.parameters,
                    "valuation_timing": "full_sample",
                }
            )


if __name__ == "__main__":
    unittest.main()
