"""命令行入口：``qtrader data-sync / backtest / live``。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .backtest import run as run_backtest
from .backtest import summary as backtest_summary
from .data import load_universe
from .live import run_session
from .screening import DISPLAY_COLUMNS, REPORT_COLUMNS, FunnelConfig, run_screen
from .settings import get_settings
from .strategy import MaCrossStrategy

app = typer.Typer(help="基于 akfamily（AKShare + AKQuant）的 A 股量化程序", no_args_is_help=True)
console = Console()


def _parse_symbols(raw: str) -> list[str]:
    symbols = [s.strip() for s in raw.split(",") if s.strip()]
    if not symbols:
        raise typer.BadParameter("至少需要一个标的，如 sh600000,sz000001")
    return symbols


def _fmt(value: object, digits: int = 2) -> str:
    """数值格式化；空值与 NaN 显示为 ``-``。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:.{digits}f}" if number == number else "-"


def _pct(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:.1%}" if number == number else "-"


@app.command("data-sync")
def data_sync(
    symbols: str = typer.Option(..., "--symbols", "-s", help="逗号分隔，如 sh600000,sz000001"),
    start: str = typer.Option("20230101", help="开始日期 YYYYMMDD"),
    end: str = typer.Option("20231231", help="结束日期 YYYYMMDD"),
    refresh: bool = typer.Option(False, help="忽略缓存强制重抓"),
    adjust: str = typer.Option(
        "", "--adjust", help="复权方式：留空=不复权，qfq=前复权，hfq=后复权"
    ),
) -> None:
    """抓取日线并写入本地 Parquet 缓存。"""
    for symbol in _parse_symbols(symbols):
        df = load_universe([symbol], start, end, refresh=refresh, adjust=adjust)[symbol]
        console.print(f"[green]{symbol}[/green] 缓存 {len(df)} 行 -> {df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}")


@app.command("backtest")
def backtest(
    symbols: str = typer.Option("sh600000", "--symbols", "-s", help="逗号分隔的标的"),
    start: str = typer.Option("20230101", help="开始日期 YYYYMMDD"),
    end: str = typer.Option("20231231", help="结束日期 YYYYMMDD"),
    report: Optional[Path] = typer.Option(None, "--report", help="HTML 报告输出路径"),
    refresh: bool = typer.Option(False, help="忽略缓存强制重抓"),
    adjust: str = typer.Option(
        "", "--adjust", help="复权方式：留空=不复权，qfq=前复权，hfq=后复权"
    ),
) -> None:
    """运行回测并打印核心绩效指标。"""
    codes = _parse_symbols(symbols)
    universe = load_universe(codes, start, end, refresh=refresh, adjust=adjust)
    data = universe[codes[0]] if len(codes) == 1 else universe
    symbol_arg: str | list[str] = codes[0] if len(codes) == 1 else codes

    result = run_backtest(
        data=data,
        strategy=MaCrossStrategy,
        symbols=symbol_arg,
        report_path=report,
    )

    table = Table(title="回测结果")
    table.add_column("指标")
    table.add_column("数值", justify="right")
    for name, row in backtest_summary(result).iterrows():
        table.add_row(str(name), f"{row['value']:.4f}")
    console.print(table)
    if report is not None:
        console.print(f"报告已写入 [cyan]{report}[/cyan]")


@app.command("live")
def live(
    symbols: str = typer.Option("sh600000", "--symbols", "-s", help="逗号分隔的标的"),
    start: str = typer.Option("20230101", help="paper 模式回放数据的开始日期"),
    end: str = typer.Option("20231231", help="paper 模式回放数据的结束日期"),
    duration: Optional[str] = typer.Option("30s", help="运行时长，如 30s / 1m"),
    adjust: str = typer.Option(
        "", "--adjust", help="paper 模式回放数据的复权方式：留空=不复权，qfq=前复权，hfq=后复权"
    ),
) -> None:
    """启动实盘/仿真会话（模式由配置 live_trading_mode 决定）。"""
    cfg = get_settings()
    codes = _parse_symbols(symbols)

    data = None
    if cfg.is_paper:
        universe = load_universe(codes, start, end, adjust=adjust)
        data = universe[codes[0]] if len(codes) == 1 else universe

    console.print(f"启动 [bold]{cfg.live_trading_mode}[/bold] 会话，标的 {codes}，时长 {duration}")
    run_session(strategy=MaCrossStrategy, symbols=codes, data=data, duration=duration)


@app.command("screen")
def screen(
    symbols: Optional[str] = typer.Option(
        None, "--symbols", "-s", help="指定标的（逗号分隔）；不给则走全市场快照"
    ),
    end: Optional[str] = typer.Option(None, help="结束日期 YYYYMMDD，默认今天"),
    years: float = typer.Option(3.0, help="指标统计窗口（年）"),
    min_amount: float = typer.Option(1.0, help="第0层: 最小成交额（亿元）"),
    min_turnover: float = typer.Option(3.0, help="第0层: 最小换手率 %"),
    max_turnover: float = typer.Option(12.0, help="第0层: 最大换手率 %"),
    include_bj: bool = typer.Option(False, help="第0层: 是否纳入北交所标的"),
    max_candidates: int = typer.Option(200, help="第0层: 候选上限，决定抓取次数与耗时"),
    min_swings: float = typer.Option(3.0, help="第1层: 年均最少波段次数"),
    top: int = typer.Option(30, help="终端展示前 N 名"),
    out: Optional[Path] = typer.Option(None, "--out", help="候选名单 CSV 输出路径"),
    refresh: bool = typer.Option(False, help="忽略缓存强制重抓"),
) -> None:
    """四层漏斗筛选适合做波段的标的。"""
    codes = _parse_symbols(symbols) if symbols else None
    config = FunnelConfig(years=years, min_swings_per_year=min_swings)

    def on_progress(done: int, total: int, symbol: str) -> None:
        if done == 1 or done == total or done % 25 == 0:
            console.print(f"  [dim]处理 {done}/{total} {symbol}[/dim]")

    console.print(f"筛选开始：窗口 {years:.1f} 年，第0层候选上限 {max_candidates}")
    result = run_screen(
        codes,
        end=end,
        config=config,
        min_amount=min_amount * 1e8,
        min_turnover_rate=min_turnover,
        max_turnover_rate=max_turnover,
        include_bj=include_bj,
        max_candidates=max_candidates,
        refresh=refresh,
        progress=on_progress,
    )

    if result.empty:
        console.print("[yellow]没有候选标的[/yellow]")
        raise typer.Exit()

    console.print("\n[bold]漏斗分布[/bold]")
    for reason, count in result["funnel"].value_counts().items():
        console.print(f"  {reason}: {count}")

    passed = result[result["passed"]]
    shown = min(top, len(passed))
    table = Table(title=f"适合做波段的候选（展示前 {shown} / 共 {len(passed)}）")
    for _, label, kind in DISPLAY_COLUMNS:
        table.add_column(label, justify="left" if kind == "text" else "right")

    def _cell(value: object, kind: str) -> str:
        if kind == "text":
            return "-" if value is None else str(value)
        return _pct(value) if kind == "pct" else _fmt(value)

    for _, row in passed.head(top).iterrows():
        table.add_row(*(_cell(row.get(field), kind) for field, _, kind in DISPLAY_COLUMNS))
    console.print(table)

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        ordered = [c for c in REPORT_COLUMNS if c in result.columns]
        ordered += [c for c in result.columns if c not in ordered and c != "passed"]
        result[ordered].to_csv(out, index=False, encoding="utf-8-sig")
        console.print(f"完整结果已写入 [cyan]{out}[/cyan]（{len(result)} 行，含未通过标的）")


if __name__ == "__main__":
    app()
