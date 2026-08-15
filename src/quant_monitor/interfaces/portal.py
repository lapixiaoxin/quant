"""生成根路径研究工作台和可浏览内容目录。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9
    import tomli as tomllib

_DATE_PATTERN = re.compile(r"20\d{2}-\d{2}-\d{2}")
_CATEGORY_ORDER = (
    "选择报告",
    "候选初筛",
    "标的研究",
    "候选定义",
    "方法与经验",
    "研究入口",
    "系统文档",
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
    return parser.title or path.stem


def _markdown_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _toml_title(path: Path) -> str:
    with path.open("rb") as handle:
        values: dict[str, Any] = tomllib.load(handle)
    return str(values.get("name") or values.get("universe_id") or path.stem)


def _category_for(relative: Path) -> str | None:
    parts = relative.parts
    if relative.suffix == ".html":
        if parts[:2] == ("data", "dashboard"):
            return None
        if parts[:3] == ("data", "selections", "latest"):
            return "候选初筛"
        if parts[:2] == ("research", "selections") and relative.name != "index.html":
            return "选择报告"
        if parts[:2] == ("research", "private"):
            return "标的研究"
        if parts[:2] == ("research", "library") and relative.name != "index.html":
            return "方法与经验"
        if parts[0] == "research":
            return "研究入口"
        if parts[0] == "docs":
            return "系统文档"
    if relative.suffix == ".md" and parts[:2] == ("data", "reports"):
        return "标的研究"
    if relative.suffix == ".toml" and parts[:2] == ("research", "universes"):
        return "候选定义"
    return None


def _entry(root: Path, path: Path) -> PortalEntry | None:
    relative = path.relative_to(root)
    category = _category_for(relative)
    if category is None:
        return None
    if path.suffix == ".html":
        title = _html_title(path)
    elif path.suffix == ".md":
        title = _markdown_title(path)
    else:
        title = _toml_title(path)
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
        *root.joinpath("docs").glob("*.html"),
        *root.joinpath("research").rglob("*.html"),
        *root.joinpath("research", "universes").glob("*.toml"),
        *root.joinpath("data", "reports").rglob("*.md"),
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


def _resource_row(entry: PortalEntry) -> str:
    return f"""
        <a class="resource-row" href="{escape(entry.href, quote=True)}">
          <span class="resource-main">
            <small>{escape(entry.category)}</small>
            <strong>{escape(entry.title)}</strong>
            <code>{escape(entry.href)}</code>
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
      <section class="resource-group">
        <header>
          <h3>{escape(category)}</h3>
          <span>{len(items)} 项</span>
        </header>
        <div class="resource-list compact">
{rows}
        </div>
      </section>
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
        if item.category in {"选择报告", "候选初筛", "标的研究"}
    ]
    recent = sorted(
        reports,
        key=lambda item: (
            "latest" in item.href,
            item.published if item.published != "持续更新" else "",
            {
                "候选初筛": 3,
                "选择报告": 2,
                "标的研究": 1,
            }[item.category],
            item.title,
        ),
        reverse=True,
    )[:6]
    recent_rows = "\n".join(_resource_row(item) for item in recent)
    catalog = _grouped_catalog(entries)
    report_count = len(reports)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>研究工作台 · Quant Monitor</title>
  <link rel="stylesheet" href="docs/assets/docs.css?v=0.7.0">
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="index.html">Quant Monitor</a>
      <nav class="site-nav" aria-label="全局导航">
        <a href="index.html" aria-current="page">工作台</a>
        <details class="nav-dropdown">
          <summary>使用指南</summary>
          <div class="nav-menu">
            <a href="docs/index.html">
              <strong>文档总览</strong><small>能力、入口与阅读路径</small>
            </a>
            <a href="docs/install.html">
              <strong>安装部署</strong><small>新设备、凭证与常驻服务</small>
            </a>
            <a href="docs/operations.html">
              <strong>运行运维</strong><small>命令、日志与故障处理</small>
            </a>
          </div>
        </details>
        <details class="nav-dropdown">
          <summary>系统设计</summary>
          <div class="nav-menu">
            <a href="docs/capabilities.html">
              <strong>能力边界</strong><small>已支持、条件支持与明确限制</small>
            </a>
            <a href="docs/architecture.html">
              <strong>架构设计</strong><small>模块、数据流与扩展契约</small>
            </a>
            <a href="docs/refactor-report.html">
              <strong>升级报告</strong><small>工程演进过程与验证证据</small>
            </a>
          </div>
        </details>
        <details class="nav-dropdown align-right">
          <summary>研究中心</summary>
          <div class="nav-menu">
            <a href="research/index.html">
              <strong>研究总览</strong><small>研究资产与隐私分层入口</small>
            </a>
            <a href="research/selections/index.html">
              <strong>候选筛选</strong><small>发现同类标的并形成短名单</small>
            </a>
            <a href="research/instruments/index.html">
              <strong>标的档案</strong><small>按代码沉淀讨论与判断</small>
            </a>
            <a href="research/library/index.html">
              <strong>通用经验</strong><small>复核并脱敏的跨标的方法</small>
            </a>
            <a href="research/methods/storage-backtesting.html">
              <strong>数据与回测</strong><small>历史存储与验证纪律</small>
            </a>
            <a href="research/templates/discussion-report.html">
              <strong>讨论模板</strong><small>统一事实、结论与失效条件</small>
            </a>
          </div>
        </details>
        <a href="data/dashboard/index.html">投资看板</a>
      </nav>
    </div>
  </header>

  <main class="page workspace-page">
    <section class="workspace-intro">
      <div>
        <p class="eyebrow">Research Workspace</p>
        <h1>研究工作台</h1>
        <p>
          从这里进入投资看板、候选筛选、研究报告和系统文档。
          新增可阅读资产会在刷新工作台后自动进入下方目录。
        </p>
      </div>
      <dl class="workspace-summary">
        <div><dt>可浏览内容</dt><dd>{len(entries)}</dd></div>
        <div><dt>研究与报告</dt><dd>{report_count}</dd></div>
        <div><dt>更新时间</dt><dd>{generated:%Y-%m-%d %H:%M}</dd></div>
      </dl>
    </section>

    <section class="section">
      <div class="section-head">
        <p class="section-label">常用入口</p>
        <div>
          <h2>先选任务，再进入内容</h2>
          <p class="section-intro">稳定入口不会随报告数量增长而改变。</p>
        </div>
      </div>
      <div class="workspace-actions">
        <a href="data/dashboard/index.html">
          <strong>投资看板</strong><span>查看最新标的、指标与策略状态</span>
        </a>
        <a href="research/selections/index.html">
          <strong>候选筛选</strong><span>从同类产品进入初筛和深度报告</span>
        </a>
        <a href="research/index.html">
          <strong>研究中心</strong><span>浏览标的档案、方法与讨论沉淀</span>
        </a>
        <a href="docs/index.html">
          <strong>文档中心</strong><span>查看能力、部署、运维和架构</span>
        </a>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <p class="section-label">最近产物</p>
        <div>
          <h2>优先显示可直接阅读的结果</h2>
          <p class="section-intro">
            原始 JSON 快照和 SQLite 不进入这里，避免干扰阅读。
          </p>
        </div>
      </div>
      <div class="resource-list">
{recent_rows}
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <p class="section-label">内容目录</p>
        <div>
          <h2>全部可浏览资产</h2>
          <p class="section-intro">按用途分组，未来新增页面由扫描规则自动收录。</p>
        </div>
      </div>
      <div class="resource-groups">
{catalog}
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="footer-inner">
      <span>Quant Monitor 研究工作台</span>
      <span>研究材料不构成投资建议或自动交易指令。</span>
    </div>
  </footer>
  <script src="docs/assets/navigation.js?v=0.7.0"></script>
</body>
</html>
"""


def write_portal(path: Path, root: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_portal(root), encoding="utf-8")
    return path
