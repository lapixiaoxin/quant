from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted(
    [
        *ROOT.joinpath("docs").glob("*.html"),
        *ROOT.joinpath("research").rglob("*.html"),
    ]
)
EXPECTED_DESTINATIONS = {
    ROOT / "docs" / "index.html",
    ROOT / "docs" / "install.html",
    ROOT / "docs" / "operations.html",
    ROOT / "docs" / "capabilities.html",
    ROOT / "docs" / "architecture.html",
    ROOT / "docs" / "refactor-report.html",
    ROOT / "research" / "index.html",
    ROOT / "research" / "instruments" / "index.html",
    ROOT / "research" / "library" / "index.html",
    ROOT / "research" / "methods" / "storage-backtesting.html",
    ROOT / "research" / "templates" / "discussion-report.html",
    ROOT / "data" / "dashboard" / "index.html",
}


class NavigationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_navigation = False
        self.navigation_depth = 0
        self.navigation_count = 0
        self.hrefs: list[str] = []
        self.current_links = 0
        self.current_groups = 0
        self.summaries: list[str] = []
        self._summary_text: list[str] | None = None
        self.stylesheets: list[str] = []
        self.scripts: list[str] = []

    @staticmethod
    def _attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value or "" for key, value in attrs}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = self._attributes(attrs)
        classes = values.get("class", "").split()
        if tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.append(values.get("href", ""))
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])
        if tag == "nav" and "site-nav" in classes:
            self.in_navigation = True
            self.navigation_depth = 1
            self.navigation_count += 1
            return
        if not self.in_navigation:
            return
        self.navigation_depth += 1
        if tag == "a":
            self.hrefs.append(values.get("href", ""))
            if values.get("aria-current") == "page":
                self.current_links += 1
        elif tag == "details" and "is-current" in classes:
            self.current_groups += 1
        elif tag == "summary":
            self._summary_text = []

    def handle_endtag(self, tag: str) -> None:
        if not self.in_navigation:
            return
        if tag == "summary" and self._summary_text is not None:
            self.summaries.append("".join(self._summary_text).strip())
            self._summary_text = None
        self.navigation_depth -= 1
        if self.navigation_depth == 0:
            self.in_navigation = False

    def handle_data(self, data: str) -> None:
        if self._summary_text is not None:
            self._summary_text.append(data)


class DocumentationNavigationTest(unittest.TestCase):
    def test_all_pages_share_one_predictable_global_navigation(self) -> None:
        self.assertEqual(len(PAGES), 11)
        for page in PAGES:
            with self.subTest(page=page.relative_to(ROOT)):
                parser = NavigationParser()
                parser.feed(page.read_text(encoding="utf-8"))

                destinations = {
                    (page.parent / urlsplit(href).path).resolve()
                    for href in parser.hrefs
                    if href and not urlsplit(href).scheme
                }
                self.assertEqual(parser.navigation_count, 1)
                self.assertEqual(
                    parser.summaries,
                    ["使用指南", "系统设计", "研究工作台"],
                )
                self.assertEqual(destinations, EXPECTED_DESTINATIONS)
                self.assertEqual(parser.current_links, 1)
                expected_groups = 0 if page == ROOT / "docs" / "index.html" else 1
                self.assertEqual(parser.current_groups, expected_groups)
                self.assertEqual(len(parser.stylesheets), 1)
                self.assertIn("docs.css?v=0.5.1", parser.stylesheets[0])
                self.assertEqual(len(parser.scripts), 1)
                self.assertIn("navigation.js?v=0.5.1", parser.scripts[0])


if __name__ == "__main__":
    unittest.main()
