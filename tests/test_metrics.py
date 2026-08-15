from __future__ import annotations

import unittest
from datetime import date, timedelta

from quant_monitor.domain.metrics import (
    calculate_metrics,
    drawdown_from_high,
    max_drawdown,
    moving_average,
    simple_return,
)
from quant_monitor.domain.models import DailyBar, Instrument, InstrumentType
from quant_monitor.domain.strategies import DividendLowVolStrategy


def bars_from_closes(closes: list[float]) -> list[DailyBar]:
    start = date(2025, 1, 1)
    return [
        DailyBar(
            trading_date=start + timedelta(days=index),
            open=close,
            close=close,
            high=close * 1.01,
            low=close * 0.99,
            volume=1_000_000,
            amount=100_000_000 + index * 1_000_000,
            amplitude_pct=2.0,
            change_pct=0.0 if index == 0 else (close / closes[index - 1] - 1) * 100,
            turnover_pct=1.0,
        )
        for index, close in enumerate(closes)
    ]


class MetricsTest(unittest.TestCase):
    def test_basic_functions(self) -> None:
        values = [1.0, 2.0, 3.0, 2.0]
        self.assertEqual(moving_average(values, 2), 2.5)
        self.assertAlmostEqual(simple_return(values, 1), -1 / 3)
        self.assertAlmostEqual(drawdown_from_high(values, 4), -1 / 3)
        self.assertAlmostEqual(max_drawdown(values, 4), -1 / 3)

    def test_uptrend_classification(self) -> None:
        closes = [1 + index * 0.005 for index in range(150)]
        result = calculate_metrics(bars_from_closes(closes))
        self.assertEqual(result["trend_state"], "强势上涨")
        self.assertGreater(
            result["moving_averages"]["ma20"],
            result["moving_averages"]["ma60"],
        )
        self.assertEqual(result["returns"]["1d"], round(closes[-1] / closes[-2] - 1, 4))

    def test_deep_drawdown_increases_attention_score(self) -> None:
        closes = [1 + index * 0.002 for index in range(120)]
        closes.extend([closes[-1] * (1 - index * 0.01) for index in range(1, 10)])
        metrics = calculate_metrics(bars_from_closes(closes))
        instrument = Instrument(
            symbol="515100",
            name="测试 ETF",
            exchange="SH",
            instrument_type=InstrumentType.ETF,
            strategy_profile_ids=("dividend_default",),
            research_profile_id="etf_core",
            notification_policy_id="silent",
            history_days=500,
        )
        result = DividendLowVolStrategy().evaluate(instrument, metrics)
        self.assertLessEqual(metrics["drawdowns"]["from_high_60d"], -0.08)
        self.assertTrue(
            any("回撤" in reason for reason in result.reasons)
        )

    def test_rejects_insufficient_history(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要 20"):
            calculate_metrics(bars_from_closes([1.0] * 19))

    def test_strategy_profile_parameters_change_thresholds(self) -> None:
        closes = [1 + index * 0.002 for index in range(120)]
        closes.extend([closes[-1] * (1 - index * 0.01) for index in range(1, 10)])
        metrics = calculate_metrics(bars_from_closes(closes))
        instrument = Instrument(
            symbol="515100",
            name="测试 ETF",
            exchange="SH",
            instrument_type=InstrumentType.ETF,
            strategy_profile_ids=("default",),
            research_profile_id="core",
            notification_policy_id="silent",
            history_days=500,
        )
        strategy = DividendLowVolStrategy()

        default = strategy.evaluate(instrument, metrics)
        conservative = strategy.evaluate(
            instrument,
            metrics,
            profile_id="conservative",
            parameters={
                "deep_drawdown": -0.20,
                "attention_drawdown": -0.15,
                "mild_drawdown": -0.10,
                "near_high": -0.01,
            },
        )

        self.assertGreater(default.score, conservative.score)

    def test_strategy_rejects_invalid_threshold_order(self) -> None:
        strategy = DividendLowVolStrategy()
        with self.assertRaisesRegex(ValueError, "阈值顺序"):
            strategy.validate_parameters(
                {
                    "deep_drawdown": -0.03,
                    "attention_drawdown": -0.08,
                },
                profile_id="broken",
            )


if __name__ == "__main__":
    unittest.main()
