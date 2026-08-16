"""命令行组合根：装配依赖并把命令映射到应用服务。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from ..application.analysis import AnalysisService
from ..application.automation import AutomationService
from ..application.backtesting import BacktestService, save_backtest_result
from ..application.monitoring import MonitoringService
from ..application.notifications import NotificationService
from ..application.selection import SelectionService
from ..config import Settings, load_settings
from ..domain.backtesting import BacktestSpecification
from ..domain.control_plane import (
    AnalysisCycle,
    AnalysisRequest,
    AnalysisTrigger,
    BacktestRunRecord,
    SelectionRunRecord,
)
from ..domain.factors import FactorRegistry
from ..domain.strategies import StrategyRegistry
from ..infrastructure.control_repository import SQLiteControlPlaneRepository
from ..infrastructure.history import SQLiteMarketHistoryRepository
from ..infrastructure.lark_events import LarkCliEventSource, LarkCliReplier
from ..infrastructure.market_data import DataSourceError, FallbackMarketDataProvider
from ..infrastructure.notifications import (
    NotificationError,
    build_notification_channels,
)
from ..infrastructure.research_agent import TraeCliResearchRunner
from ..infrastructure.selection_config import load_selection_universe
from ..infrastructure.storage import FileResearchRepository
from ..infrastructure.strategy_catalog import (
    StrategyCatalog,
    load_strategy_catalog,
)
from .backtest_reporting import write_backtest_report
from .dashboard import write_dashboard
from .markdown_viewer import write_markdown_viewer
from .platform_pages import write_platform_pages
from .portal import write_portal
from .remote import RemoteCommandRouter, listen_remote_commands
from .reporting import build_base_report
from .research_report_pages import write_research_report_pages
from .selection_reporting import write_selection_report
from .site_navigation import refresh_site_navigation


class ChineseArgumentParser(argparse.ArgumentParser):
    """将 Python 3.9 argparse 的固定帮助文本本地化。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._positionals.title = "位置参数"
        self._optionals.title = "选项"
        for action in self._actions:
            if action.dest == "help":
                action.help = "显示帮助并退出"

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "用法:", 1)

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法:", 1)


def _root() -> Path:
    configured = os.environ.get("QUANT_MONITOR_ROOT")
    return Path(configured or Path.cwd()).resolve()


def _add_target_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--symbol", help="标的代码；默认使用配置中的第一个标的")
    group.add_argument("--all", action="store_true", help="处理配置中的全部标的")


def _add_analysis_target_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--symbol", help="单个标的代码")
    group.add_argument(
        "--symbols",
        help="逗号分隔的多个标的代码",
    )
    group.add_argument("--all", action="store_true", help="分析全部启用标的")


def _symbols(args: argparse.Namespace, settings: Settings) -> list[str]:
    if getattr(args, "all", False):
        return [item.symbol for item in settings.enabled_instruments]
    symbol = getattr(args, "symbol", None)
    if symbol:
        return [symbol]
    if not settings.enabled_instruments:
        raise ValueError("配置中没有已启用的标的")
    return [settings.enabled_instruments[0].symbol]


def _analysis_symbols(
    args: argparse.Namespace,
    settings: Settings,
) -> tuple[str, ...]:
    if getattr(args, "all", False):
        symbols = tuple(item.symbol for item in settings.enabled_instruments)
    elif getattr(args, "symbols", None):
        symbols = tuple(
            dict.fromkeys(
                item.strip()
                for item in str(args.symbols).split(",")
                if item.strip()
            )
        )
    elif getattr(args, "symbol", None):
        symbols = (str(args.symbol),)
    elif settings.enabled_instruments:
        symbols = (settings.enabled_instruments[0].symbol,)
    else:
        symbols = ()
    if not symbols:
        raise ValueError("分析目标不能为空")
    return symbols


def _parser() -> argparse.ArgumentParser:
    parser = ChineseArgumentParser(
        description="个人投资行情监控与分析内核",
    )
    parser.add_argument("--config", type=Path, help="指定 TOML 配置文件")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="采集并准备研究数据")
    _add_target_options(prepare_parser)
    prepare_parser.add_argument(
        "--analysis-request",
        type=Path,
        help="标准分析请求 JSON，用于动态注入周期和因子",
    )

    report_parser = subparsers.add_parser(
        "base-report",
        help="根据最新数据生成确定性基础报告",
    )
    _add_target_options(report_parser)

    daily_parser = subparsers.add_parser(
        "daily",
        help="采集数据并生成基础日报",
    )
    _add_target_options(daily_parser)
    daily_parser.add_argument(
        "--send-base",
        action="store_true",
        help="将基础日报发送到飞书",
    )

    automate_parser = subparsers.add_parser(
        "automate",
        help="按配置执行无人值守研究与推送",
    )
    _add_target_options(automate_parser)
    automate_parser.add_argument(
        "--mode",
        choices=("base", "traecli"),
        help="覆盖配置中的自动化模式",
    )
    automate_parser.add_argument(
        "--force",
        action="store_true",
        help="即使 automation.enabled=false 也执行",
    )
    send_group = automate_parser.add_mutually_exclusive_group()
    send_group.add_argument(
        "--send",
        dest="send",
        action="store_true",
        default=None,
        help="覆盖配置并发送报告",
    )
    send_group.add_argument(
        "--no-send",
        dest="send",
        action="store_false",
        help="覆盖配置但不发送报告",
    )

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="按标的范围、周期和因子执行标准分析作业",
    )
    _add_analysis_target_options(analyze_parser)
    analyze_parser.add_argument(
        "--cycle",
        action="append",
        choices=tuple(item.value for item in AnalysisCycle),
        help="可重复指定 daily、monthly、yearly、moving_average",
    )
    analyze_parser.add_argument(
        "--factors",
        help="逗号分隔的因子 ID；省略时按周期使用默认因子",
    )
    analyze_parser.add_argument(
        "--mode",
        choices=("base", "traecli"),
        help="覆盖自动化模式",
    )
    analyze_send = analyze_parser.add_mutually_exclusive_group()
    analyze_send.add_argument(
        "--send",
        dest="send",
        action="store_true",
        default=None,
        help="按标的通知策略发送",
    )
    analyze_send.add_argument(
        "--no-send",
        dest="send",
        action="store_false",
        help="只生成报告和网页",
    )

    send_parser = subparsers.add_parser(
        "send-report",
        help="发送已有 Markdown 报告",
    )
    send_parser.add_argument("path", type=Path, help="报告文件路径")
    send_parser.add_argument("--symbol", help="标的代码；默认使用首个启用标的")
    send_parser.add_argument(
        "--event",
        default="manual",
        help="通知事件名称，默认 manual",
    )
    send_parser.add_argument("--title", help="覆盖通知策略中的标题模板")
    send_parser.add_argument(
        "--force",
        action="store_true",
        help="忽略事件过滤，但仍使用标的配置的通道",
    )

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="生成静态本地看板",
    )
    dashboard_parser.add_argument(
        "--output",
        type=Path,
        help="输出路径；默认为 data/dashboard/index.html",
    )
    subparsers.add_parser(
        "site",
        help="刷新五模块工作台、投资看板和全局导航",
    )

    listen_parser = subparsers.add_parser(
        "listen",
        help="监听飞书白名单远程命令",
    )
    listen_parser.add_argument(
        "--check",
        action="store_true",
        help="只检查配置和 lark-cli，不建立连接",
    )

    subparsers.add_parser("instruments", help="列出已配置标的和策略")
    strategies_parser = subparsers.add_parser(
        "strategies",
        help="查看版本化策略及当前生效状态",
    )
    strategies_parser.add_argument("--symbol", help="只查看指定标的")
    backtest_parser = subparsers.add_parser(
        "backtest",
        help="使用本地 SQLite 历史库回测一个策略版本",
    )
    backtest_parser.add_argument(
        "--strategy-record",
        required=True,
        help="策略目录 record_id",
    )
    backtest_parser.add_argument("--symbol", help="覆盖策略记录中的首个标的")
    backtest_parser.add_argument("--start", type=date.fromisoformat)
    backtest_parser.add_argument("--end", type=date.fromisoformat)
    history_parser = subparsers.add_parser(
        "history",
        help="查看本地 SQLite 历史行情覆盖情况",
    )
    _add_target_options(history_parser)
    select_parser = subparsers.add_parser(
        "select",
        help="按候选池执行确定性标的初筛",
    )
    select_parser.add_argument(
        "--universe",
        type=Path,
        required=True,
        help="候选池 TOML 文件",
    )
    select_parser.add_argument(
        "--output",
        type=Path,
        help="可选的机器筛选明细 HTML；正式选择报告由 Agent 补全",
    )
    subparsers.add_parser("doctor", help="检查配置、扩展点与本地环境")
    return parser


def _build_service(
    settings: Settings,
    repository: FileResearchRepository,
    history_repository: SQLiteMarketHistoryRepository,
    strategies: StrategyRegistry,
    strategy_catalog: StrategyCatalog,
) -> MonitoringService:
    return MonitoringService(
        settings=settings,
        market_data=FallbackMarketDataProvider(),
        history_repository=history_repository,
        repository=repository,
        strategies=strategies,
        strategy_catalog=strategy_catalog,
    )


def _build_notification_service(settings: Settings) -> NotificationService:
    return NotificationService(
        settings,
        build_notification_channels(settings),
    )


def _build_automation_service(
    settings: Settings,
    monitoring: MonitoringService,
    repository: FileResearchRepository,
) -> AutomationService:
    return AutomationService(
        settings=settings,
        monitoring=monitoring,
        repository=repository,
        notifications=_build_notification_service(settings),
        agent_runner=TraeCliResearchRunner(settings.root, settings.automation),
        report_renderer=build_base_report,
    )


def _send_report(
    settings: Settings,
    path: Path,
    symbol: str,
    event: str,
    title: str | None,
    force: bool = False,
) -> tuple[str, ...]:
    markdown = path.read_text(encoding="utf-8")
    service = _build_notification_service(settings)
    return service.send(
        symbol,
        event,
        markdown,
        title=title,
        force=force,
    )


def _write_site(
    root: Path,
    settings: Settings,
    repository: FileResearchRepository,
    strategy_catalog: StrategyCatalog,
    control_repository: SQLiteControlPlaneRepository,
    factors: FactorRegistry,
    *,
    dashboard_output: Path | None = None,
) -> tuple[Path, Path]:
    dashboard_path = dashboard_output or (
        settings.data_dir / "dashboard" / "index.html"
    )
    dashboard = write_dashboard(
        dashboard_path,
        repository.list_latest_packets(),
    )
    write_research_report_pages(root)
    write_platform_pages(
        root,
        settings,
        strategy_catalog,
        control_repository,
        factors,
    )
    write_markdown_viewer(root / "docs" / "markdown.html")
    portal = write_portal(root / "index.html", root)
    refresh_site_navigation(root)
    return dashboard, portal


def _doctor(
    root: Path,
    settings: Settings,
    strategies: StrategyRegistry,
    history_repository: SQLiteMarketHistoryRepository,
    strategy_catalog: StrategyCatalog,
    control_repository: SQLiteControlPlaneRepository,
    factors: FactorRegistry,
) -> None:
    for profile in settings.strategy_profiles.values():
        strategies.get(profile.strategy_id).validate_parameters(
            profile.parameters,
            profile_id=profile.profile_id,
        )
    for instrument in settings.instruments:
        skill = settings.research_plan_for(instrument.symbol).skill
        skill_path = root / ".trae" / "skills" / skill / "SKILL.md"
        if not skill_path.exists():
            raise ValueError(
                f"标的 {instrument.symbol} 配置的 Skill 不存在：{skill}"
            )
    selection_skill = (
        root / ".trae" / "skills" / "instrument-selector" / "SKILL.md"
    )
    if not selection_skill.exists():
        raise ValueError("候选筛选 Skill 不存在：instrument-selector")
    selection_universes = [
        load_selection_universe(path)
        for path in sorted((root / "research" / "universes").glob("*.toml"))
    ]
    strategy_catalog.validate_settings(settings)
    build_notification_channels(settings)
    print(f"项目目录：{root}")
    print(f"Python：{sys.version.split()[0]}")
    print(f"配置：正常（{len(settings.instruments)} 个标的）")
    print(f"策略：正常（{', '.join(strategies.ids)}）")
    print(f"策略画像：正常（{len(settings.strategy_profiles)} 个）")
    active_strategy_count = sum(
        item.lifecycle.value == "active"
        for item in strategy_catalog.records
    )
    print(
        f"策略版本：正常（{len(strategy_catalog.records)} 个，"
        f"{active_strategy_count} 个启用）"
    )
    print(
        f"分析因子：正常（{len(factors.all)} 个，"
        f"{sum(item.availability == 'available' for item in factors.all)} 个可用）"
    )
    print(
        "产品类型："
        + "、".join(item.value for item in sorted(settings.product_types, key=str))
    )
    print(
        f"研究画像：正常（{len(settings.research_profiles)} 个）"
    )
    print(
        f"通知策略：正常（{len(settings.notification_policies)} 个）"
    )
    channel_states = "、".join(
        f"{item.channel_id}({item.channel_type},"
        f"{'启用' if item.enabled else '停用'})"
        for item in settings.notification_channels.values()
    )
    print(f"通知通道：{channel_states or '未配置'}")
    print("TRAE Skill：正常")
    print(
        "候选筛选：正常（"
        f"{len(selection_universes)} 个候选池，"
        f"{sum(len(item.candidates) for item in selection_universes)} 个候选）"
    )
    traecli = TraeCliResearchRunner(root, settings.automation)
    print(
        f"自动化：{'启用' if settings.automation.enabled else '停用'}"
        f"（{settings.automation.mode}，"
        f"{'发送' if settings.automation.send else '不发送'}）"
    )
    print(
        "TraeCode CLI："
        f"{'可用' if traecli.is_available() else '未安装或路径无效'}"
    )
    print(
        "历史数据库：正常（SQLite schema "
        f"v{history_repository.schema_version}，"
        f"{history_repository.database_path}）"
    )
    print(
        "控制面数据库：正常（SQLite schema "
        f"v{control_repository.schema_version}，"
        f"{control_repository.database_path}）"
    )
    event_source = LarkCliEventSource(settings.remote)
    print(
        f"飞书远程命令：{'启用' if settings.remote.enabled else '停用'}"
        f"（lark-cli {'可用' if event_source.is_available() else '不可用'}）"
    )


def main() -> int:
    args = _parser().parse_args()
    root = _root()
    try:
        settings = load_settings(root, args.config)
        repository = FileResearchRepository(settings.data_dir)
        history_repository = SQLiteMarketHistoryRepository(
            settings.data_dir / "history" / "market.sqlite3"
        )
        control_repository = SQLiteControlPlaneRepository(
            settings.data_dir / "control" / "research.sqlite3"
        )
        strategies = StrategyRegistry.default()
        strategy_catalog = load_strategy_catalog(
            root / "research" / "strategies" / "catalog.toml"
        )
        strategy_catalog.validate_settings(settings)
        factors = FactorRegistry.default()

        if args.command == "doctor":
            _doctor(
                root,
                settings,
                strategies,
                history_repository,
                strategy_catalog,
                control_repository,
                factors,
            )
            return 0

        if args.command == "instruments":
            for item in settings.instruments:
                print(
                    f"{item.symbol}\t{item.instrument_type.value}\t"
                    f"{','.join(item.strategy_profile_ids)}\t"
                    f"{item.research_profile_id}\t"
                    f"{item.notification_policy_id}\t"
                    f"{'启用' if item.enabled else '停用'}\t"
                    f"{item.name}"
                )
            return 0

        if args.command == "strategies":
            for record in strategy_catalog.records:
                if args.symbol and not record.applies_to(args.symbol):
                    continue
                print(
                    f"{record.record_id}\t{record.version}\t"
                    f"{record.lifecycle.value}\t"
                    f"{record.validation_state.value}\t"
                    f"{record.horizon.value}\t"
                    f"{','.join(record.symbols)}\t{record.name}"
                )
            return 0

        if args.command == "history":
            print(f"数据库：{history_repository.database_path}")
            for symbol in _symbols(args, settings):
                summary = history_repository.summarize(symbol)
                coverage = (
                    f"{summary.first_date} 至 {summary.last_date}"
                    if summary.first_date and summary.last_date
                    else "暂无数据"
                )
                source = summary.last_source or "无"
                print(
                    f"{symbol}\t{summary.bar_count} 根\t{coverage}\t"
                    f"最近来源：{source}"
                )
            return 0

        if args.command == "backtest":
            record = strategy_catalog.record(args.strategy_record)
            symbol = args.symbol or record.symbols[0]
            instrument = settings.instrument_for(symbol)
            summary = history_repository.summarize(symbol)
            start_date = args.start or summary.first_date
            end_date = args.end or summary.last_date
            if start_date is None or end_date is None:
                raise ValueError(f"标的 {symbol} 没有可回测的历史数据")
            run_id = (
                f"{datetime.now().astimezone():%Y%m%dT%H%M%S}-"
                f"{uuid4().hex[:8]}"
            )
            result_dir = settings.data_dir / "backtests" / symbol
            result_path = result_dir / f"{run_id}.json"
            report_path = result_dir / f"{run_id}.html"
            started_at = datetime.now().astimezone().replace(microsecond=0)
            pending = BacktestRunRecord(
                run_id=run_id,
                strategy_record_id=record.record_id,
                symbol=symbol,
                started_at=started_at,
                completed_at=None,
                status="running",
                result_path=str(report_path.relative_to(root)),
            )
            control_repository.save_backtest(pending)
            try:
                result = BacktestService(
                    history_repository,
                    strategies,
                    strategy_catalog,
                ).run(
                    instrument,
                    settings.strategy_profiles[record.profile_id].parameters,
                    BacktestSpecification(
                        symbol=symbol,
                        model_id=record.backtest_model_id,
                        model_version=record.backtest_model_version,
                        parameters_fingerprint=record.parameters_fingerprint,
                        start_date=start_date,
                        end_date=end_date,
                    ),
                    strategy_record_id=record.record_id,
                )
                save_backtest_result(result_path, result)
                write_backtest_report(report_path, result, record)
            except (OSError, RuntimeError, ValueError) as error:
                control_repository.save_backtest(
                    replace(
                        pending,
                        completed_at=datetime.now().astimezone(),
                        status="failed",
                        error=str(error),
                    )
                )
                raise
            control_repository.save_backtest(
                BacktestRunRecord(
                    run_id=run_id,
                    strategy_record_id=record.record_id,
                    symbol=symbol,
                    started_at=started_at,
                    completed_at=datetime.now().astimezone(),
                    status="completed",
                    result_path=str(report_path.relative_to(root)),
                    total_return=result.metrics.total_return,
                    max_drawdown=result.metrics.max_drawdown,
                    trade_count=result.metrics.trade_count,
                )
            )
            _, portal_path = _write_site(
                root,
                settings,
                repository,
                strategy_catalog,
                control_repository,
                factors,
            )
            print(f"回测数据：{result_path}")
            print(f"回测报告：{report_path}")
            print(f"研究工作台：{portal_path}")
            return 0

        if args.command == "select":
            universe_path = (
                args.universe
                if args.universe.is_absolute()
                else root / args.universe
            )
            universe = load_selection_universe(universe_path.resolve())
            service = SelectionService(
                settings=settings,
                market_data=FallbackMarketDataProvider(),
                history_repository=history_repository,
                repository=repository,
            )
            packet_path, packet = service.prepare(universe)
            requested_at = datetime.fromisoformat(str(packet["as_of"]))
            selection_report_path = (
                root
                / "research"
                / "selections"
                / universe.universe_id
                / f"{requested_at:%Y-%m-%d}-selection.html"
            )
            detail_path = None
            if args.output is not None:
                output = args.output
                if not output.is_absolute():
                    output = root / output
                detail_path = write_selection_report(output, packet)
            control_repository.save_selection(
                SelectionRunRecord(
                    run_id=(
                        f"{universe.universe_id}:"
                        f"{requested_at:%Y%m%dT%H%M%S}"
                    ),
                    universe_id=universe.universe_id,
                    horizon=universe.horizon,
                    theme=universe.theme,
                    requested_at=requested_at,
                    status="screened",
                    candidate_count=packet["summary"]["candidate_count"],
                    shortlist_count=packet["summary"]["eligible"],
                    packet_path=str(packet_path.relative_to(root)),
                    report_path=str(
                        selection_report_path.relative_to(root)
                    ),
                )
            )
            _, portal_path = _write_site(
                root,
                settings,
                repository,
                strategy_catalog,
                control_repository,
                factors,
            )
            print(f"数据包：{packet_path}")
            if detail_path is not None:
                print(f"机器筛选明细：{detail_path}")
            print(f"选择报告目标：{selection_report_path}")
            print(f"研究工作台：{portal_path}")
            return 0

        if args.command in {"dashboard", "site"}:
            output = (
                args.output
                if args.command == "dashboard"
                else settings.data_dir / "dashboard" / "index.html"
            )
            output = output or settings.data_dir / "dashboard" / "index.html"
            if not output.is_absolute():
                output = root / output
            dashboard_path, portal_path = _write_site(
                root,
                settings,
                repository,
                strategy_catalog,
                control_repository,
                factors,
                dashboard_output=output,
            )
            print(f"投资看板：{dashboard_path}")
            print(f"研究工作台：{portal_path}")
            return 0

        monitoring = _build_service(
            settings,
            repository,
            history_repository,
            strategies,
            strategy_catalog,
        )
        automation = _build_automation_service(
            settings,
            monitoring,
            repository,
        )
        analysis = AnalysisService(
            settings,
            automation,
            repository,
            control_repository,
            strategy_catalog,
            factors,
        )

        def refresh_site() -> None:
            _write_site(
                root,
                settings,
                repository,
                strategy_catalog,
                control_repository,
                factors,
            )

        if args.command == "automate":
            if not settings.automation.enabled and not args.force:
                raise ValueError(
                    "自动化未启用；请配置 automation.enabled=true"
                    " 或使用 --force"
                )
            request = analysis.create_request(
                symbols=tuple(_symbols(args, settings)),
                cycles=(
                    AnalysisCycle.DAILY,
                    AnalysisCycle.MOVING_AVERAGE,
                ),
                trigger=AnalysisTrigger.SCHEDULED,
                mode=args.mode or settings.automation.mode,
                send=(
                    settings.automation.send
                    if args.send is None
                    else args.send
                ),
            )
            execution = analysis.run(request)
            for result in execution.results:
                fallback = "（已降级）" if result.fallback_used else ""
                channels = (
                    f"；通道：{', '.join(result.sent_channels)}"
                    if result.sent_channels
                    else ""
                )
                print(
                    f"{result.symbol}：{result.mode}{fallback}；"
                    f"报告：{result.report_path}{channels}"
                )
            for error in execution.errors:
                print(f"失败：{error}", file=sys.stderr)
            dashboard_path, portal_path = _write_site(
                root,
                settings,
                repository,
                strategy_catalog,
                control_repository,
                factors,
            )
            print(f"投资看板：{dashboard_path}")
            print(f"研究工作台：{portal_path}")
            return 1 if execution.errors and not execution.results else 0

        if args.command == "analyze":
            cycles = tuple(
                AnalysisCycle.parse(item)
                for item in (
                    args.cycle
                    or ("daily", "moving_average")
                )
            )
            factor_ids = tuple(
                item.strip()
                for item in str(args.factors or "").split(",")
                if item.strip()
            )
            request = analysis.create_request(
                symbols=_analysis_symbols(args, settings),
                cycles=cycles,
                factor_ids=factor_ids,
                trigger=AnalysisTrigger.MANUAL,
                mode=args.mode or settings.automation.mode,
                send=(
                    settings.automation.send
                    if args.send is None
                    else args.send
                ),
            )
            execution = analysis.run(request)
            print(f"分析任务：{execution.request.request_id}")
            print(f"请求文件：{execution.request_path}")
            for result in execution.results:
                print(f"{result.symbol}：{result.report_path}")
            for error in execution.errors:
                print(f"失败：{error}", file=sys.stderr)
            dashboard_path, portal_path = _write_site(
                root,
                settings,
                repository,
                strategy_catalog,
                control_repository,
                factors,
            )
            print(f"投资看板：{dashboard_path}")
            print(f"研究工作台：{portal_path}")
            return 1 if execution.errors and not execution.results else 0

        if args.command == "listen":
            source = LarkCliEventSource(settings.remote)
            if not settings.remote.enabled:
                raise ValueError("飞书远程命令未启用")
            if not source.is_available():
                raise ValueError("未找到 lark-cli")
            if args.check:
                source.check()
                print("飞书远程命令配置正常，lark-cli 可用")
                return 0
            router = RemoteCommandRouter(
                settings,
                monitoring,
                automation,
                repository,
                analysis,
                strategy_catalog,
                refresh_site,
            )
            try:
                listen_remote_commands(
                    settings,
                    router,
                    source,
                    LarkCliReplier(settings.remote),
                )
            except KeyboardInterrupt:
                source.close()
            return 0

        if args.command == "send-report":
            path = args.path if args.path.is_absolute() else root / args.path
            symbol = _symbols(args, settings)[0]
            channels = _send_report(
                settings,
                path.resolve(),
                symbol,
                args.event,
                args.title,
                args.force,
            )
            print(f"已发送：{path} -> {', '.join(channels)}")
            return 0

        for symbol in _symbols(args, settings):
            if args.command == "prepare":
                analysis_request = None
                if args.analysis_request:
                    request_path = (
                        args.analysis_request
                        if args.analysis_request.is_absolute()
                        else root / args.analysis_request
                    )
                    values = json.loads(
                        request_path.read_text(encoding="utf-8")
                    )
                    if not isinstance(values, dict):
                        raise ValueError("分析请求 JSON 必须是对象")
                    analysis_request = AnalysisRequest.from_packet(values)
                path, _ = monitoring.prepare(symbol, analysis_request)
                print(path)
                continue

            if args.command == "base-report":
                packet = repository.load_latest_packet(symbol)
            elif args.command == "daily":
                _, packet = monitoring.prepare(symbol)
            else:
                return 2

            content = build_base_report(packet)
            report_path = repository.save_base_report(
                symbol,
                str(packet["as_of"]),
                content,
            )
            print(report_path)
            if args.command == "daily" and args.send_base:
                _send_report(
                    settings,
                    report_path,
                    symbol,
                    "base_report",
                    None,
                )
        if args.command in {"base-report", "daily"}:
            dashboard_path, portal_path = _write_site(
                root,
                settings,
                repository,
                strategy_catalog,
                control_repository,
                factors,
            )
            print(f"投资看板：{dashboard_path}")
            print(f"研究工作台：{portal_path}")
        return 0
    except (
        DataSourceError,
        NotificationError,
        FileNotFoundError,
        RuntimeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
