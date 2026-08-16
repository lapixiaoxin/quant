from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted(
    {
        ROOT / "index.html",
        *ROOT.joinpath("docs").glob("*.html"),
        *ROOT.joinpath("research").rglob("*.html"),
        *ROOT.joinpath("data", "dashboard").rglob("*.html"),
        *ROOT.joinpath("data", "selections").rglob("*.html"),
        *ROOT.joinpath("data", "backtests").rglob("*.html"),
    }
)
EXPECTED_DESTINATIONS = {
    ROOT / "index.html",
    ROOT / "research" / "selections" / "index.html",
    ROOT / "research" / "strategies" / "index.html",
    ROOT / "research" / "analysis" / "index.html",
    ROOT / "research" / "reports" / "index.html",
    ROOT / "research" / "index.html",
    ROOT / "research" / "instruments" / "index.html",
    ROOT / "research" / "library" / "index.html",
    ROOT / "research" / "channels" / "index.html",
    ROOT / "docs" / "index.html",
    ROOT / "docs" / "capabilities.html",
    ROOT / "docs" / "architecture.html",
    ROOT / "data" / "dashboard" / "index.html",
}


class NavigationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_navigation = False
        self.navigation_depth = 0
        self.navigation_count = 0
        self.hrefs: list[str] = []
        self.all_hrefs: list[str] = []
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
        if tag == "a" and values.get("href"):
            self.all_hrefs.append(values["href"])
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
        self.assertGreaterEqual(len(PAGES), 20)
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
                    ["研究流程", "资产与渠道", "系统"],
                )
                self.assertEqual(destinations, EXPECTED_DESTINATIONS)
                self.assertEqual(parser.current_links, 1)
                ungrouped_pages = {
                    ROOT / "index.html",
                    ROOT / "data" / "dashboard" / "index.html",
                }
                expected_groups = 0 if page in ungrouped_pages else 1
                self.assertEqual(parser.current_groups, expected_groups)
                self.assertEqual(len(parser.stylesheets), 1)
                self.assertIn("docs.css?v=0.9.1", parser.stylesheets[0])
                navigation_scripts = [
                    item for item in parser.scripts
                    if "navigation.js" in item
                ]
                self.assertEqual(len(navigation_scripts), 1)
                self.assertIn(
                    "navigation.js?v=0.9.1",
                    navigation_scripts[0],
                )

    def test_all_local_page_links_resolve(self) -> None:
        for page in PAGES:
            with self.subTest(page=page.relative_to(ROOT)):
                parser = NavigationParser()
                parser.feed(page.read_text(encoding="utf-8"))
                missing: list[str] = []
                for href in parser.all_hrefs:
                    parsed = urlsplit(href)
                    if parsed.scheme or not parsed.path:
                        continue
                    target = (
                        page.parent / unquote(parsed.path)
                    ).resolve()
                    if not target.exists():
                        missing.append(href)
                self.assertEqual(missing, [])

    def test_escape_can_visually_close_a_focused_dropdown(self) -> None:
        stylesheet = (ROOT / "docs" / "assets" / "docs.css").read_text(
            encoding="utf-8"
        )
        script = (ROOT / "docs" / "assets" / "navigation.js").read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            ".nav-dropdown:focus-within > .nav-menu",
            stylesheet,
        )
        self.assertNotIn(
            ".nav-dropdown:hover > .nav-menu",
            stylesheet,
        )
        self.assertIn('event.key !== "Escape"', script)
        self.assertIn("closeDropdown(activeDropdown, true)", script)


if __name__ == "__main__":
    unittest.main()
