from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_monitor.application.analysis import AnalysisService
from quant_monitor.application.automation import AutomationResult
from quant_monitor.config import load_settings
from quant_monitor.domain.control_plane import (
    AnalysisCycle,
    AnalysisRequest,
    AnalysisTrigger,
    InvestmentHorizon,
    StrategyLifecycle,
    StrategyRecord,
    ValidationState,
)
from quant_monitor.domain.factors import FactorRegistry
from quant_monitor.infrastructure.control_repository import (
    SQLiteControlPlaneRepository,
)
from quant_monitor.infrastructure.storage import FileResearchRepository
from quant_monitor.infrastructure.strategy_catalog import (
    StrategyCatalog,
    strategy_profile_fingerprint,
)

CONFIG = """
[app]
data_dir = "data"

[product_types.etf]
strategy_profiles = ["default"]
research_profile = "core"
notification_policy = "silent"
history_days = 300

[strategy_profiles.default]
strategy = "dividend_low_vol"

[research_profiles.core]
skill = "instrument-analyst"
sections = ["趋势"]
source_priorities = ["官方"]

[notification_policies.silent]
enabled = false
channels = []
events = []

[automation]
enabled = true
mode = "base"
send = false

[[instruments]]
symbol = "515100"
name = "测试 ETF"
type = "etf"
"""


class FakeAutomation:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[tuple[str, AnalysisRequest, Path]] = []

    def run(
        self,
        symbol: str,
        *,
        mode: str,
        send: bool,
        event: str,
        analysis_request: AnalysisRequest,
        analysis_request_path: Path,
    ) -> AutomationResult:
        del send, event
        self.calls.append(
            (symbol, analysis_request, analysis_request_path)
        )
        report_path = self.root / "data" / "reports" / f"{symbol}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("# 测试报告\n", encoding="utf-8")
        return AutomationResult(
            symbol=symbol,
            mode=mode,
            report_path=report_path,
            sent_channels=("feishu_primary",),
        )


class AnalysisServiceTest(unittest.TestCase):
    def test_records_request_strategy_factors_report_and_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text(CONFIG, encoding="utf-8")
            settings = load_settings(root, config_path)
            profile = settings.strategy_profiles["default"]
            catalog = StrategyCatalog(
                1,
                (
                    StrategyRecord(
                        record_id="strategy-v1",
                        profile_id="default",
                        version="1.0.0",
                        name="测试策略",
                        symbols=("515100",),
                        horizon=InvestmentHorizon.LONG,
                        lifecycle=StrategyLifecycle.ACTIVE,
                        validation_state=ValidationState.PASSED,
                        created_at=datetime(
                            2026,
                            8,
                            14,
                            tzinfo=timezone.utc,
                        ),
                        enabled_at=datetime(
                            2026,
                            8,
                            15,
                            tzinfo=timezone.utc,
                        ),
                        retired_at=None,
                        thesis="验证标准分析作业",
                        parameters_fingerprint=(
                            strategy_profile_fingerprint(profile)
                        ),
                        backtest_model_id="attention_score_allocation",
                        backtest_model_version="1.0.0",
                        backtest_parameters={
                            "strategy_id": "dividend_low_vol"
                        },
                    ),
                ),
            )
            automation = FakeAutomation(root)
            repository = FileResearchRepository(settings.data_dir)
            control = SQLiteControlPlaneRepository(
                settings.data_dir / "control.sqlite3"
            )
            now = datetime(
                2026,
                8,
                15,
                14,
                0,
                tzinfo=timezone(timedelta(hours=8)),
            )
            service = AnalysisService(
                settings,
                automation,
                repository,
                control,
                catalog,
                FactorRegistry.default(),
                clock=lambda: now,
            )

            request = service.create_request(
                symbols=("515100",),
                cycles=(
                    AnalysisCycle.DAILY,
                    AnalysisCycle.MOVING_AVERAGE,
                ),
                trigger=AnalysisTrigger.REMOTE,
                mode="base",
                send=True,
            )
            execution = service.run(request)
            snapshot = control.export_snapshot()

            self.assertEqual(execution.errors, ())
            self.assertEqual(len(automation.calls), 1)
            self.assertIs(automation.calls[0][1], request)
            self.assertEqual(
                automation.calls[0][2],
                execution.request_path,
            )
            self.assertIn("moving_average", request.factor_ids)
            self.assertIn("strategy", request.factor_ids)
            self.assertEqual(
                snapshot["analysis_runs"][0]["status"],
                "completed",
            )
            self.assertEqual(
                snapshot["reports"][0]["strategy_records_json"],
                '["strategy-v1"]',
            )
            self.assertEqual(
                snapshot["reports"][0]["delivery_status"],
                "sent",
            )


if __name__ == "__main__":
    unittest.main()
