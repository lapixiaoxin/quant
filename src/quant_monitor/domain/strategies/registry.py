"""分析策略注册表。"""

from __future__ import annotations

from .base import AnalysisStrategy
from .etf import DividendLowVolStrategy


class StrategyRegistry:
    """集中管理策略，新增策略无需修改应用编排。"""

    def __init__(self, strategies: tuple[AnalysisStrategy, ...]) -> None:
        self._strategies = {item.strategy_id: item for item in strategies}

    @classmethod
    def default(cls) -> StrategyRegistry:
        return cls((DividendLowVolStrategy(),))

    def get(self, strategy_id: str) -> AnalysisStrategy:
        try:
            return self._strategies[strategy_id]
        except KeyError as error:
            available = "、".join(sorted(self._strategies))
            raise ValueError(
                f"未注册策略 {strategy_id!r}，当前可用策略：{available}"
            ) from error

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies))
