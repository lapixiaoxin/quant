"""研究平台控制面的纯领域模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


class InvestmentHorizon(str, Enum):
    """标的选择或策略关注的时间跨度。"""

    SHORT = "short"
    LONG = "long"

    @classmethod
    def parse(cls, value: str) -> InvestmentHorizon:
        try:
            return cls(value.strip().lower())
        except ValueError as error:
            raise ValueError("投资期限仅支持 short 或 long") from error


class StrategyLifecycle(str, Enum):
    """策略版本生命周期。"""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class ValidationState(str, Enum):
    """策略版本的验证状态。"""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class AnalysisCycle(str, Enum):
    """一次分析任务要求覆盖的时间或技术维度。"""

    DAILY = "daily"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    MOVING_AVERAGE = "moving_average"

    @classmethod
    def parse(cls, value: str) -> AnalysisCycle:
        normalized = value.strip().lower()
        aliases = {
            "day": cls.DAILY,
            "month": cls.MONTHLY,
            "year": cls.YEARLY,
            "ma": cls.MOVING_AVERAGE,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return cls(normalized)
        except ValueError as error:
            supported = "、".join(item.value for item in cls)
            raise ValueError(f"不支持的分析周期 {value!r}：{supported}") from error


class AnalysisTrigger(str, Enum):
    """分析任务的触发入口。"""

    MANUAL = "manual"
    SCHEDULED = "scheduled"
    REMOTE = "remote"


@dataclass(frozen=True)
class StrategyRecord:
    """一个可审计、可启停的策略版本。"""

    record_id: str
    profile_id: str
    version: str
    name: str
    symbols: tuple[str, ...]
    horizon: InvestmentHorizon
    lifecycle: StrategyLifecycle
    validation_state: ValidationState
    created_at: datetime
    enabled_at: datetime | None
    retired_at: datetime | None
    thesis: str
    parameters_fingerprint: str
    backtest_model_id: str
    backtest_model_version: str
    backtest_parameters: dict[str, Any]

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.record_id,
                self.profile_id,
                self.version,
                self.name,
                self.thesis,
                self.parameters_fingerprint,
            )
        ):
            raise ValueError("策略记录缺少标识、版本、名称、论点或参数指纹")
        if not self.symbols:
            raise ValueError(f"策略记录 {self.record_id} 至少绑定一个标的")
        if self.lifecycle is StrategyLifecycle.ACTIVE:
            if self.enabled_at is None or self.retired_at is not None:
                raise ValueError("启用策略必须有启用时间且不能有弃用时间")
        elif self.lifecycle is StrategyLifecycle.RETIRED:
            if self.enabled_at is None or self.retired_at is None:
                raise ValueError("弃用策略必须同时提供启用和弃用时间")
            if self.retired_at < self.enabled_at:
                raise ValueError("策略弃用时间不能早于启用时间")
        elif self.enabled_at is not None or self.retired_at is not None:
            raise ValueError("草稿策略不能设置启用或弃用时间")
        if bool(self.backtest_model_id) != bool(self.backtest_model_version):
            raise ValueError("回测模型标识和版本必须同时提供")

    def applies_to(self, symbol: str) -> bool:
        return symbol in self.symbols

    def to_packet(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "profile_id": self.profile_id,
            "version": self.version,
            "name": self.name,
            "symbols": list(self.symbols),
            "horizon": self.horizon.value,
            "lifecycle": self.lifecycle.value,
            "validation_state": self.validation_state.value,
            "created_at": self.created_at.isoformat(),
            "enabled_at": self.enabled_at.isoformat() if self.enabled_at else None,
            "retired_at": self.retired_at.isoformat() if self.retired_at else None,
            "thesis": self.thesis,
            "parameters_fingerprint": self.parameters_fingerprint,
            "backtest_model_id": self.backtest_model_id or None,
            "backtest_model_version": self.backtest_model_version or None,
            "backtest_parameters": self.backtest_parameters,
        }


@dataclass(frozen=True)
class FactorDefinition:
    """报告中的一个因子能力及其数据边界。"""

    factor_id: str
    name: str
    source_kind: str
    availability: str
    description: str

    def to_packet(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AnalysisRequest:
    """指定标的范围、周期和因子的标准分析请求。"""

    request_id: str
    requested_at: datetime
    trigger: AnalysisTrigger
    mode: str
    symbols: tuple[str, ...]
    cycles: tuple[AnalysisCycle, ...]
    factor_ids: tuple[str, ...]
    send: bool

    def __post_init__(self) -> None:
        if not self.request_id or not self.symbols:
            raise ValueError("分析请求必须有 ID 和至少一个标的")
        if not self.cycles:
            raise ValueError("分析请求至少需要一个分析周期")
        if not self.factor_ids:
            raise ValueError("分析请求至少需要一个分析因子")
        if self.mode not in {"base", "traecli"}:
            raise ValueError("分析模式仅支持 base 或 traecli")

    def for_symbol(self, symbol: str) -> dict[str, Any]:
        if symbol not in self.symbols:
            raise ValueError(f"分析请求 {self.request_id} 不包含标的 {symbol}")
        return {
            "request_id": self.request_id,
            "requested_at": self.requested_at.isoformat(),
            "trigger": self.trigger.value,
            "mode": self.mode,
            "symbol": symbol,
            "cycles": [item.value for item in self.cycles],
            "factor_ids": list(self.factor_ids),
            "send": self.send,
        }

    def to_packet(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "requested_at": self.requested_at.isoformat(),
            "trigger": self.trigger.value,
            "mode": self.mode,
            "symbols": list(self.symbols),
            "cycles": [item.value for item in self.cycles],
            "factor_ids": list(self.factor_ids),
            "send": self.send,
        }

    @classmethod
    def from_packet(cls, values: dict[str, Any]) -> AnalysisRequest:
        return cls(
            request_id=str(values["request_id"]),
            requested_at=datetime.fromisoformat(
                str(values["requested_at"])
            ),
            trigger=AnalysisTrigger(str(values["trigger"])),
            mode=str(values["mode"]),
            symbols=tuple(str(item) for item in values["symbols"]),
            cycles=tuple(
                AnalysisCycle.parse(str(item))
                for item in values["cycles"]
            ),
            factor_ids=tuple(
                str(item) for item in values["factor_ids"]
            ),
            send=bool(values["send"]),
        )


@dataclass(frozen=True)
class ReportRecord:
    """报告文件、策略、因子和发布结果的统一索引。"""

    report_id: str
    analysis_request_id: str
    symbol: str
    report_type: str
    title: str
    path: str
    generated_at: datetime
    strategy_record_ids: tuple[str, ...]
    cycles: tuple[str, ...]
    factor_ids: tuple[str, ...]
    channels: tuple[str, ...]
    delivery_status: str

    def to_packet(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "analysis_request_id": self.analysis_request_id,
            "symbol": self.symbol,
            "report_type": self.report_type,
            "title": self.title,
            "path": self.path,
            "generated_at": self.generated_at.isoformat(),
            "strategy_record_ids": list(self.strategy_record_ids),
            "cycles": list(self.cycles),
            "factor_ids": list(self.factor_ids),
            "channels": list(self.channels),
            "delivery_status": self.delivery_status,
        }


@dataclass(frozen=True)
class SelectionRunRecord:
    """候选池筛选的一次运行索引。"""

    run_id: str
    universe_id: str
    horizon: InvestmentHorizon
    theme: str
    requested_at: datetime
    status: str
    candidate_count: int
    shortlist_count: int
    packet_path: str
    report_path: str


@dataclass(frozen=True)
class BacktestRunRecord:
    """回测任务的索引及其可见状态。"""

    run_id: str
    strategy_record_id: str
    symbol: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    result_path: str
    total_return: float | None = None
    max_drawdown: float | None = None
    trade_count: int | None = None
    error: str = ""


def parse_optional_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def parse_optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
