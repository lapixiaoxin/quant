from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_monitor.interfaces.platform_pages import (
    _legacy_selection_run,
    _selection_page,
    _selection_status,
)


class PlatformSelectionPageTest(unittest.TestCase):
    def test_stale_report_is_not_linked_as_current_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe_dir = root / "research" / "universes"
            report = (
                root
                / "research"
                / "selections"
                / "test"
                / "2026-08-15-selection.html"
            )
            universe_dir.mkdir(parents=True)
            report.parent.mkdir(parents=True)
            (universe_dir / "test.toml").write_text(
                """
schema_version = 2
universe_id = "test"
name = "测试候选池"
objective = "验证统一选择报告"
instrument_type = "etf"
horizon = "long"
theme = "test"
created_at = 2026-08-15
history_days = 120
shortlist_size = 1

[[candidates]]
symbol = "515100"
name = "候选一"
exchange = "SH"

[[candidates]]
symbol = "512890"
name = "候选二"
exchange = "SH"
""".strip(),
                encoding="utf-8",
            )
            report.write_text("<title>旧选择报告</title>", encoding="utf-8")
            requested_at = datetime(
                2026,
                8,
                15,
                14,
                0,
                tzinfo=timezone(timedelta(hours=8)),
            )
            report_path = report.relative_to(root).as_posix()
            run = {
                "universe_id": "test",
                "status": "screened",
                "requested_at": requested_at.isoformat(),
                "candidate_count": 2,
                "shortlist_count": 1,
                "report_path": report_path,
            }
            control = {"selection_runs": [run]}

            stale = requested_at.timestamp() - 60
            os.utime(report, (stale, stale))
            stale_html = _selection_page(root, control)

            self.assertIn('class="management-table"', stale_html)
            self.assertIn('data-status="screened"', stale_html)
            self.assertIn("待深度研究", stale_html)
            self.assertNotIn(f'href="../../{report_path}"', stale_html)

            current = requested_at.timestamp() + 60
            os.utime(report, (current, current))
            current_html = _selection_page(root, control)

            self.assertIn('data-status="completed"', current_html)
            self.assertIn(f'href="../../{report_path}"', current_html)

    def test_legacy_packet_only_targets_its_matching_report_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet_path = (
                root / "data" / "selections" / "latest" / "test.json"
            )
            old_report = (
                root
                / "research"
                / "selections"
                / "test"
                / "2026-08-15-selection.html"
            )
            packet_path.parent.mkdir(parents=True)
            old_report.parent.mkdir(parents=True)
            packet_path.write_text(
                json.dumps(
                    {
                        "as_of": "2026-08-16T10:00:00+08:00",
                        "summary": {
                            "candidate_count": 6,
                            "eligible": 3,
                        },
                    }
                ),
                encoding="utf-8",
            )
            old_report.write_text("<title>旧选择报告</title>", encoding="utf-8")

            run = _legacy_selection_run(root, "test")

            self.assertEqual(run["status"], "screened")
            self.assertEqual(
                run["report_path"],
                "research/selections/test/2026-08-16-selection.html",
            )
            self.assertEqual(_selection_status(root, run), "screened")

    def test_completed_run_without_report_returns_to_screened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = {
                "status": "completed",
                "report_path": (
                    "research/selections/test/2026-08-15-selection.html"
                ),
            }

            self.assertEqual(_selection_status(root, run), "screened")


if __name__ == "__main__":
    unittest.main()
