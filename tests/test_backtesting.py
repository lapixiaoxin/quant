from __future__ import annotations

import unittest
from datetime import date

from quant_monitor.domain.backtesting import BacktestSignal, BacktestSpecification


class BacktestingContractTest(unittest.TestCase):
    def test_specification_freezes_model_version_and_costs(self) -> None:
        specification = BacktestSpecification(
            symbol="515100",
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
                symbol="515100",
                model_id="model",
                model_version="1.0.0",
                parameters_fingerprint="sha256:test-parameters",
                start_date=date(2026, 1, 2),
                end_date=date(2026, 1, 1),
            )

    def test_specification_requires_parameters_fingerprint(self) -> None:
        with self.assertRaisesRegex(ValueError, "参数指纹"):
            BacktestSpecification(
                symbol="515100",
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


if __name__ == "__main__":
    unittest.main()
