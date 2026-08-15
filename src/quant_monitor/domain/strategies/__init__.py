"""可注册的产品与标的分析策略。"""

from .base import AnalysisStrategy, StrategyAssessment
from .etf import DividendLowVolStrategy
from .registry import StrategyRegistry

__all__ = [
    "AnalysisStrategy",
    "DividendLowVolStrategy",
    "StrategyAssessment",
    "StrategyRegistry",
]
