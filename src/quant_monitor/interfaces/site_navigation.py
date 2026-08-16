"""统一生成并刷新所有可浏览页面的全局导航。"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

_HEADER_PATTERN = re.compile(
    r"  <header class=\"site-header\">.*?  </header>",
    re.DOTALL,
)
_ASSET_VERSION_PATTERN = re.compile(
    r"(?P<asset>docs\.css|navigation\.js)\?v=[0-9.]+"
)
_HREF_PATTERN = re.compile(r'href="(?P<href>[^"]+)"')
ASSET_VERSION = "0.10.1"


def build_site_header(prefix: str, current: str) -> str:
    """生成只保留工作台返回路径的全局顶栏。"""

    navigation = (
        ""
        if current == "workspace"
        else f"""
      <nav class="site-nav" aria-label="全局导航">
        <a class="workspace-return" href="{prefix}index.html">返回工作台</a>
      </nav>
        """.rstrip()
    )
    return f"""
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="{prefix}index.html">Quant Monitor</a>
{navigation}
    </div>
  </header>
    """.strip("\n").rstrip()


def _current_for(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    parts = relative.parts
    if relative == Path("index.html"):
        return "workspace"
    if parts[0] == "docs":
        if relative.name == "markdown.html":
            return "reports"
        if relative.name == "capabilities.html":
            return "capabilities"
        if relative.name == "architecture.html":
            return "architecture"
        return "docs"
    if parts[:2] == ("research", "selections"):
        return "selection"
    if parts[:2] == ("research", "strategies"):
        return "strategy"
    if parts[:2] == ("research", "analysis"):
        return "analysis"
    if parts[:2] == ("research", "reports"):
        return "reports"
    if parts[:2] == ("research", "channels"):
        return "channels"
    if parts[:2] == ("research", "instruments"):
        return "instruments"
    if parts[:2] == ("research", "library"):
        return "library"
    if parts[0] == "research":
        return "research"
    if parts[:2] == ("data", "dashboard"):
        return "dashboard"
    if parts[:2] == ("data", "selections"):
        return "selection"
    if parts[:2] == ("data", "backtests"):
        return "strategy"
    if parts[:2] == ("data", "reports"):
        return "reports"
    return "workspace"


def _prefix_for(path: Path, root: Path) -> str:
    depth = len(path.relative_to(root).parent.parts)
    return "../" * depth


def _rewrite_markdown_links(content: str, path: Path, root: Path) -> str:
    prefix = _prefix_for(path, root)

    def replace(match: re.Match[str]) -> str:
        href = unescape(match.group("href"))
        parsed = urlsplit(href)
        if (
            parsed.scheme
            or parsed.netloc
            or not unquote(parsed.path).lower().endswith(".md")
        ):
            return match.group(0)
        target = (path.parent / unquote(parsed.path)).resolve()
        try:
            relative = target.relative_to(root)
        except ValueError:
            return match.group(0)
        source = quote(f"../{relative.as_posix()}", safe="/")
        fragment = (
            f"#{quote(unquote(parsed.fragment), safe='-._~')}"
            if parsed.fragment
            else ""
        )
        viewer = f"{prefix}docs/markdown.html?src={source}{fragment}"
        return f'href="{viewer}"'

    return _HREF_PATTERN.sub(replace, content)


def refresh_site_navigation(root: Path) -> tuple[Path, ...]:
    """统一现有 HTML 的导航、静态资源版本和键盘交互脚本。"""

    candidates = {
        root / "index.html",
        *root.joinpath("docs").glob("*.html"),
        *root.joinpath("research").rglob("*.html"),
        *root.joinpath("data", "dashboard").rglob("*.html"),
        *root.joinpath("data", "selections").rglob("*.html"),
        *root.joinpath("data", "backtests").rglob("*.html"),
        *root.joinpath("data", "reports").rglob("*.html"),
    }
    changed: list[Path] = []
    for path in sorted(candidates):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        prefix = _prefix_for(path, root)
        header = build_site_header(prefix, _current_for(path, root))
        updated, replacements = _HEADER_PATTERN.subn(header, content, count=1)
        if replacements != 1:
            raise ValueError(f"页面缺少唯一全局导航：{path}")
        updated = _ASSET_VERSION_PATTERN.sub(
            rf"\g<asset>?v={ASSET_VERSION}",
            updated,
        )
        updated = _rewrite_markdown_links(updated, path, root)
        if "navigation.js" not in updated:
            script = (
                f'  <script src="{prefix}docs/assets/navigation.js'
                f'?v={ASSET_VERSION}"></script>\n'
            )
            updated = updated.replace("</body>", f"{script}</body>")
        updated = "\n".join(
            line.rstrip() for line in updated.splitlines()
        ) + "\n"
        if updated != content:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return tuple(changed)
