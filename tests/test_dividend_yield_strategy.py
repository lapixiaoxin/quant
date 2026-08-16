from __future__ import annotations

import unittest

from quant_monitor.domain.strategies.etf import DividendYieldDynamicStrategy


def metrics(
    *,
    percentile: float | None,
    observations: int = 1_000,
    drawdown: float = -0.12,
    fundamental_status: str = "pass",
    dividend_cut_pct: float | None = None,
    stale: bool = False,
) -> dict:
    valuation = None
    if percentile is not None:
        valuation = {
            "dividend_yield": 0.055,
            "dividend_yield_percentile": percentile,
            "history_observations": observations,
            "stale": stale,
        }
    return {
        "valuation": valuation,
        "drawdowns": {"from_high_242d": drawdown},
        "fundamental_guard": {
            "status": fundamental_status,
            "dividend_cut_pct": dividend_cut_pct,
        },
    }


class DividendYieldDynamicStrategyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = DividendYieldDynamicStrategy()
        self.parameters = {
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
        }

    def decide(self, data: dict):
        return self.strategy.decide(
            data,
            profile_id="test",
            parameters=self.parameters,
        )

    def test_missing_or_short_valuation_history_blocks_direction(self) -> None:
        missing = self.decide(metrics(percentile=None))
        short = self.decide(metrics(percentile=0.90, observations=500))

        self.assertEqual(missing.status, "blocked")
        self.assertIsNone(missing.target_weight)
        self.assertEqual(short.band, "估值历史不足")
        self.assertIsNone(short.target_weight)

    def test_expensive_percentile_keeps_only_minimum_weight(self) -> None:
        decision = self.decide(metrics(percentile=0.12))

        self.assertEqual(decision.status, "eligible")
        self.assertEqual(decision.band, "估值偏贵")
        self.assertEqual(decision.target_weight, 0.20)

    def test_high_yield_percentile_requires_fundamental_confirmation(self) -> None:
        decision = self.decide(
            metrics(percentile=0.90, fundamental_status="unknown")
        )

        self.assertEqual(decision.status, "blocked")
        self.assertEqual(decision.band, "待补基本面")
        self.assertIsNone(decision.target_weight)

    def test_drawdown_confirms_each_addition_band(self) -> None:
        first = self.decide(metrics(percentile=0.75, drawdown=-0.06))
        second = self.decide(metrics(percentile=0.90, drawdown=-0.12))
        full = self.decide(metrics(percentile=0.97, drawdown=-0.18))

        self.assertEqual(first.target_weight, 0.50)
        self.assertEqual(second.target_weight, 0.75)
        self.assertEqual(full.target_weight, 1.00)

    def test_shallow_drawdown_caps_aggressive_addition(self) -> None:
        decision = self.decide(metrics(percentile=0.97, drawdown=-0.08))

        self.assertEqual(decision.band, "极端分位待回撤确认")
        self.assertEqual(decision.target_weight, 0.75)

    def test_dividend_cut_invalidates_averaging_down(self) -> None:
        decision = self.decide(
            metrics(
                percentile=0.97,
                drawdown=-0.20,
                dividend_cut_pct=-0.20,
            )
        )

        self.assertEqual(decision.status, "invalidated")
        self.assertEqual(decision.target_weight, 0.20)
        self.assertIn("禁止越跌越加", decision.reasons[0])

    def test_parameter_order_is_validated(self) -> None:
        invalid = {
            **self.parameters,
            "first_add_percentile": 0.90,
            "second_add_percentile": 0.80,
        }

        with self.assertRaisesRegex(ValueError, "分位阈值"):
            self.strategy.validate_parameters(
                invalid,
                profile_id="test",
            )


if __name__ == "__main__":
    unittest.main()
