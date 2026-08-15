"""策略回测的领域契约；当前不包含撮合和参数优化实现。"""

from .models import (
    BacktestMetrics,
    BacktestResult,
    BacktestSignal,
    BacktestSpecification,
    EquityPoint,
)
from .protocols import BacktestSignalModel

__all__ = [
    "BacktestMetrics",
    "BacktestResult",
    "BacktestSignal",
    "BacktestSignalModel",
    "BacktestSpecification",
    "EquityPoint",
]
