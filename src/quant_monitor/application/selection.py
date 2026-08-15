"""候选池准备应用服务：采集、硬过滤、市场排名与证据落盘。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from ..config import Settings
from ..domain.models import Instrument
from ..domain.selection import (
    SelectionUniverse,
    evaluate_candidate,
    failed_candidate,
    rank_market_evaluations,
)
from .ports import (
    MarketDataProvider,
    MarketHistoryRepository,
    ResearchRepository,
)


class SelectionService:
    """对未进入正式监控配置的候选标的执行可审计初筛。"""

    def __init__(
        self,
        settings: Settings,
        market_data: MarketDataProvider,
        history_repository: MarketHistoryRepository,
        repository: ResearchRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._market_data = market_data
        self._history_repository = history_repository
        self._repository = repository
        self._clock = clock or self._system_now

    def _system_now(self) -> datetime:
        return datetime.now(ZoneInfo(self._settings.timezone)).replace(microsecond=0)

    @staticmethod
    def _as_instrument(universe: SelectionUniverse, index: int) -> Instrument:
        candidate = universe.candidates[index]
        return Instrument(
            symbol=candidate.symbol,
            name=candidate.name,
            exchange=candidate.exchange,
            instrument_type=candidate.instrument_type,
            strategy_profile_ids=(),
            research_profile_id="",
            notification_policy_id="",
            history_days=universe.history_days,
            tracking_index=candidate.metadata.tracking_index,
            tracking_index_code=candidate.metadata.tracking_index_code,
        )

    def prepare(
        self,
        universe: SelectionUniverse,
    ) -> tuple[Path, dict[str, Any]]:
        now = self._clock().replace(microsecond=0)
        evaluations = []
        for index, candidate in enumerate(universe.candidates):
            instrument = self._as_instrument(universe, index)
            try:
                bundle = self._market_data.fetch(
                    instrument,
                    universe.history_days,
                )
                self._history_repository.save_bundle(instrument, bundle, now)
                evaluations.append(
                    evaluate_candidate(candidate, bundle, universe.rules)
                )
            except (OSError, RuntimeError, ValueError) as error:
                evaluations.append(failed_candidate(candidate, error))
        ranked = rank_market_evaluations(tuple(evaluations))
        status_counts = {
            status: sum(item.status == status for item in ranked)
            for status in ("eligible", "needs_research", "excluded", "data_error")
        }
        packet: dict[str, Any] = {
            "selection_schema_version": 1,
            "as_of": now.isoformat(),
            "universe": universe.to_packet(),
            "candidates": [item.to_packet() for item in ranked],
            "summary": {
                **status_counts,
                "candidate_count": len(ranked),
                "market_ranking_scope": (
                    "仅比较流动性、近期波动和一年最大回撤；"
                    "不代表最终适配性或买入顺序"
                ),
            },
            "data_quality": {
                "limitations": [
                    "低频费率、规模、跟踪误差和指数规则依赖来源日期",
                    "市场排名不包含申赎、券商佣金、税费和个人账户约束",
                    "缺失必需元数据的候选不能进入最终短名单",
                    "候选发现可能遗漏新成立、停牌或更名产品",
                ]
            },
        }
        path = self._repository.save_selection_packet(
            universe.universe_id,
            packet,
        )
        return path, packet
