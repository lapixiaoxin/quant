from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_monitor.config import load_settings
from quant_monitor.domain.control_plane import (
    InvestmentHorizon,
    StrategyLifecycle,
    StrategyRecord,
    ValidationState,
)
from quant_monitor.infrastructure.strategy_catalog import (
    StrategyCatalog,
    strategy_profile_fingerprint,
)

CONFIG = """
[app]

[product_types.etf]
strategy_profiles = ["default"]
research_profile = "core"
notification_policy = "silent"
history_days = 300

[strategy_profiles.default]
strategy = "dividend_low_vol"
parameters = { attention_drawdown = -0.05 }

[research_profiles.core]
skill = "instrument-analyst"
sections = ["趋势"]
source_priorities = ["官方"]

[notification_policies.silent]
enabled = false
channels = []
events = []

[[instruments]]
symbol = "515100"
name = "测试 ETF"
type = "etf"
"""


def record(fingerprint: str, *, record_id: str = "record-v1") -> StrategyRecord:
    return StrategyRecord(
        record_id=record_id,
        profile_id="default",
        version="1.0.0",
        name="测试策略",
        symbols=("515100",),
        horizon=InvestmentHorizon.LONG,
        lifecycle=StrategyLifecycle.ACTIVE,
        validation_state=ValidationState.PENDING,
        created_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
        enabled_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        retired_at=None,
        thesis="验证策略目录与运行配置一致",
        parameters_fingerprint=fingerprint,
        backtest_model_id="attention_score_allocation",
        backtest_model_version="1.0.0",
        backtest_parameters={"strategy_id": "dividend_low_vol"},
    )


class StrategyCatalogTest(unittest.TestCase):
    def _settings(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        path = root / "config.toml"
        path.write_text(CONFIG, encoding="utf-8")
        return load_settings(root, path)

    def test_accepts_active_record_matching_runtime_parameters(self) -> None:
        settings = self._settings()
        fingerprint = strategy_profile_fingerprint(
            settings.strategy_profiles["default"]
        )
        catalog = StrategyCatalog(1, (record(fingerprint),))

        catalog.validate_settings(settings)

        self.assertEqual(
            catalog.active_for("515100", ("default",))[0].record_id,
            "record-v1",
        )

    def test_rejects_configuration_drift(self) -> None:
        settings = self._settings()
        catalog = StrategyCatalog(1, (record("outdated-fingerprint"),))

        with self.assertRaisesRegex(ValueError, "参数指纹与配置不一致"):
            catalog.validate_settings(settings)

    def test_rejects_two_active_versions_for_same_symbol_and_profile(self) -> None:
        settings = self._settings()
        fingerprint = strategy_profile_fingerprint(
            settings.strategy_profiles["default"]
        )

        with self.assertRaisesRegex(ValueError, "只能有一个启用版本"):
            StrategyCatalog(
                1,
                (
                    record(fingerprint, record_id="record-v1"),
                    record(fingerprint, record_id="record-v2"),
                ),
            )


if __name__ == "__main__":
    unittest.main()
