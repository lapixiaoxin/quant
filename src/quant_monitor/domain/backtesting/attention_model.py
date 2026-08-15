"""把当前确定性关注度策略显式转换为仅供回测的目标仓位。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..metrics import calculate_metrics
from ..models import DailyBar, Instrument
from ..strategies.base import AnalysisStrategy
from .models import BacktestSignal


class AttentionScoreAllocationModel:
    """以明确阈值映射关注度分数，不改变线上分析策略语义。"""

    model_id = "attention_score_allocation"
    model_version = "1.0.0"
    minimum_bars = 120

    def __init__(self, strategy: AnalysisStrategy) -> None:
        self._strategy = strategy

    def validate_parameters(self, parameters: dict[str, Any]) -> None:
        full_score = int(parameters.get("full_score", 68))
        watch_score = int(parameters.get("watch_score", 52))
        full_weight = float(parameters.get("full_weight", 1.0))
        watch_weight = float(parameters.get("watch_weight", 0.5))
        if not 0 <= watch_score <= full_score <= 100:
            raise ValueError("回测关注度阈值必须满足 0 <= watch <= full <= 100")
        if not 0 <= watch_weight <= full_weight <= 1:
            raise ValueError("回测目标仓位必须满足 0 <= watch <= full <= 1")

    def generate_signal(
        self,
        instrument: Instrument,
        history: Sequence[DailyBar],
        parameters: dict[str, Any],
    ) -> BacktestSignal:
        self.validate_parameters(parameters)
        if len(history) < self.minimum_bars:
            raise ValueError(
                f"关注度回测至少需要 {self.minimum_bars} 根历史日线"
            )
        profile_id = str(parameters["profile_id"])
        strategy_parameters = parameters.get("strategy_parameters", {})
        if not isinstance(strategy_parameters, dict):
            raise ValueError("strategy_parameters 必须是键值表")
        assessment = self._strategy.evaluate(
            instrument,
            calculate_metrics(history),
            profile_id=profile_id,
            parameters=strategy_parameters,
        )
        full_score = int(parameters.get("full_score", 68))
        watch_score = int(parameters.get("watch_score", 52))
        if assessment.score >= full_score:
            target = float(parameters.get("full_weight", 1.0))
        elif assessment.score >= watch_score:
            target = float(parameters.get("watch_weight", 0.5))
        else:
            target = 0.0
        return BacktestSignal(
            trading_date=history[-1].trading_date,
            target_weight=target,
            reason=(
                f"关注度 {assessment.score}，"
                f"状态 {assessment.level}，映射目标仓位 {target:.0%}"
            ),
        )
