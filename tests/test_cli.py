"""CLI 集成边界：不联网验证探索、失败状态与已移除命令。"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_monitoring import FakeMarketData, market_bundle

from quant_monitor.infrastructure.control_repository import SQLiteControlPlaneRepository
from quant_monitor.interfaces.cli import _parser, main

CONFIG = """
[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
"""


class CLITest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "config").mkdir()
        self.config = self.root / "config/config.toml"
        self.config.write_text(CONFIG, encoding="utf-8")

    def run_cli(self, *arguments):
        output = io.StringIO()
        with (
            patch.dict("os.environ", {"QUANT_MONITOR_ROOT": str(self.root)}),
            patch("sys.argv", ["quant", *arguments]),
            redirect_stdout(output),
            redirect_stderr(output),
        ):
            result = main()
        return result, output.getvalue()

    def test_exploration_ignores_broken_unrelated_catalog(self):
        catalog = self.root / "research/strategies/catalog.toml"
        catalog.parent.mkdir(parents=True)
        catalog.write_text("this is invalid TOML", encoding="utf-8")
        provider = FakeMarketData(market_bundle())
        with patch(
            "quant_monitor.interfaces.cli.FallbackMarketDataProvider",
            return_value=provider,
        ):
            status, output = self.run_cli("prepare", "--symbol", "510300")
        self.assertEqual(status, 0, output)
        self.assertEqual(len(provider.calls), 1)
        packet = json.loads((self.root / "data/latest/510300.json").read_text())
        self.assertEqual(packet["schema_version"], 5)
        self.assertEqual(packet["assessments"], [])
        self.assertEqual(list(self.root.rglob("*.html")), [])
        self.assertEqual(self.run_cli("base-report", "--symbol", "510300")[0], 0)

    def test_partial_analysis_has_nonzero_exit_and_keeps_success(self):
        self.config.write_text(
            CONFIG
            + """
[[instruments]]
symbol = "510720"
name = "第二只 ETF"
type = "etf"
""",
            encoding="utf-8",
        )

        class PartialMarketData(FakeMarketData):
            def fetch(self, instrument, limit):
                if instrument.symbol == "510720":
                    raise ValueError("数据源不可用")
                return super().fetch(instrument, limit)

        with patch(
            "quant_monitor.interfaces.cli.FallbackMarketDataProvider",
            return_value=PartialMarketData(market_bundle()),
        ):
            status, output = self.run_cli("analyze", "--all")
        self.assertEqual(status, 1)
        self.assertIn("510720：数据源不可用", output)
        snapshot = SQLiteControlPlaneRepository(
            self.root / "data/control/research.sqlite3",
        ).export_snapshot()
        self.assertEqual(snapshot["analysis_runs"][0]["status"], "partial")
        self.assertEqual(len(snapshot["reports"]), 1)

    def test_removed_commands_and_unknown_symbols_fail(self):
        for command in (
            "daily",
            "automate",
            "site",
            "dashboard",
            "listen",
            "send-report",
        ):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                _parser().parse_args([command])
            self.assertEqual(error.exception.code, 2)
        status, output = self.run_cli("history", "--symbol", "999999")
        self.assertEqual(status, 1)
        self.assertIn("不存在标的", output)

    def test_doctor_accepts_empty_strategy_catalog(self):
        catalog = self.root / "research/strategies/catalog.toml"
        catalog.parent.mkdir(parents=True)
        catalog.write_text("schema_version = 1\n", encoding="utf-8")
        status, output = self.run_cli("doctor")
        self.assertEqual(status, 0, output)
