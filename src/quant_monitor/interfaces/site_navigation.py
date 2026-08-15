"""统一生成并刷新所有可浏览页面的全局导航。"""

from __future__ import annotations

import re
from pathlib import Path

_HEADER_PATTERN = re.compile(
    r"  <header class=\"site-header\">.*?  </header>",
    re.DOTALL,
)
_ASSET_VERSION_PATTERN = re.compile(
    r"(?P<asset>docs\.css|navigation\.js)\?v=[0-9.]+"
)
ASSET_VERSION = "0.8.1"


def _link_current(current: str, value: str) -> str:
    return ' aria-current="page"' if current == value else ""


def _group_state(current: str, values: set[str]) -> tuple[str, str]:
    if current not in values:
        return "", ""
    return " is-current", ' aria-current="true"'


def build_site_header(prefix: str, current: str) -> str:
    """按页面相对根路径和当前位置生成同一套导航信息架构。"""

    process_class, process_current = _group_state(
        current,
        {"selection", "strategy", "analysis", "reports"},
    )
    assets_class, assets_current = _group_state(
        current,
        {"research", "instruments", "library", "channels"},
    )
    system_class, system_current = _group_state(
        current,
        {"docs", "capabilities", "architecture"},
    )
    workspace_current = _link_current(current, "workspace")
    selection_current = _link_current(current, "selection")
    strategy_current = _link_current(current, "strategy")
    analysis_current = _link_current(current, "analysis")
    reports_current = _link_current(current, "reports")
    research_current = _link_current(current, "research")
    instruments_current = _link_current(current, "instruments")
    library_current = _link_current(current, "library")
    channels_current = _link_current(current, "channels")
    docs_current = _link_current(current, "docs")
    capabilities_current = _link_current(current, "capabilities")
    architecture_current = _link_current(current, "architecture")
    dashboard_current = _link_current(current, "dashboard")
    return f"""
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="{prefix}index.html">Quant Monitor</a>
      <nav class="site-nav" aria-label="全局导航">
        <a href="{prefix}index.html"{workspace_current}>
          工作台
        </a>
        <details class="nav-dropdown{process_class}">
          <summary{process_current}>研究流程</summary>
          <div class="nav-menu">
            <a href="{prefix}research/selections/index.html"{selection_current}>
              <strong>标的选择</strong><small>候选池、筛选历史与短名单</small>
            </a>
            <a href="{prefix}research/strategies/index.html"{strategy_current}>
              <strong>策略与回测</strong><small>版本、状态、配置与验证</small>
            </a>
            <a href="{prefix}research/analysis/index.html"{analysis_current}>
              <strong>分析作业</strong><small>触发、周期、因子与运行状态</small>
            </a>
            <a href="{prefix}research/reports/index.html"{reports_current}>
              <strong>报告中心</strong><small>分类、时间和发布状态</small>
            </a>
          </div>
        </details>
        <details class="nav-dropdown{assets_class}">
          <summary{assets_current}>资产与渠道</summary>
          <div class="nav-menu">
            <a href="{prefix}research/index.html"{research_current}>
              <strong>研究中心</strong><small>标的档案、经验与方法入口</small>
            </a>
            <a href="{prefix}research/instruments/index.html"{instruments_current}>
              <strong>标的档案</strong><small>按代码沉淀讨论和判断</small>
            </a>
            <a href="{prefix}research/library/index.html"{library_current}>
              <strong>研究经验</strong><small>复核并脱敏的方法</small>
            </a>
            <a href="{prefix}research/channels/index.html"{channels_current}>
              <strong>渠道与通知</strong><small>策略、事件和发送通道</small>
            </a>
          </div>
        </details>
        <details class="nav-dropdown align-right{system_class}">
          <summary{system_current}>系统</summary>
          <div class="nav-menu">
            <a href="{prefix}docs/index.html"{docs_current}>
              <strong>文档中心</strong><small>能力、部署和运维入口</small>
            </a>
            <a href="{prefix}docs/capabilities.html"{capabilities_current}>
              <strong>能力边界</strong><small>当前支持和明确限制</small>
            </a>
            <a href="{prefix}docs/architecture.html"{architecture_current}>
              <strong>架构设计</strong><small>数据流、契约和扩展方式</small>
            </a>
          </div>
        </details>
        <a href="{prefix}data/dashboard/index.html"{dashboard_current}>
          投资看板
        </a>
      </nav>
    </div>
  </header>
    """.strip("\n").rstrip()


def _current_for(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    parts = relative.parts
    if relative == Path("index.html"):
        return "workspace"
    if parts[0] == "docs":
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
    return "workspace"


def _prefix_for(path: Path, root: Path) -> str:
    depth = len(path.relative_to(root).parent.parts)
    return "../" * depth


def refresh_site_navigation(root: Path) -> tuple[Path, ...]:
    """统一现有 HTML 的导航、静态资源版本和键盘交互脚本。"""

    candidates = {
        root / "index.html",
        *root.joinpath("docs").glob("*.html"),
        *root.joinpath("research").rglob("*.html"),
        *root.joinpath("data", "dashboard").rglob("*.html"),
        *root.joinpath("data", "selections").rglob("*.html"),
        *root.joinpath("data", "backtests").rglob("*.html"),
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
