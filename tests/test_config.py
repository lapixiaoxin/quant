"""研究配置不依赖特定 Agent 或自动化；引用错误仍明确失败。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quant_monitor.config import load_settings

MINIMAL = """
[[instruments]]
symbol = "601985"
name = "中国核电"
type = "stock"
"""


class ConfigTest(unittest.TestCase):
    def load(self, content: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        path = root / "config.toml"
        path.write_text(content, encoding="utf-8")
        return load_settings(root, path)

    def test_minimal_instrument_does_not_require_profiles(self):
        settings = self.load(MINIMAL)
        self.assertEqual(settings.instrument_for("601985").strategy_profile_ids, ())
        self.assertEqual(settings.research_plan_for("601985").focus, ())
        self.assertEqual(self.load("").instruments, ())

    def test_product_defaults_and_explicit_empty_override(self):
        defaults = """
[product_types.stock]
strategy_profiles = ["test"]
research_profile = "core"
history_days = 260
[strategy_profiles.test]
strategy = "dividend_low_vol"
[research_profiles.core]
focus = ["现金流"]
"""
        inherited = self.load(defaults + MINIMAL).instrument_for("601985")
        self.assertEqual(inherited.strategy_profile_ids, ("test",))
        self.assertEqual(inherited.history_days, 260)
        settings = self.load(
            defaults
            + MINIMAL
            + """
strategy_profiles = []
research_focus = ["现金流", "投产"]
history_start_date = 2025-01-01
"""
        )
        self.assertEqual(settings.instrument_for("601985").strategy_profile_ids, ())
        self.assertEqual(
            settings.research_plan_for("601985").focus,
            ("现金流", "投产"),
        )
        self.assertEqual(
            str(settings.instrument_for("601985").history_start_date),
            "2025-01-01",
        )

    def test_legacy_automation_values_are_inert(self):
        settings = self.load(
            """
[automation]
enabled = true
send = true
[remote]
enabled = true
[notification_policies.old]
channels = ["missing"]
"""
            + MINIMAL
        )
        self.assertIn("automation", settings.ignored_legacy_sections)
        self.assertFalse(hasattr(settings, "automation"))
        self.assertFalse(hasattr(settings, "remote"))

    def test_invalid_references_identity_and_dates_are_rejected(self):
        for suffix, message in (
            ('research_profile = "missing"', "研究画像"),
            ('strategy_profiles = ["missing"]', "策略画像"),
            ('history_start_date = "bad"', "history_start_date"),
            ("history_days = 1", "history_days"),
            ('exchange = "US"', "SH/SZ"),
        ):
            with (
                self.subTest(suffix=suffix),
                self.assertRaisesRegex(ValueError, message),
            ):
                self.load(MINIMAL + suffix)
        with self.assertRaisesRegex(ValueError, "重复"):
            self.load(MINIMAL + MINIMAL)
