"""候选标的筛选的纯领域模型与确定性比较规则。"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from .metrics import calculate_metrics
from .models import InstrumentType, MarketBundle


@dataclass(frozen=True)
class CandidateMetadata:
    """候选标的需要由官方或权威来源核验的低频事实。

    total_fee_pct 仅合计管理费、托管费和销售服务费，不包含交易成本及其他
    运作费用。
    """

    tracking_index: str = ""
    tracking_index_code: str = ""
    management_fee_pct: float | None = None
    custody_fee_pct: float | None = None
    service_fee_pct: float | None = None
    fund_size_cny: float | None = None
    average_amount_20d_cny: float | None = None
    tracking_error_pct: float | None = None
    tracking_error_as_of: date | None = None
    inception_date: date | None = None
    as_of: date | None = None
    source_urls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        numeric_values = {
            "management_fee_pct": self.management_fee_pct,
            "custody_fee_pct": self.custody_fee_pct,
            "service_fee_pct": self.service_fee_pct,
            "fund_size_cny": self.fund_size_cny,
            "average_amount_20d_cny": self.average_amount_20d_cny,
            "tracking_error_pct": self.tracking_error_pct,
        }
        if any(value is not None and value < 0 for value in numeric_values.values()):
            raise ValueError("候选元数据数值不能为负数")
        has_low_frequency_facts = any(
            value is not None for value in numeric_values.values()
        )
        if has_low_frequency_facts and self.as_of is None:
            raise ValueError("候选低频事实必须提供 metadata_as_of")
        if self.tracking_error_pct is not None and self.tracking_error_as_of is None:
            raise ValueError("跟踪误差必须提供独立的 tracking_error_as_of")
        if (
            has_low_frequency_facts
            or self.tracking_index
            or self.tracking_index_code
        ) and not self.source_urls:
            raise ValueError("候选元数据必须提供至少一个来源 URL")
        if any(
            not url.startswith(("https://", "http://"))
            for url in self.source_urls
        ):
            raise ValueError("候选来源必须是完整的 HTTP(S) URL")

    @property
    def total_fee_pct(self) -> float | None:
        if self.management_fee_pct is None or self.custody_fee_pct is None:
            return None
        return (
            self.management_fee_pct
            + self.custody_fee_pct
            + (self.service_fee_pct or 0.0)
        )

    def value_for(self, field: str) -> object:
        if field == "total_fee_pct":
            return self.total_fee_pct
        if not hasattr(self, field):
            raise ValueError(f"未知候选元数据字段：{field}")
        return getattr(self, field)

    def to_packet(self) -> dict[str, Any]:
        return {
            "tracking_index": self.tracking_index,
            "tracking_index_code": self.tracking_index_code,
            "management_fee_pct": self.management_fee_pct,
            "custody_fee_pct": self.custody_fee_pct,
            "service_fee_pct": self.service_fee_pct,
            "total_fee_pct": self.total_fee_pct,
            "fund_size_cny": self.fund_size_cny,
            "average_amount_20d_cny": self.average_amount_20d_cny,
            "tracking_error_pct": self.tracking_error_pct,
            "tracking_error_as_of": (
                self.tracking_error_as_of.isoformat()
                if self.tracking_error_as_of
                else None
            ),
            "inception_date": (
                self.inception_date.isoformat() if self.inception_date else None
            ),
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "source_urls": list(self.source_urls),
        }


@dataclass(frozen=True)
class SelectionCandidate:
    """候选池中的一个标的，不要求先进入正式监控配置。"""

    symbol: str
    name: str
    exchange: str
    instrument_type: InstrumentType
    metadata: CandidateMetadata = CandidateMetadata()

    def to_packet(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "type": self.instrument_type.value,
            "metadata": self.metadata.to_packet(),
        }


@dataclass(frozen=True)
class SelectionRules:
    """候选筛选的硬门槛和证据完整性要求。"""

    min_history_bars: int = 120
    min_average_amount_cny: float = 10_000_000
    min_fund_size_cny: float | None = None
    max_total_fee_pct: float | None = None
    required_metadata: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.min_history_bars < 20:
            raise ValueError("候选筛选最少历史条数不能小于 20")
        if self.min_average_amount_cny < 0:
            raise ValueError("最低日均成交额不能为负数")
        if self.min_fund_size_cny is not None and self.min_fund_size_cny < 0:
            raise ValueError("最低基金规模不能为负数")
        if self.max_total_fee_pct is not None and self.max_total_fee_pct < 0:
            raise ValueError("最高显性持续费率不能为负数")

    def to_packet(self) -> dict[str, Any]:
        return {
            "min_history_bars": self.min_history_bars,
            "min_average_amount_cny": self.min_average_amount_cny,
            "min_fund_size_cny": self.min_fund_size_cny,
            "max_total_fee_pct": self.max_total_fee_pct,
            "required_metadata": list(self.required_metadata),
        }


@dataclass(frozen=True)
class SelectionUniverse:
    """围绕同一投资目标组织的候选池。"""

    universe_id: str
    name: str
    objective: str
    instrument_type: InstrumentType
    history_days: int
    shortlist_size: int
    rules: SelectionRules
    candidates: tuple[SelectionCandidate, ...]

    def __post_init__(self) -> None:
        if not self.universe_id or not self.name or not self.objective:
            raise ValueError("候选池必须提供 ID、名称和投资目标")
        if self.history_days < self.rules.min_history_bars:
            raise ValueError("候选池历史窗口不能小于硬门槛所需条数")
        if self.shortlist_size <= 0:
            raise ValueError("候选池短名单数量必须大于 0")
        if len(self.candidates) < 2:
            raise ValueError("候选池至少需要两个标的")
        symbols = [item.symbol for item in self.candidates]
        if len(symbols) != len(set(symbols)):
            raise ValueError("候选池不能包含重复标的代码")
        if any(
            item.instrument_type is not self.instrument_type
            for item in self.candidates
        ):
            raise ValueError("候选标的类型必须与候选池类型一致")

    def to_packet(self) -> dict[str, Any]:
        return {
            "id": self.universe_id,
            "name": self.name,
            "objective": self.objective,
            "instrument_type": self.instrument_type.value,
            "history_days": self.history_days,
            "shortlist_size": self.shortlist_size,
            "rules": self.rules.to_packet(),
        }


@dataclass(frozen=True)
class CandidateEvaluation:
    """候选的确定性市场指标、门槛结论与证据缺口。"""

    candidate: SelectionCandidate
    status: str
    metrics: dict[str, Any]
    exclusions: tuple[str, ...] = ()
    evidence_gaps: tuple[str, ...] = ()
    market_score: float | None = None
    market_rank: int | None = None
    error: str = ""

    def to_packet(self) -> dict[str, Any]:
        return {
            **self.candidate.to_packet(),
            "status": self.status,
            "metrics": self.metrics,
            "exclusions": list(self.exclusions),
            "evidence_gaps": list(self.evidence_gaps),
            "market_score": self.market_score,
            "market_rank": self.market_rank,
            "error": self.error or None,
        }


def _is_missing(value: object) -> bool:
    return value is None or value == "" or value == ()


def evaluate_candidate(
    candidate: SelectionCandidate,
    bundle: MarketBundle,
    rules: SelectionRules,
) -> CandidateEvaluation:
    """使用统一日线和已核验元数据执行硬过滤，不输出买卖建议。"""

    metrics = calculate_metrics(bundle.bars)
    exclusions: list[str] = []
    if len(bundle.bars) < rules.min_history_bars:
        exclusions.append(
            f"历史数据不足：{len(bundle.bars)} < {rules.min_history_bars}"
        )
    calculated_average_amount = metrics["liquidity"]["amount_ma20"]
    average_amount = (
        calculated_average_amount
        if calculated_average_amount is not None
        else candidate.metadata.average_amount_20d_cny
    )
    extra_gaps: list[str] = []
    if average_amount is None:
        extra_gaps.append("average_amount_20d_cny")
    elif average_amount < rules.min_average_amount_cny:
        exclusions.append(
            "近20日日均成交额低于门槛："
            f"{average_amount:.0f} < {rules.min_average_amount_cny:.0f}"
        )
    metadata = candidate.metadata
    if (
        rules.min_fund_size_cny is not None
        and metadata.fund_size_cny is not None
        and metadata.fund_size_cny < rules.min_fund_size_cny
    ):
        exclusions.append(
            "基金规模低于门槛："
            f"{metadata.fund_size_cny:.0f} < {rules.min_fund_size_cny:.0f}"
        )
    total_fee = metadata.total_fee_pct
    if (
        rules.max_total_fee_pct is not None
        and total_fee is not None
        and total_fee > rules.max_total_fee_pct
    ):
        exclusions.append(
            f"显性持续费率高于门槛：{total_fee:.4f}%"
            f" > {rules.max_total_fee_pct:.4f}%"
        )
    gaps = tuple(
        dict.fromkeys(
            [
                *extra_gaps,
                *[
                    field
                    for field in rules.required_metadata
                    if _is_missing(metadata.value_for(field))
                ],
            ]
        )
    )
    status = "excluded" if exclusions else ("needs_research" if gaps else "eligible")
    market_metrics = {
        "market_source": bundle.source,
        "history_bars": len(bundle.bars),
        "latest_trading_date": metrics["latest_trading_date"],
        "latest_close": metrics["latest_close"],
        "return_242d": metrics["returns"]["242d"],
        "annualized_volatility_20d": metrics["risk"][
            "annualized_volatility_20d"
        ],
        "max_drawdown_242d": metrics["max_drawdowns"]["242d"],
        "drawdown_from_high_60d": metrics["drawdowns"]["from_high_60d"],
        "average_amount_20d": average_amount,
        "average_amount_20d_source": (
            "market_history"
            if calculated_average_amount is not None
            else ("verified_metadata" if average_amount is not None else None)
        ),
        "average_volume_20d": metrics["liquidity"]["volume_ma20"],
        "trend_state": metrics["trend_state"],
    }
    return CandidateEvaluation(
        candidate=candidate,
        status=status,
        metrics=market_metrics,
        exclusions=tuple(exclusions),
        evidence_gaps=gaps,
    )


def failed_candidate(
    candidate: SelectionCandidate,
    error: Exception,
) -> CandidateEvaluation:
    """把单个候选的数据失败显式保留在比较结果中。"""

    return CandidateEvaluation(
        candidate=candidate,
        status="data_error",
        metrics={},
        exclusions=("行情采集或指标计算失败",),
        error=str(error),
    )


def _normalized(values: list[float], value: float, *, higher_better: bool) -> float:
    low = min(values)
    high = max(values)
    if math.isclose(low, high):
        return 1.0
    score = (value - low) / (high - low)
    return score if higher_better else 1.0 - score


def rank_market_evaluations(
    evaluations: tuple[CandidateEvaluation, ...],
) -> tuple[CandidateEvaluation, ...]:
    """只对可用市场指标排名；该排名不能替代费用和跟踪质量研究。"""

    comparable = [
        item
        for item in evaluations
        if item.status != "data_error"
        and item.metrics.get("average_amount_20d") is not None
        and item.metrics.get("annualized_volatility_20d") is not None
        and item.metrics.get("max_drawdown_242d") is not None
    ]
    if not comparable:
        return evaluations
    amounts = [float(item.metrics["average_amount_20d"]) for item in comparable]
    volatilities = [
        float(item.metrics["annualized_volatility_20d"]) for item in comparable
    ]
    drawdowns = [
        abs(float(item.metrics["max_drawdown_242d"])) for item in comparable
    ]
    scored: list[CandidateEvaluation] = []
    for item in comparable:
        score = 100 * (
            0.50
            * _normalized(
                amounts,
                float(item.metrics["average_amount_20d"]),
                higher_better=True,
            )
            + 0.25
            * _normalized(
                volatilities,
                float(item.metrics["annualized_volatility_20d"]),
                higher_better=False,
            )
            + 0.25
            * _normalized(
                drawdowns,
                abs(float(item.metrics["max_drawdown_242d"])),
                higher_better=False,
            )
        )
        scored.append(replace(item, market_score=round(score, 2)))
    ordered = sorted(
        scored,
        key=lambda item: (
            item.status == "excluded",
            -(item.market_score or 0),
            item.candidate.symbol,
        ),
    )
    ranked = {
        item.candidate.symbol: replace(item, market_rank=index)
        for index, item in enumerate(ordered, start=1)
    }
    return tuple(
        ranked.get(item.candidate.symbol, item)
        for item in evaluations
    )
