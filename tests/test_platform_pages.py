from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
from quant_monitor.interfaces.platform_pages import (
    _legacy_selection_run,
    _selection_page,
    _selection_status,
    _strategy_page,
)


class PlatformSelectionPageTest(unittest.TestCase):
    def test_selection_page_keeps_latest_run_for_each_universe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe_dir = root / "research" / "universes"
            universe_dir.mkdir(parents=True)
            (universe_dir / "test.toml").write_text(
                """
schema_version = 2
universe_id = "test"
name = "测试候选池"
objective = "验证最新运行"
instrument_type = "etf"
history_days = 120
shortlist_size = 1

[[candidates]]
symbol = "510300"
name = "候选一"
exchange = "SH"

[[candidates]]
symbol = "512890"
name = "候选二"
exchange = "SH"
""".strip(),
                encoding="utf-8",
            )
            control = {
                "selection_runs": [
                    {
                        "universe_id": "test",
                        "requested_at": "2026-08-16T17:35:00+08:00",
                        "status": "screened",
                        "candidate_count": 12,
                        "shortlist_count": 7,
                        "report_path": "",
                    },
                    {
                        "universe_id": "test",
                        "requested_at": "2026-08-16T17:33:00+08:00",
                        "status": "screened",
                        "candidate_count": 12,
                        "shortlist_count": 0,
                        "report_path": "",
                    },
                ]
            }

            html = _selection_page(root, control)

            self.assertIn("<th>初筛合格</th>", html)
            self.assertIn("<td>12</td>\n          <td>7</td>", html)

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
symbol = "510300"
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


class PlatformStrategyPageTest(unittest.TestCase):
    def test_strategy_page_renders_unbound_draft_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text(
                """
[app]

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

[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
""".strip(),
                encoding="utf-8",
            )
            settings = load_settings(root, config_path)
            draft = StrategyRecord(
                record_id="dynamic-v1",
                profile_id="dividend_yield_dynamic_v1",
                version="1.0.0",
                name="动态股息率策略",
                symbols=("512890",),
                horizon=InvestmentHorizon.LONG,
                lifecycle=StrategyLifecycle.DRAFT,
                validation_state=ValidationState.PENDING,
                created_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                enabled_at=None,
                retired_at=None,
                thesis="估值数据不足时拒绝方向性结论",
                parameters_fingerprint="sha256:draft",
                backtest_model_id="dividend_yield_percentile_allocation",
                backtest_model_version="1.0.0",
                backtest_parameters={
                    "strategy_id": "dividend_yield_dynamic",
                    "strategy_parameters": {
                        "first_add_percentile": 0.70,
                    },
                },
            )

            html = _strategy_page(
                settings,
                StrategyCatalog(1, (draft,)),
                {"backtest_runs": []},
            )

            self.assertIn("草案未配置", html)
            self.assertIn("第一增配分位", html)
            self.assertIn("70.00%", html)
            self.assertIn("dividend_yield_dynamic", html)
            self.assertIn("分位、仓位和回撤对应表", html)
            self.assertIn("242日回撤", html)
            self.assertIn("术语速查", html)
            self.assertIn("策略预算中计划暴露", html)
            self.assertIn("查看原始参数名", html)

    def test_strategy_record_exposes_expandable_auditable_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text(
                """
[app]

[product_types.etf]
strategy_profiles = ["default"]
research_profile = "core"
notification_policy = "silent"
history_days = 300

[strategy_profiles.default]
strategy = "dividend_low_vol"
parameters = {
  attention_drawdown = -0.05,
  high_volatility = 0.25,
}

[research_profiles.core]
skill = "instrument-analyst"
sections = ["趋势"]
source_priorities = ["官方"]

[notification_policies.silent]
enabled = false
channels = []
events = []

[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
""".strip(),
                encoding="utf-8",
            )
            settings = load_settings(root, config_path)
            profile = settings.strategy_profiles["default"]
            fingerprint = strategy_profile_fingerprint(profile)
            record = StrategyRecord(
                record_id="record-v1",
                profile_id="default",
                version="1.0.0",
                name="<测试策略>",
                symbols=("510300",),
                horizon=InvestmentHorizon.LONG,
                lifecycle=StrategyLifecycle.ACTIVE,
                validation_state=ValidationState.PENDING,
                created_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
                enabled_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                retired_at=None,
                thesis="验证策略逻辑与详情来自同一事实源",
                parameters_fingerprint=fingerprint,
                backtest_model_id="attention_score_allocation",
                backtest_model_version="1.0.0",
                backtest_parameters={
                    "strategy_id": "dividend_low_vol",
                    "full_score": 68,
                    "watch_score": 52,
                    "full_weight": 1.0,
                    "watch_weight": 0.5,
                },
            )

            html = _strategy_page(
                settings,
                StrategyCatalog(1, (record,)),
                {"backtest_runs": []},
            )

            self.assertIn('<details class="strategy-record"', html)
            self.assertIn("<summary>", html)
            self.assertIn("&lt;测试策略&gt;", html)
            self.assertNotIn("<测试策略>", html)
            self.assertIn("验证策略逻辑与详情来自同一事实源", html)
            self.assertIn("关注回撤", html)
            self.assertIn("-5.00%", html)
            self.assertIn("高关注回测仓位", html)
            self.assertIn("100.00%", html)
            self.assertIn("仅用于历史模拟", html)
            self.assertIn("attention_score_allocation v1.0.0", html)
            self.assertIn(fingerprint, html)
            self.assertIn('data-lifecycle="active"', html)
            self.assertIn('data-validation="pending"', html)


if __name__ == "__main__":
    unittest.main()
