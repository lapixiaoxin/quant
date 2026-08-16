"""把动态股息率研究策略转换为可回放的目标仓位。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..models import DailyBar, Instrument, ValuationObservation
from ..strategies.etf import DividendYieldDynamicStrategy
from .models import BacktestSignal


class DividendYieldPercentileAllocationModel:
    """使用来源逐日分位，在月度频率映射研究目标仓位。"""

    model_id = "dividend_yield_percentile_allocation"
    model_version = "1.0.0"
    minimum_bars = 242

    def __init__(
        self,
        strategy: DividendYieldDynamicStrategy,
        valuations: Sequence[ValuationObservation],
    ) -> None:
        windows = {item.history_window for item in valuations}
        if len(windows) > 1:
            raise ValueError("一次回测不能混用多个估值历史窗口")
        self._strategy = strategy
        self._valuations = {
            item.observation_date: item for item in valuations
        }
        self._history_observations = {
            "y3": 726,
            "y5": 1_210,
            "y10": 2_420,
        }.get(next(iter(windows), ""), 0)

    def validate_parameters(self, parameters: dict[str, Any]) -> None:
        strategy_parameters = parameters.get("strategy_parameters", {})
        if not isinstance(strategy_parameters, dict):
            raise ValueError("strategy_parameters 必须是键值表")
        self._strategy.validate_parameters(
            strategy_parameters,
            profile_id=str(parameters["profile_id"]),
        )
        interval = int(parameters.get("rebalance_interval_days", 20))
        if interval <= 0:
            raise ValueError("最短再平衡交易日必须大于 0")
        if parameters.get("valuation_timing") != "point_in_time":
            raise ValueError("股息率回测必须使用 point_in_time 时点口径")
        if parameters.get("missing_valuation_policy") != "reject":
            raise ValueError("股息率回测缺失估值时必须拒绝运行")
        if (
            parameters.get("fundamental_guard_mode")
            != "index_methodology_proxy"
        ):
            raise ValueError("当前只支持指数编制规则基本面代理")
        minimum = int(
            strategy_parameters.get("minimum_history_observations", 726)
        )
        if self._history_observations < minimum:
            raise ValueError(
                "估值来源窗口不足："
                f"{self._history_observations} < {minimum}"
            )

    def generate_signal(
        self,
        instrument: Instrument,
        history: Sequence[DailyBar],
        parameters: dict[str, Any],
    ) -> BacktestSignal:
        del instrument
        self.validate_parameters(parameters)
        if len(history) < self.minimum_bars:
            raise ValueError(
                f"动态股息率回测至少需要 {self.minimum_bars} 根价格日线"
            )
        interval = int(parameters.get("rebalance_interval_days", 20))
        elapsed = len(history) - self.minimum_bars
        days_since_rebalance = elapsed % interval
        decision_history = history[
            : len(history) - days_since_rebalance
        ]
        decision_bar = decision_history[-1]
        valuation = self._valuations.get(decision_bar.trading_date)
        if valuation is None:
            raise ValueError(
                f"{decision_bar.trading_date} 缺少同日股息率估值"
            )
        price_window = decision_history[-self.minimum_bars :]
        peak = max(item.close for item in price_window)
        drawdown = decision_bar.close / peak - 1
        profile_id = str(parameters["profile_id"])
        strategy_parameters = parameters["strategy_parameters"]
        decision = self._strategy.decide(
            {
                "valuation": {
                    "dividend_yield": valuation.value,
                    "dividend_yield_percentile": valuation.percentile,
                    "history_observations": self._history_observations,
                    "stale": False,
                },
                "drawdowns": {"from_high_242d": drawdown},
                "fundamental_guard": {
                    "status": "pass",
                    "source": "index_methodology_proxy",
                },
            },
            profile_id=profile_id,
            parameters=strategy_parameters,
        )
        if decision.target_weight is None:
            raise ValueError(
                f"{decision_bar.trading_date} 的策略判断被阻断："
                + "；".join(decision.reasons)
            )
        return BacktestSignal(
            trading_date=history[-1].trading_date,
            target_weight=decision.target_weight,
            reason=(
                f"估值日 {decision_bar.trading_date}，"
                f"股息率 {valuation.value:.2%}，"
                f"历史分位 {valuation.percentile:.2%}，"
                f"242日回撤 {drawdown:.2%}，"
                f"{decision.band}，目标仓位 {decision.target_weight:.0%}"
            ),
        )
