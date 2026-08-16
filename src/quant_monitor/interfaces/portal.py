"""生成根路径研究工作台和可浏览内容目录。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote

from .site_navigation import ASSET_VERSION, build_site_header

_DATE_PATTERN = re.compile(r"20\d{2}-\d{2}-\d{2}")
_CATEGORY_ORDER = (
    "标的报告",
    "选择报告",
    "候选初筛",
    "回测报告",
    "标的档案",
    "研究经验",
)
_ENGINEERING_DOCUMENTS = (
    ("工程约束", "AGENTS.md"),
    ("使用说明", "README.md"),
    ("能力边界", "capabilities.md"),
    ("安装部署", "install.md"),
    ("架构设计", "docs/architecture.md"),
    ("数据目录", "data/README.md"),
    ("研究归档", "research/README.md"),
)


@dataclass(frozen=True)
class PortalEntry:
    """工作台中的一个可浏览资产。"""

    title: str
    href: str
    category: str
    published: str


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self._parts).strip()


def _html_title(path: Path) -> str:
    parser = _TitleParser()
    parser.feed(path.read_text(encoding="utf-8"))
    title = parser.title or path.stem
    suffix = " · Quant Monitor"
    return title[:-len(suffix)] if title.endswith(suffix) else title


def _category_for(relative: Path) -> str | None:
    parts = relative.parts
    if relative.suffix == ".html":
        if parts[:2] == ("data", "reports"):
            return "标的报告"
        if parts[:2] == ("data", "dashboard"):
            return None
        if parts[:3] == ("data", "selections", "latest"):
            return "候选初筛"
        if parts[:2] == ("data", "backtests"):
            return "回测报告"
        if parts[:2] == ("research", "selections") and relative.name != "index.html":
            return "选择报告"
        if parts[:2] == ("research", "private"):
            return "标的档案"
        if parts[:2] == ("research", "library") and relative.name != "index.html":
            return "研究经验"
    return None


def _entry(root: Path, path: Path) -> PortalEntry | None:
    relative = path.relative_to(root)
    category = _category_for(relative)
    if category is None:
        return None
    title = _html_title(path)
    date_match = _DATE_PATTERN.search(relative.as_posix())
    return PortalEntry(
        title=title,
        href=quote(relative.as_posix()),
        category=category,
        published=date_match.group(0) if date_match else "持续更新",
    )


def discover_portal_entries(root: Path) -> tuple[PortalEntry, ...]:
    """扫描允许进入可视化目录的研究资产，不暴露原始快照和数据库。"""

    candidates = [
        *root.joinpath("research", "private").rglob("*.html"),
        *root.joinpath("research", "library").rglob("*.html"),
        *root.joinpath("research", "selections").rglob("*.html"),
        *root.joinpath("data", "reports").rglob("*.html"),
        *root.joinpath("data", "backtests").rglob("*.html"),
        *root.joinpath("data", "selections", "latest").glob("*.html"),
    ]
    entries = [
        entry
        for path in sorted(set(candidates))
        if path.is_file() and (entry := _entry(root, path)) is not None
    ]
    category_order = {
        category: index for index, category in enumerate(_CATEGORY_ORDER)
    }
    return tuple(
        sorted(
            entries,
            key=lambda item: (
                category_order[item.category],
                item.published == "持续更新",
                item.published,
                item.title,
            ),
        )
    )


def readable_href(href: str, *, root_prefix: str = "") -> str:
    """把工程 Markdown 路由到站内阅读器，其他资产保持原链接。"""

    if unquote(href).lower().endswith(".md"):
        return (
            f"{root_prefix}docs/markdown.html?src="
            f"{quote('../' + unquote(href), safe='/')}"
        )
    return f"{root_prefix}{href}"


def _engineering_links() -> str:
    return "\n".join(
        f"""
          <a href="{escape(readable_href(path), quote=True)}">
            <strong>{escape(label)}</strong><code>{escape(path)}</code>
          </a>
        """.strip()
        for label, path in _ENGINEERING_DOCUMENTS
    )


def _resource_row(entry: PortalEntry) -> str:
    href = readable_href(entry.href)
    return f"""
        <a class="resource-row" href="{escape(href, quote=True)}"
          data-catalog-row data-category="{escape(entry.category)}"
          data-date="{escape(entry.published)}">
          <span class="resource-main">
            <small>{escape(entry.category)}</small>
            <strong>{escape(entry.title)}</strong>
          </span>
          <span class="resource-date">{escape(entry.published)}</span>
        </a>
    """.strip()


def _grouped_catalog(entries: tuple[PortalEntry, ...]) -> str:
    groups: list[str] = []
    for category in _CATEGORY_ORDER:
        items = [item for item in entries if item.category == category]
        if not items:
            continue
        if any(item.published != "持续更新" for item in items):
            items.sort(
                key=lambda item: (
                    item.published if item.published != "持续更新" else "",
                    item.title,
                ),
                reverse=True,
            )
        else:
            items.sort(key=lambda item: item.title)
        rows = "\n".join(_resource_row(item) for item in items)
        groups.append(
            f"""
      <details class="resource-group">
        <summary>
          <strong>{escape(category)}</strong>
          <span>{len(items)} 项</span>
        </summary>
        <div class="resource-list compact">
{rows}
        </div>
      </details>
            """.strip()
        )
    return "\n".join(groups)


def build_portal(
    root: Path,
    *,
    generated_at: datetime | None = None,
) -> str:
    """生成打开 HTTP 根路径即可使用的研究工作台。"""

    entries = discover_portal_entries(root)
    generated = (generated_at or datetime.now().astimezone()).replace(microsecond=0)
    reports = [
        item
        for item in entries
        if item.category in {
            "标的报告",
            "选择报告",
            "候选初筛",
            "回测报告",
            "标的档案",
        }
    ]
    recent = sorted(
        reports,
        key=lambda item: (
            "latest" in item.href,
            item.published if item.published != "持续更新" else "",
            {
                "候选初筛": 3,
                "选择报告": 2,
                "回测报告": 2,
                "标的报告": 4,
                "标的档案": 1,
            }[item.category],
            item.title,
        ),
        reverse=True,
    )[:6]
    recent_rows = "\n".join(_resource_row(item) for item in recent)
    catalog = _grouped_catalog(entries)
    engineering_links = _engineering_links()
    report_count = len(reports)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>研究工作台 · Quant Monitor</title>
  <link rel="stylesheet" href="docs/assets/docs.css?v={ASSET_VERSION}">
</head>
<body>
{build_site_header("", "workspace")}

  <main class="page workspace-page">
    <section class="workspace-intro">
      <h1>研究工作台</h1>
      <dl class="workspace-summary">
        <div><dt>可浏览内容</dt><dd>{len(entries)}</dd></div>
        <div><dt>研究与报告</dt><dd>{report_count}</dd></div>
        <div><dt>更新时间</dt><dd>{generated:%Y-%m-%d %H:%M}</dd></div>
      </dl>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>研究流程</h2>
      </div>
      <div class="workspace-actions platform-actions">
        <a class="module-selection" href="research/selections/index.html">
          <strong><span>01</span>标的选择</strong><small>候选池 · 短名单</small>
        </a>
        <a class="module-strategy" href="research/strategies/index.html">
          <strong><span>02</span>策略与回测</strong><small>版本 · 验证</small>
        </a>
        <a class="module-analysis" href="research/analysis/index.html">
          <strong><span>03</span>分析作业</strong><small>任务 · 因子</small>
        </a>
        <a class="module-reports" href="research/reports/index.html">
          <strong><span>04</span>报告中心</strong><small>报告 · 发布</small>
        </a>
        <a class="module-channels" href="research/channels/index.html">
          <strong><span>05</span>渠道与通知</strong><small>策略 · 通道</small>
        </a>
        <a class="module-dashboard" href="data/dashboard/index.html">
          <strong><span>06</span>投资看板</strong><small>行情 · 判断</small>
        </a>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>研究资料</h2>
      </div>
      <div class="workspace-actions asset-actions">
        <a class="module-archive" href="research/index.html">
          <strong>研究归档</strong><small>目录 · 隐私分层</small>
        </a>
        <a class="module-instruments" href="research/instruments/index.html">
          <strong>标的档案</strong><small>讨论 · 判断</small>
        </a>
        <a class="module-library" href="research/library/index.html">
          <strong>研究经验</strong><small>方法 · 复用</small>
        </a>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>最近报告</h2>
      </div>
      <div class="resource-list">
{recent_rows}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>全部内容</h2>
      </div>
      <div class="resource-browser">
        <form class="catalog-filters" data-catalog-filters="portal-assets">
          <label class="catalog-search">
            <span>搜索全部内容</span>
            <input type="search" data-field="text"
              placeholder="标的、报告、模块或路径">
          </label>
          <label>
            <span>分类</span>
            <select data-field="category">
              <option value="">全部</option>
              {"".join(
                  f'<option value="{escape(item)}">{escape(item)}</option>'
                  for item in _CATEGORY_ORDER
              )}
            </select>
          </label>
          <button type="reset">重置</button>
          <output data-catalog-count="portal-assets"></output>
        </form>
        <div class="resource-catalog" data-catalog="portal-assets">
{catalog}
        </div>
      </div>
    </section>

    <section class="section engineering-section">
      <details class="engineering-resources">
        <summary>
          <strong>工程资料</strong>
          <span>Agent 与低频查阅</span>
        </summary>
        <div class="engineering-links">
{engineering_links}
        </div>
      </details>
    </section>
  </main>

  <footer class="site-footer">
    <div class="footer-inner">
      <span>Quant Monitor 研究工作台</span>
      <span>研究材料不构成投资建议或自动交易指令。</span>
    </div>
  </footer>
  <script src="docs/assets/navigation.js?v={ASSET_VERSION}"></script>
  <script src="docs/assets/catalog.js?v={ASSET_VERSION}"></script>
</body>
</html>
"""


def write_portal(path: Path, root: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_portal(root), encoding="utf-8")
    return path
