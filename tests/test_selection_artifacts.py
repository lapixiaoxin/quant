from __future__ import annotations

import unittest
from pathlib import Path

from quant_monitor.infrastructure.selection_config import load_selection_universe

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = (
    ROOT / "research" / "universes" / "dividend-low-vol-100-etf.toml"
)
REPORT_PATH = (
    ROOT
    / "research"
    / "selections"
    / "dividend-low-vol-100-etf"
    / "2026-08-15-selection.html"
)


class SelectionArtifactTest(unittest.TestCase):
    def test_deep_report_uses_current_comparable_facts(self) -> None:
        universe = load_selection_universe(UNIVERSE_PATH)
        report = REPORT_PATH.read_text(encoding="utf-8")

        self.assertEqual(universe.horizon.value, "long")
        self.assertEqual(universe.theme, "dividend-low-vol")
        self.assertEqual(universe.created_at.isoformat(), "2026-08-15")
        self.assertIn("显性持续费率", report)
        self.assertNotIn("年综合费率", report)
        self.assertNotIn("低费率产品可能在复制精度上做了取舍", report)
        self.assertNotIn("<strong>首选：", report)
        self.assertNotIn("每年定期调整一次", report)
        self.assertNotIn("低频元数据截至2026-08-15", report)
        self.assertNotIn("主仓", report)
        self.assertNotIn("存续风险极低", report)
        self.assertNotIn("冲击成本极高", report)
        self.assertNotIn("行业传统费率", report)
        self.assertIn("股息率 / 过去一年波动率", report)
        self.assertIn("每季度调整一次", report)
        self.assertIn("930955hbook.pdf", report)
        for candidate in universe.candidates[:3]:
            with self.subTest(symbol=candidate.symbol):
                metadata = candidate.metadata
                self.assertIn(candidate.symbol, report)
                self.assertEqual(
                    metadata.as_of.isoformat(),
                    "2026-06-29",
                )
                self.assertIn(
                    f"{metadata.tracking_error_pct:.2f}%",
                    report,
                )
                self.assertIn(
                    metadata.tracking_error_as_of.isoformat(),
                    report,
                )

    def test_deep_report_keeps_investment_boundary_visible(self) -> None:
        report = REPORT_PATH.read_text(encoding="utf-8")

        self.assertIn("不构成任何投资建议", report)
        self.assertIn("自动交易指令", report)
        self.assertIn("适用条件", report)
        self.assertIn("数据缺口", report)
        self.assertIn("失效条件", report)


if __name__ == "__main__":
    unittest.main()
