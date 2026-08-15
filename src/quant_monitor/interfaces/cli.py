"""命令行组合根：装配依赖并把命令映射到应用服务。"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from ..application.monitoring import MonitoringService
from ..application.notifications import NotificationService
from ..config import Settings, load_settings
from ..domain.strategies import StrategyRegistry
from ..infrastructure.market_data import DataSourceError, FallbackMarketDataProvider
from ..infrastructure.notifications import (
    NotificationError,
    build_notification_channels,
)
from ..infrastructure.storage import FileResearchRepository
from .dashboard import write_dashboard
from .reporting import build_base_report


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


def _symbols(args: argparse.Namespace, settings: Settings) -> list[str]:
    if getattr(args, "all", False):
        return [item.symbol for item in settings.enabled_instruments]
    symbol = getattr(args, "symbol", None)
    if symbol:
        return [symbol]
    if not settings.enabled_instruments:
        raise ValueError("配置中没有已启用的标的")
    return [settings.enabled_instruments[0].symbol]


def _parser() -> argparse.ArgumentParser:
    parser = ChineseArgumentParser(
        description="个人投资行情监控与分析内核",
    )
    parser.add_argument("--config", type=Path, help="指定 TOML 配置文件")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="采集并准备研究数据")
    _add_target_options(prepare_parser)

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

    subparsers.add_parser("instruments", help="列出已配置标的和策略")
    subparsers.add_parser("doctor", help="检查配置、扩展点与本地环境")
    return parser


def _build_service(
    settings: Settings,
    repository: FileResearchRepository,
    strategies: StrategyRegistry,
) -> MonitoringService:
    return MonitoringService(
        settings=settings,
        market_data=FallbackMarketDataProvider(),
        repository=repository,
        strategies=strategies,
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
    service = NotificationService(
        settings,
        build_notification_channels(settings),
    )
    return service.send(
        symbol,
        event,
        markdown,
        title=title,
        force=force,
    )


def _doctor(
    root: Path,
    settings: Settings,
    strategies: StrategyRegistry,
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
    build_notification_channels(settings)
    print(f"项目目录：{root}")
    print(f"Python：{sys.version.split()[0]}")
    print(f"配置：正常（{len(settings.instruments)} 个标的）")
    print(f"策略：正常（{', '.join(strategies.ids)}）")
    print(f"策略画像：正常（{len(settings.strategy_profiles)} 个）")
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
    print(f"TraeCode CLI：{shutil.which('traecli') or '未安装'}")


def main() -> int:
    args = _parser().parse_args()
    root = _root()
    try:
        settings = load_settings(root, args.config)
        repository = FileResearchRepository(settings.data_dir)
        strategies = StrategyRegistry.default()

        if args.command == "doctor":
            _doctor(root, settings, strategies)
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

        if args.command == "dashboard":
            output = args.output or settings.data_dir / "dashboard" / "index.html"
            if not output.is_absolute():
                output = root / output
            print(write_dashboard(output, repository.list_latest_packets()))
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

        service = _build_service(settings, repository, strategies)
        for symbol in _symbols(args, settings):
            if args.command == "prepare":
                path, _ = service.prepare(symbol)
                print(path)
                continue

            if args.command == "base-report":
                packet = repository.load_latest_packet(symbol)
            elif args.command == "daily":
                _, packet = service.prepare(symbol)
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
        return 0
    except (
        DataSourceError,
        NotificationError,
        FileNotFoundError,
        ValueError,
        OSError,
    ) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
