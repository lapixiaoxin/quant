"""回测层：把数据与策略喂给 AKQuant 引擎，产出结果与 HTML 报告。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from akquant import BacktestResult, Strategy, run_backtest

from ..settings import Settings, get_settings


def run(
    data: Union[pd.DataFrame, dict[str, pd.DataFrame]],
    strategy: type[Strategy] = Strategy,
    symbols: Optional[Union[str, list[str]]] = None,
    settings: Optional[Settings] = None,
    report_path: Optional[Path | str] = None,
    benchmark: Optional[pd.Series] = None,
) -> BacktestResult:
    """执行一次回测。

    :param data: 单只标的的 DataFrame，或 ``{symbol: df}``。
    :param strategy: 策略类（默认需显式传入 ``MaCrossStrategy``）。
    :param symbols: 标的代码；单标的传字符串，多标的传列表。
    :param settings: 费率/资金配置，默认取全局 Settings。
    :param report_path: 若给定则生成 HTML 报告到该路径。
    :param benchmark: 可选的基准收益序列（如沪深300日收益）。
    """
    cfg = settings or get_settings()

    kwargs: dict[str, object] = dict(
        data=data,
        strategy=strategy,
        symbols=symbols,
        initial_cash=cfg.initial_cash,
        commission_rate=cfg.commission_rate,
        stamp_tax_rate=cfg.stamp_tax_rate,
        transfer_fee_rate=cfg.transfer_fee_rate,
        min_commission=cfg.min_commission,
        slippage={"type": "percent", "value": cfg.slippage},
        volume_limit_pct=cfg.volume_limit_pct,
        t_plus_one=cfg.t_plus_one,
        show_progress=False,
    )
    if cfg.broker_profile:
        kwargs["broker_profile"] = cfg.broker_profile

    result = run_backtest(**kwargs)

    if report_path is not None:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        result.viz.report(
            filename=str(report_path),
            show=False,
            market_data=data,
            benchmark=benchmark,
        )
    return result


def summary(result: BacktestResult) -> pd.DataFrame:
    """返回核心绩效指标子集，便于终端打印。"""
    keys = [
        "total_return_pct",
        "annualized_return",
        "sharpe_ratio",
        "max_drawdown_pct",
        "win_rate",
        "closed_trade_count",
        "total_commission",
    ]
    metrics = result.metrics_df
    present = [k for k in keys if k in metrics.index]
    return metrics.loc[present]
