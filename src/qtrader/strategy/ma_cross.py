"""示例策略：双均线交叉。

同一份代码既能在 ``run_backtest`` 回测，也能在 ``run_live`` 实盘运行——
这是 AKQuant 事件驱动引擎的核心优势。
"""

from __future__ import annotations

import numpy as np

from akquant import Strategy


class MaCrossStrategy(Strategy):
    """快线（fast）上穿慢线（slow）买入，下穿清仓。"""

    fast: int = 5
    slow: int = 20
    trade_size: int = 1000

    # 引擎会在攒够 warmup_period 根 K 线后才进入正常决策
    warmup_period: int = 20

    def on_start(self) -> None:
        # get_history 必须先声明回溯长度，否则读取历史会直接报错
        self.set_history_depth(self.slow + 1)

    def on_bar(self, bar) -> None:
        closes = self.get_history(self.slow + 1, symbol=bar.symbol, field="close")
        if closes.shape[0] < self.slow + 1:
            return

        fast_now = float(np.mean(closes[-self.fast:]))
        fast_prev = float(np.mean(closes[-self.fast - 1:-1]))
        slow_now = float(np.mean(closes[-self.slow:]))
        slow_prev = float(np.mean(closes[-self.slow - 1:-1]))

        position = self.get_position(bar.symbol)
        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        if position == 0 and crossed_up:
            self.buy(symbol=bar.symbol, quantity=self.trade_size)
        elif position > 0 and crossed_down:
            self.close_position(symbol=bar.symbol)
