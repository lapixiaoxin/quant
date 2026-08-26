from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from quant_monitor.config import load_settings
from quant_monitor.domain.models import InstrumentType

BASE_CONFIG = """
[app]
timezone = "Asia/Shanghai"

[product_types.etf]
strategy_profiles = ["dividend_default"]
research_profile = "etf_core"
notification_policy = "daily"
history_days = 500

[strategy_profiles.dividend_default]
strategy = "dividend_low_vol"
parameters = { deep_drawdown = -0.08 }

[strategy_profiles.custom]
strategy = "dividend_low_vol"
parameters = { deep_drawdown = -0.10 }

[research_profiles.etf_core]
skill = "instrument-analyst"
sections = ["趋势", "基本面"]
focus = ["大类关注"]
source_priorities = ["官方来源"]
max_sources = 4
instructions = ["大类指令"]

[research_profiles.custom]
skill = "instrument-analyst"
sections = ["自定义"]
focus = ["自定义关注"]
source_priorities = ["指定来源"]
max_sources = 2
instructions = ["自定义指令"]

[notification_channels.primary]
type = "feishu"
enabled = false
mode = "app"
receive_id = "oc_target"
receive_id_type = "chat_id"

[notification_policies.daily]
enabled = true
channels = ["primary"]
events = ["agent_report"]
title_template = "{symbol} 日报"

[notification_policies.silent]
enabled = false
channels = []
events = []
"""


class ConfigTest(unittest.TestCase):
    def _load(self, instrument_config: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        path = root / "settings.toml"
        path.write_text(BASE_CONFIG + instrument_config, encoding="utf-8")
        return load_settings(root, path)

    def test_allows_configuration_without_preloaded_instruments(self) -> None:
        settings = self._load("")

        self.assertEqual(settings.instruments, ())
        self.assertEqual(settings.enabled_instruments, ())

    def test_inherits_product_type_defaults(self) -> None:
        settings = self._load(
            """
[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
research_focus = ["标的关注"]
research_instructions = ["标的指令"]
"""
        )

        instrument = settings.instrument_for("510300")
        plan = settings.research_plan_for("510300")
        self.assertEqual(instrument.instrument_type, InstrumentType.ETF)
        self.assertEqual(
            instrument.strategy_profile_ids,
            ("dividend_default",),
        )
        self.assertEqual(instrument.notification_policy_id, "daily")
        self.assertEqual(instrument.history_days, 500)
        self.assertEqual(plan.focus, ("大类关注", "标的关注"))
        self.assertEqual(plan.instructions, ("大类指令", "标的指令"))

    def test_instrument_can_override_each_behavior(self) -> None:
        settings = self._load(
            """
[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
strategy_profiles = ["dividend_default", "custom"]
research_profile = "custom"
notification_policy = "silent"
history_days = 260
history_start_date = 2024-05-15
"""
        )

        instrument = settings.instrument_for("510300")
        self.assertEqual(
            instrument.strategy_profile_ids,
            ("dividend_default", "custom"),
        )
        self.assertEqual(instrument.research_profile_id, "custom")
        self.assertEqual(instrument.notification_policy_id, "silent")
        self.assertEqual(instrument.history_days, 260)
        self.assertEqual(instrument.history_start_date, date(2024, 5, 15))

    def test_rejects_invalid_history_start_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "history_start_date"):
            self._load(
                """
[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
history_start_date = "2024/05/15"
"""
            )

    def test_rejects_missing_product_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "product_types.stock"):
            self._load(
                """
[[instruments]]
symbol = "600000"
name = "测试股票"
type = "stock"
"""
            )

    def test_rejects_unknown_profile_reference(self) -> None:
        with self.assertRaisesRegex(ValueError, "不存在的研究画像"):
            self._load(
                """
[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
research_profile = "missing"
"""
            )

    def test_rejects_unknown_channel_reference(self) -> None:
        broken = BASE_CONFIG.replace(
            'channels = ["primary"]',
            'channels = ["missing"]',
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "settings.toml"
            path.write_text(
                broken
                + """
[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "不存在的通道"):
                load_settings(root, path)

    def test_rejects_unknown_title_template_field(self) -> None:
        broken = BASE_CONFIG.replace(
            'title_template = "{symbol} 日报"',
            'title_template = "{unknown} 日报"',
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "settings.toml"
            path.write_text(
                broken
                + """
[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "未知字段"):
                load_settings(root, path)

    def test_automation_and_remote_default_to_disabled(self) -> None:
        settings = self._load(
            """
[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
"""
        )

        self.assertFalse(settings.automation.enabled)
        self.assertEqual(settings.automation.mode, "base")
        self.assertFalse(settings.remote.enabled)

    def test_remote_requires_allowlist_when_enabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "allowed_sender_ids"):
            self._load(
                """
[remote]
enabled = true

[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
"""
            )

    def test_remote_can_inherit_notification_chat_target(self) -> None:
        settings = self._load(
            """
[remote]
enabled = true
allowed_channel_targets = ["primary"]

[[instruments]]
symbol = "510300"
name = "测试 ETF"
type = "etf"
"""
        )

        self.assertTrue(settings.remote.is_allowed("other", "oc_target"))
        self.assertEqual(
            settings.remote.allowed_channel_targets,
            ("primary",),
        )


if __name__ == "__main__":
    unittest.main()
