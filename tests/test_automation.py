from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quant_monitor.application.automation import AutomationService
from quant_monitor.config import load_settings

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

[notification_channels.primary]
type = "feishu"
enabled = false

[notification_policies.daily]
enabled = true
channels = ["primary"]
events = ["scheduled_report"]

[automation]
enabled = true
mode = "traecli"
send = true
fallback_to_base = true

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
        return Path("packet.json"), {
            "as_of": "2026-08-15T14:00:00+08:00",
            "symbol": symbol,
        }


class FakeRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save_base_report(self, symbol: str, as_of: str, content: str) -> Path:
        path = self.root / f"{symbol}-base.md"
        path.write_text(f"{as_of}\n{content}", encoding="utf-8")
        return path


class FakeNotifications:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, str]] = []

    def send(self, symbol: str, event: str, markdown: str):
        self.calls.append((symbol, event, markdown))
        if self.fail:
            raise RuntimeError("飞书暂时不可用")
        return ("primary",)


class FakeRunner:
    def __init__(self, root: Path, available: bool) -> None:
        self.available = available
        self.path = root / "515100-research.md"
        self.calls: list[tuple[str, bool, Path | None]] = []

    def is_available(self) -> bool:
        return self.available

    def run(
        self,
        symbol: str,
        *,
        send: bool,
        analysis_request_path: Path | None = None,
    ) -> Path:
        self.calls.append((symbol, send, analysis_request_path))
        self.path.write_text("完整研究", encoding="utf-8")
        return self.path


class AutomationTest(unittest.TestCase):
    def _service(
        self,
        root: Path,
        runner: FakeRunner,
        *,
        notification_failure: bool = False,
    ):
        config_path = root / "config.toml"
        config_path.write_text(CONFIG, encoding="utf-8")
        settings = load_settings(root, config_path)
        monitoring = FakeMonitoring()
        notifications = FakeNotifications(fail=notification_failure)
        service = AutomationService(
            settings=settings,
            monitoring=monitoring,
            repository=FakeRepository(root),
            notifications=notifications,
            agent_runner=runner,
            report_renderer=lambda packet: f"基础分析 {packet['symbol']}",
        )
        return service, monitoring, notifications

    def test_uses_headless_agent_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FakeRunner(root, available=True)
            service, monitoring, notifications = self._service(root, runner)

            result = service.run("515100")

            self.assertEqual(result.mode, "traecli")
            self.assertEqual(runner.calls, [("515100", False, None)])
            self.assertEqual(monitoring.calls, [])
            self.assertEqual(
                notifications.calls[0][:2],
                ("515100", "scheduled_report"),
            )
            self.assertEqual(result.sent_channels, ("primary",))

    def test_falls_back_to_base_and_sends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FakeRunner(root, available=False)
            service, monitoring, notifications = self._service(root, runner)

            result = service.run("515100")

            self.assertEqual(result.mode, "base")
            self.assertTrue(result.fallback_used)
            self.assertEqual(monitoring.calls, ["515100"])
            self.assertEqual(notifications.calls[0][:2], ("515100", "scheduled_report"))

    def test_send_override_disables_notification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FakeRunner(root, available=False)
            service, _, notifications = self._service(root, runner)

            result = service.run("515100", mode="base", send=False)

            self.assertEqual(result.sent_channels, ())
            self.assertEqual(notifications.calls, [])

    def test_caller_can_select_notification_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FakeRunner(root, available=False)
            service, _, notifications = self._service(root, runner)

            service.run(
                "515100",
                mode="base",
                send=True,
                event="base_report",
            )

            self.assertEqual(
                notifications.calls[0][1],
                "base_report",
            )

    def test_delivery_failure_keeps_generated_report_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FakeRunner(root, available=False)
            service, _, _ = self._service(
                root,
                runner,
                notification_failure=True,
            )

            result = service.run("515100", mode="base", send=True)

            self.assertTrue(result.report_path.exists())
            self.assertEqual(result.sent_channels, ())
            self.assertEqual(
                result.delivery_errors,
                ("飞书暂时不可用",),
            )

    def test_standard_agent_request_generates_then_application_sends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FakeRunner(root, available=True)
            service, _, notifications = self._service(root, runner)
            request_path = root / "data" / "analysis" / "request.json"

            result = service.run(
                "515100",
                analysis_request_path=request_path,
            )

            self.assertEqual(
                runner.calls,
                [("515100", False, request_path)],
            )
            self.assertEqual(
                notifications.calls[0][:2],
                ("515100", "scheduled_report"),
            )
            self.assertEqual(result.sent_channels, ("primary",))


if __name__ == "__main__":
    unittest.main()
