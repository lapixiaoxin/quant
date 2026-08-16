"""生成站内统一 Markdown 阅读器。"""

from __future__ import annotations

from pathlib import Path

from .site_navigation import ASSET_VERSION, build_site_header


def build_markdown_viewer() -> str:
    """生成仅从同源 `.md` 文件读取并安全渲染的静态页面。"""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Markdown 阅读 · Quant Monitor</title>
  <link rel="stylesheet" href="assets/docs.css?v={ASSET_VERSION}">
</head>
<body class="module-page module-engineering markdown-reader-page">
{build_site_header("../", "reports")}
  <main class="page reader-page">
    <header class="reader-toolbar">
      <a href="../index.html">返回工作台</a>
      <span id="reader-path">Markdown</span>
      <a id="reader-raw" href="#" hidden>查看源文件</a>
    </header>
    <article id="markdown-content" class="markdown-body" aria-live="polite">
      <p class="reader-state">正在读取...</p>
    </article>
  </main>
  <script src="assets/navigation.js?v={ASSET_VERSION}"></script>
  <script src="assets/vendor/marked.min.js?v=12.0.2"></script>
  <script src="assets/vendor/purify.min.js?v=3.1.6"></script>
  <script src="assets/markdown-viewer.js?v={ASSET_VERSION}"></script>
</body>
</html>
"""


def write_markdown_viewer(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_markdown_viewer(), encoding="utf-8")
    return path
