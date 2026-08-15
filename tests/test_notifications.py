from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quant_monitor.application.notifications import NotificationService
from quant_monitor.config import load_settings


class FakeChannel:
    channel_id = "primary"

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send(self, title: str, markdown: str) -> None:
        self.messages.append((title, markdown))


def settings_for(policy: str = "daily"):
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    path = root / "settings.toml"
    path.write_text(
        f"""
[app]

[product_types.etf]
strategy_profiles = ["dividend_default"]
research_profile = "core"
notification_policy = "{policy}"
history_days = 500

[strategy_profiles.dividend_default]
strategy = "dividend_low_vol"

[research_profiles.core]
skill = "instrument-analyst"
sections = ["趋势"]
source_priorities = ["官方来源"]

[notification_channels.primary]
type = "feishu"
enabled = false

[notification_policies.daily]
enabled = true
channels = ["primary"]
events = ["agent_report"]
title_template = "{{symbol}} {{name}} 决策简报"

[notification_policies.silent]
enabled = false
channels = []
events = []

[[instruments]]
symbol = "515100"
name = "测试 ETF"
type = "etf"
""",
        encoding="utf-8",
    )
    return temporary, load_settings(root, path)


class NotificationTest(unittest.TestCase):
    def test_routes_event_and_renders_title(self) -> None:
        temporary, settings = settings_for()
        self.addCleanup(temporary.cleanup)
        channel = FakeChannel()
        service = NotificationService(settings, {"primary": channel})

        sent = service.send("515100", "agent_report", "报告正文")

        self.assertEqual(sent, ("primary",))
        self.assertEqual(
            channel.messages,
            [("515100 测试 ETF 决策简报", "报告正文")],
        )

    def test_rejects_unsubscribed_event(self) -> None:
        temporary, settings = settings_for()
        self.addCleanup(temporary.cleanup)
        service = NotificationService(settings, {"primary": FakeChannel()})

        with self.assertRaisesRegex(ValueError, "不接收事件"):
            service.send("515100", "base_report", "报告正文")

    def test_instrument_can_inherit_silent_policy(self) -> None:
        temporary, settings = settings_for("silent")
        self.addCleanup(temporary.cleanup)
        service = NotificationService(settings, {"primary": FakeChannel()})

        with self.assertRaisesRegex(ValueError, "未启用"):
            service.send("515100", "agent_report", "报告正文")


if __name__ == "__main__":
    unittest.main()
