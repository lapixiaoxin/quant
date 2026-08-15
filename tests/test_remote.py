from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from quant_monitor.config import load_settings
from quant_monitor.interfaces.remote import RemoteCommandRouter

CONFIG = """
[app]

[product_types.etf]
strategy_profiles = ["default"]
research_profile = "core"
notification_policy = "daily"
history_days = 100

[strategy_profiles.default]
strategy = "dividend_low_vol"

[research_profiles.core]
skill = "instrument-analyst"
sections = ["趋势"]
source_priorities = ["官方"]

[notification_policies.daily]
enabled = true
channels = []
events = ["scheduled_report"]

[automation]
enabled = true
mode = "traecli"
send = true

[remote]
enabled = true
prefix = "/quant"
allowed_sender_ids = ["ou_allowed"]
allowed_chat_ids = ["oc_allowed"]

[[instruments]]
symbol = "515100"
name = "测试 ETF"
type = "etf"
"""


class FakeMonitoring:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def prepare(self, symbol: str):
        self.calls.append(symbol)
        return Path("data/latest") / f"{symbol}.json", {}


class FakeAutomation:
    def __init__(self) -> None:
        self.calls: list[
            tuple[str, str | None, bool | None, str]
        ] = []

    def run(
        self,
        symbol: str,
        *,
        mode: str | None = None,
        send: bool | None = None,
        event: str = "scheduled_report",
    ):
        self.calls.append((symbol, mode, send, event))
        return SimpleNamespace(
            mode=mode or "traecli",
            report_path=Path("report.md"),
            fallback_used=False,
        )


class FakeRepository:
    def list_latest_packets(self):
        return []


class RemoteTest(unittest.TestCase):
    def _router(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        path = root / "config.toml"
        path.write_text(CONFIG, encoding="utf-8")
        settings = load_settings(root, path)
        monitoring = FakeMonitoring()
        automation = FakeAutomation()
        router = RemoteCommandRouter(
            settings,
            monitoring,
            automation,
            FakeRepository(),
        )
        return settings, router, monitoring, automation

    def test_allowlist_matches_sender_or_chat(self) -> None:
        settings, _, _, _ = self._router()

        self.assertTrue(settings.remote.is_allowed("ou_allowed", "other"))
        self.assertTrue(settings.remote.is_allowed("other", "oc_allowed"))
        self.assertFalse(settings.remote.is_allowed("other", "other"))

    def test_analyze_uses_configured_automation(self) -> None:
        _, router, _, automation = self._router()

        response = router.handle("/quant analyze 515100")

        self.assertIn("分析完成", response or "")
        self.assertEqual(
            automation.calls,
            [("515100", None, True, "agent_report")],
        )

    def test_base_forces_deterministic_mode(self) -> None:
        _, router, _, automation = self._router()

        response = router.handle("/quant base")

        self.assertIn("基础分析完成", response or "")
        self.assertEqual(
            automation.calls,
            [("515100", "base", True, "base_report")],
        )

    def test_unknown_command_never_becomes_shell(self) -> None:
        _, router, monitoring, automation = self._router()

        with self.assertRaisesRegex(ValueError, "未知命令"):
            router.handle("/quant rm -rf /")

        self.assertEqual(monitoring.calls, [])
        self.assertEqual(automation.calls, [])

    def test_unrelated_message_is_ignored(self) -> None:
        _, router, _, _ = self._router()

        self.assertIsNone(router.handle("你好"))


if __name__ == "__main__":
    unittest.main()
