"""显式研究请求的成功、部分失败和旧请求兼容边界。"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from quant_monitor.application.analysis import AnalysisService
from quant_monitor.config import load_settings
from quant_monitor.domain.control_plane import AnalysisCycle, AnalysisRequest
from quant_monitor.domain.factors import FactorRegistry
from quant_monitor.infrastructure.control_repository import SQLiteControlPlaneRepository
from quant_monitor.infrastructure.storage import FileResearchRepository

CONFIG = """
[[instruments]]
symbol = "601985"
name = "中国核电"
type = "stock"
[[instruments]]
symbol = "510720"
name = "红利 ETF"
type = "etf"
"""


class FakeMonitoring:
    def __init__(self, root: Path):
        self.root = root
        self.calls = []
        self.failed = set()

    def prepare(self, symbol, request, *, evaluate_strategies):
        self.calls.append((symbol, request.request_id, evaluate_strategies))
        if symbol in self.failed:
            raise ValueError("行情不足")
        return self.root / f"{symbol}.json", {
            "as_of": "2026-10-07T12:00:00+08:00",
            "strategy_plan": [{"record_id": "test-v1"}],
        }


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        config = self.root / "config.toml"
        config.write_text(CONFIG, encoding="utf-8")
        settings = load_settings(self.root, config)
        self.monitoring = FakeMonitoring(self.root)
        self.repository = FileResearchRepository(settings.data_dir)
        self.control = SQLiteControlPlaneRepository(self.root / "control.sqlite3")
        self.service = AnalysisService(
            settings,
            self.monitoring,
            self.repository,
            self.control,
            FactorRegistry.default(),
            lambda packet: "# 研究基线\n",
            clock=lambda: datetime(2026, 10, 7, tzinfo=timezone.utc),
        )

    def request(self):
        return self.service.create_request(
            symbols=("601985", "510720"),
            cycles=(AnalysisCycle.DAILY,),
        )

    def test_report_and_completed_state_are_registered(self):
        result = self.service.run(self.request())
        self.assertEqual(result.errors, ())
        self.assertEqual(len(result.results), 2)
        snapshot = self.control.export_snapshot()
        self.assertEqual(snapshot["analysis_runs"][0]["status"], "completed")
        self.assertEqual(snapshot["reports"][0]["delivery_status"], "draft")
        self.assertEqual(snapshot["reports"][0]["strategy_records_json"], '["test-v1"]')
        self.assertTrue(all(call[2] for call in self.monitoring.calls))
        self.assertTrue(all(item.report_path.exists() for item in result.results))

    def test_partial_failure_preserves_success_and_failed_state(self):
        self.monitoring.failed = {"510720"}
        result = self.service.run(self.request())
        self.assertEqual(len(result.results), 1)
        self.assertIn("行情不足", result.errors[0])
        self.assertEqual(
            self.control.export_snapshot()["analysis_runs"][0]["status"],
            "partial",
        )
        self.monitoring.failed.add("601985")
        self.service.run(self.request())
        self.assertIn(
            "failed",
            [
                item["status"]
                for item in self.control.export_snapshot()["analysis_runs"]
            ],
        )

    def test_legacy_requests_are_readable_but_cannot_trigger_execution(self):
        request = replace(self.request(), mode="base", send=True)
        packet = {**request.to_packet(), "send": True}
        loaded = AnalysisRequest.from_packet(packet)
        with self.assertRaisesRegex(ValueError, "旧自动化请求"):
            self.service.run(loaded)
        self.assertEqual(self.monitoring.calls, [])

    def test_same_request_cannot_overwrite_its_frozen_snapshot(self):
        request = self.request()
        self.repository.save_analysis_request(request.request_id, request.to_packet())
        with self.assertRaisesRegex(ValueError, "不能覆盖"):
            self.repository.save_analysis_request(
                request.request_id,
                replace(request, symbols=("601985",)).to_packet(),
            )
