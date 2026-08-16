from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_monitor.interfaces.portal import (
    build_portal,
    discover_portal_entries,
)
from quant_monitor.interfaces.research_report_pages import (
    write_research_report_pages,
)


class PortalTest(unittest.TestCase):
    def test_discovers_readable_assets_and_excludes_raw_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            selection = root / "research" / "selections" / "test"
            library = root / "research" / "library"
            reports = root / "data" / "reports" / "2026-08-15"
            snapshots = root / "data" / "snapshots" / "2026-08-15"
            universe = root / "research" / "universes"
            for path in (
                docs,
                selection,
                library,
                reports,
                snapshots,
                universe,
            ):
                path.mkdir(parents=True)
            (docs / "index.html").write_text(
                "<title>文档中心</title>",
                encoding="utf-8",
            )
            (selection / "2026-08-15-selection.html").write_text(
                "<title>测试候选 &amp; 报告</title>",
                encoding="utf-8",
            )
            (reports / "515100-research.md").write_text(
                "# 515100 研究简报\n",
                encoding="utf-8",
            )
            (library / "method.html").write_text(
                "<title>测试研究经验</title>",
                encoding="utf-8",
            )
            (universe / "test.toml").write_text(
                'name = "测试候选池"\n',
                encoding="utf-8",
            )
            (snapshots / "raw.json").write_text(
                '{"secret": "不得进入目录"}',
                encoding="utf-8",
            )
            (root / "data" / "history").mkdir(parents=True)
            (root / "data" / "history" / "market.sqlite3").touch()
            write_research_report_pages(root)

            entries = discover_portal_entries(root)
            content = build_portal(
                root,
                generated_at=datetime(2026, 8, 15, 14, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(len(entries), 3)
            self.assertIn("测试候选 &amp; 报告", content)
            self.assertIn("515100 研究简报", content)
            self.assertIn("测试研究经验", content)
            self.assertIn(
                'href="data/reports/2026-08-15/515100-research.html"',
                content,
            )
            self.assertNotIn(
                'href="data/reports/2026-08-15/515100-research.md"',
                content,
            )
            self.assertNotIn("测试候选池", content)
            self.assertNotIn("文档中心", content)
            self.assertNotIn("raw.json", content)
            self.assertNotIn("market.sqlite3", content)
            self.assertNotIn("不得进入目录", content)

    def test_root_portal_has_stable_secondary_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "index.html").write_text(
                "<title>文档中心</title>",
                encoding="utf-8",
            )

            content = build_portal(root)

            self.assertIn('href="data/dashboard/index.html"', content)
            self.assertIn('href="research/selections/index.html"', content)
            self.assertIn('href="research/index.html"', content)
            self.assertIn(
                'href="docs/markdown.html?src=../AGENTS.md"',
                content,
            )
            self.assertNotIn('href="docs/index.html"', content)
            self.assertNotIn('class="site-nav"', content)


if __name__ == "__main__":
    unittest.main()
