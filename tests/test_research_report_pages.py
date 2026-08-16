from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quant_monitor.interfaces.research_report_pages import (
    build_research_report_page,
    report_html_path,
    write_research_report_pages,
)


class ResearchReportPagesTest(unittest.TestCase):
    def test_generates_html_companion_for_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = (
                root
                / "data"
                / "reports"
                / "2026-08-16"
                / "510300-research.md"
            )
            source.parent.mkdir(parents=True)
            source.write_text("# 510300 研究报告\n", encoding="utf-8")

            pages = write_research_report_pages(root)
            output = report_html_path(source)
            content = output.read_text(encoding="utf-8")

            self.assertEqual(pages, (output,))
            self.assertIn("<title>510300 研究报告", content)
            self.assertIn(
                'data-markdown-source="510300-research.md"',
                content,
            )
            self.assertIn('id="report-visuals"', content)
            self.assertIn('data-report-symbol="510300"', content)

    def test_report_page_uses_local_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "data" / "reports" / "2026-08-16" / "test.md"
            source.parent.mkdir(parents=True)
            source.write_text("# 测试报告\n", encoding="utf-8")

            content = build_research_report_page(source, root)

            self.assertIn("docs/assets/vendor/marked.min.js", content)
            self.assertIn("docs/assets/vendor/purify.min.js", content)
            self.assertNotIn("https://", content)


if __name__ == "__main__":
    unittest.main()
