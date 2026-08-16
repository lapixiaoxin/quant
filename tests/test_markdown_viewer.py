from __future__ import annotations

import unittest
from pathlib import Path

from quant_monitor.interfaces.markdown_viewer import build_markdown_viewer

ROOT = Path(__file__).resolve().parents[1]


class MarkdownViewerTest(unittest.TestCase):
    def test_viewer_uses_local_parser_and_sanitizer(self) -> None:
        content = build_markdown_viewer()

        self.assertIn("assets/vendor/marked.min.js?v=12.0.2", content)
        self.assertIn("assets/vendor/purify.min.js?v=3.1.6", content)
        self.assertIn("assets/markdown-viewer.js", content)
        self.assertNotIn("https://", content)

    def test_viewer_script_restricts_and_sanitizes_source(self) -> None:
        script = (
            ROOT / "docs" / "assets" / "markdown-viewer.js"
        ).read_text(encoding="utf-8")

        self.assertIn("sourceUrl.origin !== window.location.origin", script)
        self.assertIn('endsWith(".md")', script)
        self.assertIn("window.DOMPurify.sanitize", script)
        self.assertIn('FORBID_TAGS: ["form", "iframe"', script)

    def test_vendored_dependencies_include_licenses(self) -> None:
        vendor = ROOT / "docs" / "assets" / "vendor"

        self.assertTrue((vendor / "marked.min.js").is_file())
        self.assertTrue((vendor / "marked.LICENSE.md").is_file())
        self.assertTrue((vendor / "purify.min.js").is_file())
        self.assertTrue((vendor / "dompurify.LICENSE").is_file())


if __name__ == "__main__":
    unittest.main()
