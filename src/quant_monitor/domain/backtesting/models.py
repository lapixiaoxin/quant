"""与具体存储和执行框架无关的回测领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BacktestSpecification:
    """一次可复现回测的冻结输入。"""

    symbol: str
    model_id: str
    model_version: str
    parameters_fingerprint: str
    start_date: date
    end_date: date
    initial_cash: float = 1_000_000.0
    commission_bps: float = 3.0
    slippage_bps: float = 2.0
    benchmark_symbol: str = ""

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("回测开始日期不能晚于结束日期")
        if self.initial_cash <= 0:
            raise ValueError("回测初始资金必须大于 0")
        if self.commission_bps < 0 or self.slippage_bps < 0:
            raise ValueError("回测费率和滑点不能为负数")
        if (
            not self.model_id
            or not self.model_version
            or not self.parameters_fingerprint
        ):
            raise ValueError("回测必须冻结模型标识、版本和参数指纹")


@dataclass(frozen=True)
class BacktestSignal:
    """长线只做多模型在某个交易日的目标仓位。"""

    trading_date: date
    target_weight: float
    reason: str

    def __post_init__(self) -> None:
        if not 0 <= self.target_weight <= 1:
            raise ValueError("目标仓位必须在 0 到 1 之间")
        if not self.reason.strip():
            raise ValueError("回测信号必须说明原因")


@dataclass(frozen=True)
class EquityPoint:
    """回测权益曲线的单日状态。"""

    trading_date: date
    equity: float
    cash: float
    position_value: float
    target_weight: float


@dataclass(frozen=True)
class BacktestMetrics:
    """回测结果的确定性汇总指标。"""

    total_return: float
    annualized_return: float | None
    max_drawdown: float
    annualized_volatility: float | None
    sharpe_ratio: float | None
    turnover: float
    trade_count: int
    benchmark_return: float | None = None
    excess_return: float | None = None


@dataclass(frozen=True)
class BacktestResult:
    """冻结输入、结果和限制说明组成的回测产物。"""

    specification: BacktestSpecification
    metrics: BacktestMetrics
    equity_curve: tuple[EquityPoint, ...]
    warnings: tuple[str, ...] = ()
