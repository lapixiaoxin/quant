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
from .settings import get_settings
from .strategy import MaCrossStrategy

app = typer.Typer(help="基于 akfamily（AKShare + AKQuant）的 A 股量化程序", no_args_is_help=True)
console = Console()


def _parse_symbols(raw: str) -> list[str]:
    symbols = [s.strip() for s in raw.split(",") if s.strip()]
    if not symbols:
        raise typer.BadParameter("至少需要一个标的，如 sh600000,sz000001")
    return symbols


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


if __name__ == "__main__":
    app()
