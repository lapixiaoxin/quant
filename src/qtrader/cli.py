"""命令行入口：``qtrader data-sync / backtest / live / screen``。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from .backtest import run as run_backtest
from .backtest import summary as backtest_summary
from .data import load_etf_universe, load_universe
from .live import run_session
from .screening import (
    DISPLAY_COLUMNS,
    REPORT_COLUMNS,
    FunnelConfig,
    run_out_of_sample,
    run_screen,
)
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


def _load_bars(
    codes: list[str], start: str, end: str, *, asset: str, adjust: str, refresh: bool
) -> dict[str, pd.DataFrame]:
    """按资产类型选择数据源：个股走 ``load_universe``，ETF 走 ``load_etf_universe``。"""
    if asset == "etf":
        return load_etf_universe(codes, start, end, refresh=refresh)
    return load_universe(codes, start, end, refresh=refresh, adjust=adjust)


@app.command("data-sync")
def data_sync(
    symbols: str = typer.Option(..., "--symbols", "-s", help="逗号分隔，如 sh600000,sz000001"),
    start: str = typer.Option("20230101", help="开始日期 YYYYMMDD"),
    end: str = typer.Option("20231231", help="结束日期 YYYYMMDD"),
    refresh: bool = typer.Option(False, help="忽略缓存强制重抓"),
    asset: str = typer.Option("stock", "--asset", help="资产类型：stock 个股 / etf 基金"),
    adjust: str = typer.Option("", "--adjust", help="个股复权方式：留空=不复权，qfq=前复权，hfq=后复权"),
) -> None:
    """抓取行情并写入本地 Parquet 缓存。"""
    for symbol in _parse_symbols(symbols):
        df = _load_bars([symbol], start, end, asset=asset, adjust=adjust, refresh=refresh)[symbol]
        console.print(f"[green]{symbol}[/green] 缓存 {len(df)} 行 -> {df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}")


@app.command("backtest")
def backtest(
    symbols: str = typer.Option("sh600000", "--symbols", "-s", help="逗号分隔的标的"),
    start: str = typer.Option("20230101", help="开始日期 YYYYMMDD"),
    end: str = typer.Option("20231231", help="结束日期 YYYYMMDD"),
    report: Optional[Path] = typer.Option(None, "--report", help="HTML 报告输出路径"),
    refresh: bool = typer.Option(False, help="忽略缓存强制重抓"),
    asset: str = typer.Option("stock", "--asset", help="资产类型：stock 个股 / etf 基金"),
    adjust: str = typer.Option("", "--adjust", help="个股复权方式：留空=不复权，qfq=前复权，hfq=后复权"),
) -> None:
    """运行回测并打印核心绩效指标。"""
    codes = _parse_symbols(symbols)
    universe = _load_bars(codes, start, end, asset=asset, adjust=adjust, refresh=refresh)
    data = universe[codes[0]] if len(codes) == 1 else universe
    symbol_arg: str | list[str] = codes[0] if len(codes) == 1 else codes

    # 资产类型进入 Settings，决定费率口径（ETF 免印花税）与撮合资产
    cfg = get_settings().model_copy(update={"asset_type": asset})
    result = run_backtest(
        data=data,
        strategy=MaCrossStrategy,
        symbols=symbol_arg,
        settings=cfg,
        report_path=report,
    )

    table = Table(title=f"回测结果（{asset}）")
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
    asset: str = typer.Option("stock", "--asset", help="资产类型：stock 个股 / etf 基金"),
    adjust: str = typer.Option(
        "", "--adjust", help="paper 模式回放数据的个股复权方式：留空=不复权，qfq=前复权"
    ),
) -> None:
    """启动实盘/仿真会话（模式由配置 live_trading_mode 决定）。"""
    codes = _parse_symbols(symbols)
    cfg = get_settings().model_copy(update={"asset_type": asset})

    data = None
    if cfg.is_paper:
        universe = _load_bars(codes, start, end, asset=asset, adjust=adjust, refresh=False)
        data = universe[codes[0]] if len(codes) == 1 else universe

    console.print(f"启动 [bold]{cfg.live_trading_mode}[/bold] 会话，标的 {codes}，时长 {duration}")
    run_session(strategy=MaCrossStrategy, symbols=codes, data=data, duration=duration, settings=cfg)


@app.command("screen")
def screen(
    symbols: Optional[str] = typer.Option(
        None, "--symbols", "-s", help="指定标的（逗号分隔）；不给则按资产类型走快照"
    ),
    asset: str = typer.Option("stock", "--asset", help="资产类型：stock 个股 / etf 基金"),
    period: str = typer.Option("weekly", help="指标周期：weekly 周线 / daily 日线"),
    end: Optional[str] = typer.Option(None, help="结束日期 YYYYMMDD，默认今天"),
    years: Optional[float] = typer.Option(None, help="统计窗口（年），默认按周期预设"),
    min_swings: Optional[float] = typer.Option(None, help="第1层：年均最少波段次数"),
    min_amount: Optional[float] = typer.Option(None, help="第0层：最小成交额（亿元）"),
    max_candidates: Optional[int] = typer.Option(None, help="第0层：候选上限"),
    include_bj: bool = typer.Option(False, help="第0层：是否纳入北交所标的"),
    validate: bool = typer.Option(False, "--validate", help="做样本外验证（前段筛选 / 后段检验）"),
    train_years: float = typer.Option(3.0, help="样本外：筛选窗口（年）"),
    test_years: float = typer.Option(2.0, help="样本外：检验窗口（年）"),
    top: int = typer.Option(30, help="终端展示前 N 名"),
    out: Optional[Path] = typer.Option(None, "--out", help="结果 CSV 输出路径"),
    refresh: bool = typer.Option(False, help="忽略缓存强制重抓"),
) -> None:
    """筛选适合做波段的标的（四层漏斗 + 可选样本外验证）。"""
    codes = _parse_symbols(symbols) if symbols else None
    config = FunnelConfig.for_period(period, years=years)
    if min_swings is not None:
        config = replace(config, min_swings_per_year=min_swings)

    extra: dict[str, object] = {"include_bj": include_bj}
    if min_amount is not None:
        extra["min_amount"] = min_amount * 1e8
    if max_candidates is not None:
        extra["max_candidates"] = max_candidates

    def on_progress(done: int, total: int, symbol: str) -> None:
        if done == 1 or done == total or done % 25 == 0:
            console.print(f"  [dim]处理 {done}/{total} {symbol}[/dim]")

    console.print(
        f"筛选：资产 {asset}，周期 {period}，窗口 {config.years:.1f} 年，"
        f"zigzag 阈值 {config.swing_threshold:.0%}"
    )

    if validate:
        merged = run_out_of_sample(
            codes,
            asset=asset,
            period=period,
            train_years=train_years,
            test_years=test_years,
            config=config,
            refresh=refresh,
            progress=on_progress,
            **extra,
        )
        if merged.empty:
            console.print("[yellow]前段窗口没有通过筛选的标的[/yellow]")
            raise typer.Exit()
        survived = int(merged["survived"].sum())
        table = Table(title=f"样本外验证（前 {train_years:.0f} 年筛选 / 后 {test_years:.0f} 年检验）")
        for column, justify in [
            ("代码", "left"),
            ("名称", "left"),
            ("前段评分", "right"),
            ("前段波段/年", "right"),
            ("后段漏斗", "right"),
            ("后段波段/年", "right"),
            ("后段波动", "right"),
            ("后段回撤", "right"),
            ("存活", "right"),
        ]:
            table.add_column(column, justify=justify)
        for _, row in merged.head(top).iterrows():
            table.add_row(
                str(row["symbol"]),
                str(row["name"]),
                _fmt(row.get("train_score")),
                _fmt(row.get("train_swings_per_year")),
                str(row.get("test_funnel", "-")),
                _fmt(row.get("test_swings_per_year")),
                _pct(row.get("test_annual_volatility")),
                _pct(row.get("test_max_drawdown")),
                "是" if row.get("survived") else "否",
            )
        console.print(table)
        console.print(f"前段入选 {len(merged)} 只，后段仍通过 [bold]{survived}[/bold] 只")
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            merged.to_csv(out, index=False, encoding="utf-8-sig")
            console.print(f"完整结果已写入 [cyan]{out}[/cyan]")
        return

    result = run_screen(
        codes,
        asset=asset,
        period=period,
        end=end,
        config=config,
        refresh=refresh,
        progress=on_progress,
        **extra,
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
