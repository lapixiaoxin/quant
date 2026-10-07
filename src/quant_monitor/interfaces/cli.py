"""轻量研究工具组合根：数据、策略、模型、实验与文档登记。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from dataclasses import asdict, replace
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from ..application.analysis import AnalysisService
from ..application.backtesting import BacktestService, save_backtest_result
from ..application.monitoring import MonitoringService
from ..application.selection import SelectionService
from ..config import Settings, load_settings
from ..domain.backtesting import BacktestSpecification
from ..domain.backtesting.registry import MODEL_REGISTRY
from ..domain.control_plane import AnalysisCycle, BacktestRunRecord, SelectionRunRecord
from ..domain.factors import FactorRegistry
from ..domain.strategies import StrategyRegistry
from ..infrastructure.control_repository import SQLiteControlPlaneRepository
from ..infrastructure.documents import DocumentRegistry
from ..infrastructure.history import SQLiteMarketHistoryRepository
from ..infrastructure.index_valuation import LixingerIndexValuationProvider
from ..infrastructure.market_data import FallbackMarketDataProvider
from ..infrastructure.selection_config import load_selection_universe
from ..infrastructure.storage import FileResearchRepository
from ..infrastructure.strategy_catalog import (
    StrategyCatalog,
    load_strategy_catalog,
    strategy_profile_fingerprint,
)
from .backtest_study import run_study
from .reporting import build_base_report


class ChineseArgumentParser(argparse.ArgumentParser):
    """本地化命令行帮助。"""

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


def _parser() -> argparse.ArgumentParser:
    parser = ChineseArgumentParser(description="Agent 投资研究工具箱")
    parser.add_argument("--config", type=Path, help="指定 TOML 配置")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("prepare", "采集行情与指标；不要求绑定策略"),
        ("base-report", "将最新数据转换为本地 Markdown 草稿"),
        ("history-sync", "同步日线并检查配置的覆盖首日"),
        ("history", "查看或导出本地日线"),
        ("analyze", "显式评估启用策略并保存研究基线"),
    ):
        child = commands.add_parser(name, help=help_text)
        targets = child.add_mutually_exclusive_group()
        targets.add_argument("--symbol", help="单个标的代码")
        targets.add_argument("--symbols", help="逗号分隔的标的代码")
        targets.add_argument("--all", action="store_true", help="全部启用标的")
        if name == "history":
            child.add_argument("--output", type=Path, help="单标的 CSV 导出路径")
            child.add_argument("--start", type=date.fromisoformat, help="起始日")
            child.add_argument("--end", type=date.fromisoformat, help="截止日")
        if name == "analyze":
            child.add_argument(
                "--cycle",
                action="append",
                choices=tuple(item.value for item in AnalysisCycle),
                help="可重复指定分析周期",
            )
            child.add_argument("--factors", help="逗号分隔的因子 ID")
    for name, help_text in (
        ("doctor", "验证配置、策略引用、文档索引与数据库完整性"),
        ("instruments", "列出标的"),
        ("models", "列出可执行模型及适用入口"),
    ):
        commands.add_parser(name, help=help_text)
    for name in ("strategies", "reports"):
        child = commands.add_parser(name, help="查询策略版本或文档索引")
        child.add_argument("--symbol", help="按标的过滤")
    register = commands.add_parser("report-register", help="验证并登记报告元数据 JSON")
    register.add_argument(
        "metadata", type=Path, help="元数据文件；契约见 research/README.md"
    )
    backtest = commands.add_parser("backtest", help="执行本地历史或冻结快照回测")
    source = backtest.add_mutually_exclusive_group(required=True)
    source.add_argument("--strategy-record", help="策略目录 record_id")
    source.add_argument("--study", type=Path, help="冻结研究规格 JSON")
    backtest.add_argument("--symbol", help="覆盖记录中的首个标的")
    backtest.add_argument("--start", type=date.fromisoformat, help="起始日")
    backtest.add_argument("--end", type=date.fromisoformat, help="截止日")
    valuation = commands.add_parser("valuation-sync", help="同步带时点的指数估值")
    valuation.add_argument("--strategy-record", required=True, help="策略记录 ID")
    valuation.add_argument("--input", type=Path, help="可选的公开 pageData 脚本")
    select = commands.add_parser("select", help="计算候选池指标、硬门槛与证据缺口")
    select.add_argument("--universe", required=True, type=Path, help="候选池 TOML")
    return parser


def _symbols(args: argparse.Namespace, settings: Settings) -> tuple[str, ...]:
    if args.all:
        symbols = tuple(item.symbol for item in settings.enabled_instruments)
    elif args.symbols:
        symbols = tuple(
            dict.fromkeys(
                item.strip() for item in args.symbols.split(",") if item.strip()
            )
        )
    elif args.symbol:
        symbols = (args.symbol,)
    else:
        symbols = tuple(item.symbol for item in settings.enabled_instruments[:1])
    if not symbols:
        raise ValueError("请配置或指定至少一个标的")
    for symbol in symbols:
        settings.instrument_for(symbol)
    return symbols


def _catalog(root: Path) -> StrategyCatalog:
    path = root / "research/strategies/catalog.toml"
    return load_strategy_catalog(path) if path.exists() else StrategyCatalog(1, ())


def _backtest(args, settings, history, control, strategies, catalog) -> Path:
    if args.study:
        if args.symbol or args.start or args.end:
            raise ValueError("冻结研究不能覆盖标的或日期；请创建新版本规格")
        return run_study(
            settings.root,
            args.study.resolve(),
            settings.data_dir,
            control,
            catalog,
        )
    record = catalog.record(args.strategy_record)
    symbol = args.symbol or record.symbols[0]
    instrument = settings.instrument_for(symbol)
    profile = settings.strategy_profiles.get(record.profile_id)
    if profile is None or strategy_profile_fingerprint(profile) != (
        record.parameters_fingerprint
    ):
        raise ValueError("回测策略参数与冻结指纹不一致；请保留旧配置或新建版本")
    summary = history.summarize(symbol)
    start, end = args.start or summary.first_date, args.end or summary.last_date
    if start is None or end is None:
        raise ValueError(f"标的 {symbol} 没有可回测的历史数据")
    now = datetime.now().astimezone()
    run_id = f"{now:%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
    path = settings.data_dir / "backtests" / symbol / f"{run_id}.json"
    pending = BacktestRunRecord(
        run_id,
        record.record_id,
        symbol,
        now,
        None,
        "running",
        str(path.relative_to(settings.root)),
    )
    control.save_backtest(pending)
    try:
        result = BacktestService(history, strategies, catalog).run(
            instrument,
            profile.parameters,
            BacktestSpecification(
                symbol=symbol,
                model_id=record.backtest_model_id,
                model_version=record.backtest_model_version,
                parameters_fingerprint=record.parameters_fingerprint,
                start_date=start,
                end_date=end,
            ),
            strategy_record_id=record.record_id,
        )
        save_backtest_result(path, result)
    except (OSError, RuntimeError, ValueError) as error:
        control.save_backtest(
            replace(
                pending,
                status="failed",
                completed_at=datetime.now().astimezone(),
                error=str(error),
            )
        )
        raise
    control.save_backtest(
        replace(
            pending,
            status="completed",
            completed_at=datetime.now().astimezone(),
            total_return=result.metrics.total_return,
            max_drawdown=result.metrics.max_drawdown,
            trade_count=result.metrics.trade_count,
        )
    )
    return path


def main() -> int:
    args = _parser().parse_args()
    root = Path(os.environ.get("QUANT_MONITOR_ROOT", Path.cwd())).resolve()
    try:
        settings = load_settings(root, args.config)
        repository = FileResearchRepository(settings.data_dir)
        documents = DocumentRegistry(root)
        if args.command in {"reports", "report-register"}:
            if args.command == "report-register":
                documents.register(
                    json.loads(args.metadata.read_text(encoding="utf-8"))
                )
            print(
                json.dumps(
                    documents.list(getattr(args, "symbol", None)),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "instruments":
            for item in settings.instruments:
                print(
                    f"{item.symbol}\t{item.instrument_type.value}\t{item.name}\t"
                    f"策略：{','.join(item.strategy_profile_ids) or '未绑定'}"
                )
            return 0
        if args.command == "models":
            for model in MODEL_REGISTRY:
                implementation = model.implementation
                print(
                    f"{implementation.model_id}\t{implementation.model_version}"
                    f"\t{model.entry}\t{model.requirements}"
                    f"\t{implementation.__module__}.{implementation.__name__}"
                )
            return 0
        # 数据探索不解析策略目录；其他标的的策略漂移不会阻断采集。
        catalog = (
            _catalog(root)
            if args.command in {"doctor", "strategies", "backtest", "analyze"}
            else StrategyCatalog(1, ())
        )
        strategies = StrategyRegistry.default()
        factors = FactorRegistry.default()
        history = SQLiteMarketHistoryRepository(
            settings.data_dir / "history/market.sqlite3",
        )
        control = SQLiteControlPlaneRepository(
            settings.data_dir / "control/research.sqlite3",
        )
        if args.command == "doctor":
            for profile in settings.strategy_profiles.values():
                strategies.get(profile.strategy_id).validate_parameters(
                    profile.parameters,
                    profile_id=profile.profile_id,
                )
            catalog.validate_settings(settings)
            documents.list()
            for path in (history.database_path, control.database_path):
                with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                    if connection.execute("PRAGMA integrity_check").fetchall() != [
                        ("ok",)
                    ]:
                        raise ValueError(f"数据库完整性检查失败：{path}")
                print(f"数据库完整性：正常 {path}")
            for path in (root / "research/universes").glob("*.toml"):
                load_selection_universe(path)
            print(
                f"配置：{len(settings.instruments)} 个标的；"
                f"策略目录：{len(catalog.records)} 个版本"
            )
            print(f"研究文档：{documents.root_url}")
            if settings.ignored_legacy_sections:
                print("已忽略旧配置段：" + "、".join(settings.ignored_legacy_sections))
            print("本命令未验证飞书登录或远端文档内容。")
            return 0
        if args.command == "strategies":
            for item in catalog.records:
                if not args.symbol or item.applies_to(args.symbol):
                    print(
                        f"{item.record_id}\t{item.version}\t{item.lifecycle.value}"
                        f"\t{item.validation_state.value}\t{item.name}"
                    )
            return 0
        if args.command == "backtest":
            print(_backtest(args, settings, history, control, strategies, catalog))
            return 0
        if args.command == "valuation-sync":
            record = _catalog(root).record(args.strategy_record)
            values = record.backtest_parameters
            index = str(values.get("valuation_symbol", ""))
            exchange = str(values.get("valuation_exchange", ""))
            ticker = int(values.get("valuation_ticker_id", 0))
            if not index or not exchange or ticker <= 0:
                raise ValueError("策略记录缺少估值源标识")
            provider = LixingerIndexValuationProvider()
            observations = (
                provider.parse(
                    args.input.read_text(encoding="utf-8"),
                    index_code=index,
                    source_url=provider.page_url_template.format(
                        exchange=exchange,
                        index_code=index,
                        ticker_id=ticker,
                    ),
                )
                if args.input
                else provider.fetch(
                    exchange=exchange,
                    index_code=index,
                    ticker_id=ticker,
                )
            )
            history.save_valuation_observations(
                observations, datetime.now().astimezone()
            )
            print(f"估值：{index}，{len(observations)} 根")
            return 0
        if args.command == "select":
            universe = load_selection_universe(args.universe.resolve())
            path, packet = SelectionService(
                settings,
                FallbackMarketDataProvider(),
                history,
                repository,
            ).prepare(universe)
            now = datetime.fromisoformat(packet["as_of"])
            control.save_selection(
                SelectionRunRecord(
                    f"{universe.universe_id}:{uuid4().hex}",
                    universe.universe_id,
                    universe.horizon,
                    universe.theme,
                    now,
                    "screened",
                    packet["summary"]["candidate_count"],
                    packet["summary"]["eligible"],
                    str(path.relative_to(root)),
                    "",
                )
            )
            print(path)
            return 0
        symbols = _symbols(args, settings)
        if args.command == "history":
            if args.output and len(symbols) != 1:
                raise ValueError("CSV 导出一次只支持一个标的")
            if args.start and args.end and args.start > args.end:
                raise ValueError("起始日不能晚于截止日")
            for symbol in symbols:
                print(history.summarize(symbol))
                if args.output:
                    bars = history.load_bars(
                        symbol,
                        start_date=args.start,
                        end_date=args.end,
                    )
                    if not bars:
                        raise ValueError("指定范围没有可导出的行情")
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    with args.output.open("x", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=asdict(bars[0]))
                        writer.writeheader()
                        writer.writerows(asdict(item) for item in bars)
                    print(f"日线导出：{args.output}；价格为前复权，成交额为元")
            return 0
        monitoring = MonitoringService(
            settings,
            FallbackMarketDataProvider(),
            history,
            repository,
            strategies,
            strategy_catalog=catalog,
        )
        if args.command == "analyze":
            service = AnalysisService(
                settings,
                monitoring,
                repository,
                control,
                factors,
                build_base_report,
            )
            request = service.create_request(
                symbols=symbols,
                cycles=tuple(
                    AnalysisCycle.parse(item)
                    for item in (args.cycle or ("daily", "moving_average"))
                ),
                factor_ids=tuple(
                    filter(
                        None, (item.strip() for item in (args.factors or "").split(","))
                    )
                ),
            )
            execution = service.run(request)
            print(f"分析请求：{execution.request_path}")
            for result in execution.results:
                print(result.report_path)
            for error in execution.errors:
                print(f"失败：{error}", file=sys.stderr)
            return 1 if execution.errors else 0
        errors = []
        for symbol in symbols:
            try:
                if args.command == "prepare":
                    print(monitoring.prepare(symbol)[0])
                elif args.command == "history-sync":
                    print(monitoring.sync_history(symbol).summary)
                else:
                    packet = repository.load_latest_packet(symbol)
                    print(
                        repository.save_base_report(
                            symbol,
                            str(packet["as_of"]),
                            build_base_report(packet),
                        )
                    )
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(f"{symbol}：{error}")
        for error in errors:
            print(f"失败：{error}", file=sys.stderr)
        return 1 if errors else 0
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        sqlite3.Error,
    ) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
