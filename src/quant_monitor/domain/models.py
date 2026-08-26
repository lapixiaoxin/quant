"""不依赖外部系统的核心领域模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


class InstrumentType(str, Enum):
    """当前支持的投资标的类别。"""

    ETF = "etf"
    STOCK = "stock"
    INDEX = "index"

    @classmethod
    def parse(cls, value: str) -> InstrumentType:
        try:
            return cls(value.lower())
        except ValueError as error:
            supported = "、".join(item.value for item in cls)
            message = f"不支持的标的类型 {value!r}，可选值：{supported}"
            raise ValueError(message) from error


@dataclass(frozen=True)
class Instrument:
    """经过类别默认值和单标的覆盖解析后的投资标的。"""

    symbol: str
    name: str
    exchange: str
    instrument_type: InstrumentType
    strategy_profile_ids: tuple[str, ...]
    research_profile_id: str
    notification_policy_id: str
    history_days: int
    history_start_date: date | None = None
    enabled: bool = True
    research_focus: tuple[str, ...] = ()
    research_instructions: tuple[str, ...] = ()
    tracking_index: str = ""
    tracking_index_code: str = ""

    @property
    def secid(self) -> str:
        market = "1" if self.exchange.upper() == "SH" else "0"
        return f"{market}.{self.symbol}"

    def to_packet(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "type": self.instrument_type.value,
            "strategy_profiles": list(self.strategy_profile_ids),
            "research_profile": self.research_profile_id,
            "notification_policy": self.notification_policy_id,
            "history_days": self.history_days,
            "enabled": self.enabled,
            "research_focus": list(self.research_focus),
            "research_instructions": list(self.research_instructions),
            "tracking_index": self.tracking_index,
            "tracking_index_code": self.tracking_index_code,
        }


@dataclass(frozen=True)
class DailyBar:
    """统一后的日线行情。百分比字段使用百分数，例如 2.5 表示 2.5%。"""

    trading_date: date
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    amplitude_pct: float
    change_pct: float
    turnover_pct: float


@dataclass(frozen=True)
class ValuationObservation:
    """某个指数在指定交易日可见的估值与历史分位。"""

    valuation_symbol: str
    observation_date: date
    metric: str
    weighting: str
    history_window: str
    value: float
    percentile: float
    percentile_20_value: float
    percentile_50_value: float
    percentile_80_value: float
    source: str
    source_url: str


@dataclass(frozen=True)
class MarketQuote:
    """统一后的实时或延迟行情快照。比例字段使用小数，例如 0.025 表示 2.5%。"""

    symbol: str
    name: str
    price: float | None
    high: float | None
    low: float | None
    open: float | None
    previous_close: float | None
    volume: float
    amount: float
    total_market_value: float
    circulating_market_value: float
    change_pct: float | None
    amplitude_pct: float | None
    price_precision: int
    quote_time: str | None = None

    def to_packet(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketBundle:
    """一次行情采集得到的快照、历史数据及来源信息。"""

    quote: MarketQuote
    bars: tuple[DailyBar, ...]
    source: str


@dataclass(frozen=True)
class HistorySummary:
    """本地历史行情库中一个标的的覆盖情况。"""

    symbol: str
    bar_count: int
    first_date: date | None
    last_date: date | None
    last_source: str | None
    updated_at: datetime | None
