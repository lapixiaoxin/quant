"""分析策略的领域契约与结构化输出。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..models import Instrument


@dataclass(frozen=True)
class StrategyAssessment:
    """策略对当前环境的结构化判断，不代表交易指令。"""

    profile_id: str
    strategy_id: str
    strategy_name: str
    level: str
    score: int
    reasons: tuple[str, ...]

    def to_packet(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "id": self.strategy_id,
            "name": self.strategy_name,
            "level": self.level,
            "score": self.score,
            "reasons": list(self.reasons),
        }


class AnalysisStrategy(Protocol):
    """所有当前分析策略必须实现的最小契约。"""

    strategy_id: str
    name: str

    def validate_parameters(
        self,
        parameters: dict[str, Any],
        *,
        profile_id: str,
    ) -> None:
        """在执行前校验策略画像参数。"""

    def evaluate(
        self,
        instrument: Instrument,
        metrics: dict[str, Any],
        *,
        profile_id: str,
        parameters: dict[str, Any],
    ) -> StrategyAssessment:
        """使用确定性指标评估环境。"""
