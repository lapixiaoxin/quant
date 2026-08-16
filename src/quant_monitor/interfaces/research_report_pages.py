"""把标的 Markdown 报告转换为可扩展的独立 HTML 页面。"""

from __future__ import annotations

from html import escape
from pathlib import Path

from .site_navigation import ASSET_VERSION, build_site_header


def _markdown_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def report_html_path(markdown_path: Path) -> Path:
    """返回 Markdown 标的报告的同目录 HTML 页面路径。"""

    return markdown_path.with_suffix(".html")


def build_research_report_page(
    markdown_path: Path,
    root: Path,
) -> str:
    """生成固定数据源的报告页，为后续图表组件预留挂载区。"""

    relative = markdown_path.relative_to(root)
    title = _markdown_title(markdown_path)
    symbol = markdown_path.stem.split("-", 1)[0]
    report_date = (
        relative.parts[2]
        if len(relative.parts) > 2
        else "未标注日期"
    )
    prefix = "../" * len(relative.parent.parts)
    source = escape(markdown_path.name, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · Quant Monitor</title>
  <link rel="stylesheet"
    href="{prefix}docs/assets/docs.css?v={ASSET_VERSION}">
</head>
<body class="module-page module-reports research-report-page"
  data-markdown-source="{source}">
{build_site_header(prefix, "reports")}
  <main class="page reader-page">
    <header class="reader-toolbar">
      <a href="{prefix}research/reports/index.html">返回报告中心</a>
      <span>{escape(symbol)} · {escape(report_date)}</span>
    </header>
    <section id="report-visuals" class="report-visuals"
      data-report-symbol="{escape(symbol, quote=True)}"
      data-report-date="{escape(report_date, quote=True)}" hidden></section>
    <article id="markdown-content" class="markdown-body" aria-live="polite">
      <p class="reader-state">正在读取...</p>
    </article>
  </main>
  <script src="{prefix}docs/assets/navigation.js?v={ASSET_VERSION}"></script>
  <script src="{prefix}docs/assets/vendor/marked.min.js?v=12.0.2"></script>
  <script src="{prefix}docs/assets/vendor/purify.min.js?v=3.1.6"></script>
  <script src="{prefix}docs/assets/markdown-viewer.js?v={ASSET_VERSION}"></script>
</body>
</html>
"""


def write_research_report_pages(root: Path) -> tuple[Path, ...]:
    """为所有标的 Markdown 报告生成同名 HTML 页面。"""

    pages: list[Path] = []
    for markdown_path in sorted(
        root.joinpath("data", "reports").rglob("*.md")
    ):
        output = report_html_path(markdown_path)
        output.write_text(
            build_research_report_page(markdown_path, root),
            encoding="utf-8",
        )
        pages.append(output)
    return tuple(pages)
