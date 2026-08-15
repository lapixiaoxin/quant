from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_monitor.domain.control_plane import (
    AnalysisCycle,
    AnalysisRequest,
    AnalysisTrigger,
    BacktestRunRecord,
    InvestmentHorizon,
    ReportRecord,
    SelectionRunRecord,
)
from quant_monitor.infrastructure.control_repository import (
    SQLiteControlPlaneRepository,
)


class ControlRepositoryTest(unittest.TestCase):
    def test_persists_cross_module_runtime_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteControlPlaneRepository(
                Path(directory) / "control.sqlite3"
            )
            now = datetime(2026, 8, 15, 14, 0, tzinfo=timezone.utc)
            request = AnalysisRequest(
                request_id="analysis-1",
                requested_at=now,
                trigger=AnalysisTrigger.MANUAL,
                mode="base",
                symbols=("515100",),
                cycles=(
                    AnalysisCycle.DAILY,
                    AnalysisCycle.MOVING_AVERAGE,
                ),
                factor_ids=("market_snapshot", "strategy"),
                send=False,
            )

            repository.save_analysis_request(request, status="running")
            repository.complete_analysis(
                request.request_id,
                completed_at=now,
                status="completed",
            )
            repository.save_report(
                ReportRecord(
                    report_id="report-1",
                    analysis_request_id=request.request_id,
                    symbol="515100",
                    report_type="base_report",
                    title="测试报告",
                    path="data/reports/test.md",
                    generated_at=now,
                    strategy_record_ids=("strategy-v1",),
                    cycles=("daily",),
                    factor_ids=("strategy",),
                    channels=(),
                    delivery_status="not_requested",
                )
            )
            repository.save_selection(
                SelectionRunRecord(
                    run_id="selection-1",
                    universe_id="universe-1",
                    horizon=InvestmentHorizon.LONG,
                    theme="dividend",
                    requested_at=now,
                    status="completed",
                    candidate_count=6,
                    shortlist_count=3,
                    packet_path="data/selections/test.json",
                    report_path="data/selections/test.html",
                )
            )
            repository.save_backtest(
                BacktestRunRecord(
                    run_id="backtest-1",
                    strategy_record_id="strategy-v1",
                    symbol="515100",
                    started_at=now,
                    completed_at=now,
                    status="completed",
                    result_path="data/backtests/test.html",
                    total_return=0.12,
                    max_drawdown=-0.08,
                    trade_count=4,
                )
            )

            snapshot = repository.export_snapshot()

            self.assertEqual(snapshot["schema_version"], 1)
            self.assertEqual(
                snapshot["analysis_runs"][0]["status"],
                "completed",
            )
            self.assertEqual(
                snapshot["reports"][0]["delivery_status"],
                "not_requested",
            )
            self.assertEqual(
                snapshot["selection_runs"][0]["shortlist_count"],
                3,
            )
            self.assertEqual(
                snapshot["backtest_runs"][0]["trade_count"],
                4,
            )

    def test_rejects_completion_for_unknown_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteControlPlaneRepository(
                Path(directory) / "control.sqlite3"
            )

            with self.assertRaisesRegex(ValueError, "分析任务不存在"):
                repository.complete_analysis(
                    "missing",
                    completed_at=datetime.now(timezone.utc),
                    status="failed",
                )


if __name__ == "__main__":
    unittest.main()
