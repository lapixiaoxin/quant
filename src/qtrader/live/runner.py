"""实盘层：封装 AKQuant ``run_live``。

两种模式：
- ``paper``     ：本地回放行情（replay）+ 内置仿真交易通道，无需真实柜台，可先验证全链路。
- ``broker_live``：接真实柜台（CTP 原生支持；QMT/PTrade 需另装券商插件）。

同一份策略代码在回测与实盘之间保持一等公民地位。
"""

from __future__ import annotations

from typing import Optional, Union

import pandas as pd

from akquant import AssetType, Instrument, Strategy, run_live
from akquant.normalize import dataframe_to_bars

from ..settings import Settings, get_settings


def _instruments(symbols: list[str]) -> list[Instrument]:
    return [Instrument(symbol=s, asset_type=AssetType.Stock) for s in symbols]


def _replay_bars(data: dict[str, pd.DataFrame]) -> list:
    bars: list = []
    for symbol, df in data.items():
        bars.extend(dataframe_to_bars(df, symbol=symbol))
    return bars


def run_session(
    strategy: type[Strategy],
    symbols: list[str],
    data: Optional[Union[pd.DataFrame, dict[str, pd.DataFrame]]] = None,
    settings: Optional[Settings] = None,
    duration: Optional[str] = None,
) -> None:
    """启动一次实盘/仿真会话（阻塞直到结束或到达 ``duration``）。

    :param strategy: 策略类。
    :param symbols: 交易标的列表。
    :param data: ``paper`` 模式必需的行情回放数据，单只 DataFrame 或 ``{symbol: df}``。
    :param settings: 配置，默认取全局 Settings。
    :param duration: 可选运行时长，如 ``"30s"``、``"1m"``。
    """
    cfg = settings or get_settings()
    options: dict[str, object] = dict(cfg.gateway_options())

    if cfg.is_paper:
        if data is None:
            raise ValueError("paper 模式需要传入行情数据 data")
        normalized = {symbols[0]: data} if isinstance(data, pd.DataFrame) else data
        options["bars"] = _replay_bars(normalized)
        options["freq"] = "1d"
        market_broker: Optional[str] = "replay"
        trader_broker: Optional[str] = cfg.live_trader_broker or "miniqmt"
        trading_mode = "paper"
    else:
        market_broker = cfg.live_market_broker or None
        trader_broker = cfg.live_trader_broker or None
        trading_mode = "broker_live"

    run_live(
        strategy_cls=strategy,
        instruments=_instruments(symbols),
        cash=cfg.initial_cash,
        market_broker=market_broker,
        trader_broker=trader_broker,
        trading_mode=trading_mode,
        gateway_options=options,
        show_progress=False,
        duration=duration,
    )
