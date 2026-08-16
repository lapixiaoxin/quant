from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quant_monitor.application.notifications import (
    NotificationDeliveryError,
    NotificationService,
)
from quant_monitor.config import load_settings


class FakeChannel:
    def __init__(
        self,
        channel_id: str = "primary",
        *,
        fail: bool = False,
    ) -> None:
        self.channel_id = channel_id
        self.fail = fail
        self.messages: list[tuple[str, str]] = []

    def send(self, title: str, markdown: str) -> None:
        self.messages.append((title, markdown))
        if self.fail:
            raise RuntimeError("测试发送失败")


def settings_for(
    policy: str = "daily",
    channels: str = '["primary"]',
):
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

[notification_channels.secondary]
type = "feishu"
enabled = false

[notification_policies.daily]
enabled = true
channels = {channels}
events = ["agent_report"]
title_template = "{{symbol}} {{name}} 决策简报"

[notification_policies.silent]
enabled = false
channels = []
events = []

[[instruments]]
symbol = "510300"
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

        sent = service.send("510300", "agent_report", "报告正文")

        self.assertEqual(sent, ("primary",))
        self.assertEqual(
            channel.messages,
            [("510300 测试 ETF 决策简报", "报告正文")],
        )

    def test_rejects_unsubscribed_event(self) -> None:
        temporary, settings = settings_for()
        self.addCleanup(temporary.cleanup)
        service = NotificationService(settings, {"primary": FakeChannel()})

        with self.assertRaisesRegex(ValueError, "不接收事件"):
            service.send("510300", "base_report", "报告正文")

    def test_instrument_can_inherit_silent_policy(self) -> None:
        temporary, settings = settings_for("silent")
        self.addCleanup(temporary.cleanup)
        service = NotificationService(settings, {"primary": FakeChannel()})

        with self.assertRaisesRegex(ValueError, "未启用"):
            service.send("510300", "agent_report", "报告正文")

    def test_attempts_all_channels_and_preserves_partial_success(self) -> None:
        temporary, settings = settings_for(
            channels='["primary", "secondary"]'
        )
        self.addCleanup(temporary.cleanup)
        primary = FakeChannel(fail=True)
        secondary = FakeChannel("secondary")
        service = NotificationService(
            settings,
            {
                "primary": primary,
                "secondary": secondary,
            },
        )

        with self.assertRaises(NotificationDeliveryError) as raised:
            service.send("510300", "agent_report", "报告正文")

        self.assertEqual(raised.exception.sent_channels, ("secondary",))
        self.assertIn("primary：测试发送失败", raised.exception.failures)
        self.assertEqual(len(primary.messages), 1)
        self.assertEqual(len(secondary.messages), 1)


if __name__ == "__main__":
    unittest.main()
