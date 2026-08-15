"""行情准备用例：采集、计算、策略评估与数据落盘。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from ..config import Settings
from ..domain.metrics import calculate_metrics
from ..domain.models import MarketBundle
from ..domain.strategies import StrategyRegistry
from .ports import (
    MarketDataProvider,
    MarketHistoryRepository,
    ResearchRepository,
)


class MonitoringService:
    """可被 CLI、定时任务和未来远程命令入口共同调用的应用服务。"""

    def __init__(
        self,
        settings: Settings,
        market_data: MarketDataProvider,
        history_repository: MarketHistoryRepository,
        repository: ResearchRepository,
        strategies: StrategyRegistry,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._market_data = market_data
        self._history_repository = history_repository
        self._repository = repository
        self._strategies = strategies
        self._clock = clock or self._system_now

    def _system_now(self) -> datetime:
        return datetime.now(ZoneInfo(self._settings.timezone)).replace(microsecond=0)

    @staticmethod
    def _repair_intraday_amount(
        bundle: MarketBundle, now: datetime
    ) -> MarketBundle:
        bars = list(bundle.bars)
        if (
            bars
            and bars[-1].trading_date == now.date()
            and bars[-1].amount == 0
            and bundle.quote.amount
        ):
            bars[-1] = replace(bars[-1], amount=bundle.quote.amount)
        return MarketBundle(
            quote=bundle.quote,
            bars=tuple(bars),
            source=bundle.source,
        )

    def prepare(self, symbol: str) -> tuple[Path, dict[str, Any]]:
        instrument = self._settings.instrument_for(symbol)
        now = self._clock().replace(microsecond=0)
        bundle = self._market_data.fetch(
            instrument,
            instrument.history_days,
        )
        bundle = self._repair_intraday_amount(bundle, now)
        self._history_repository.save_bundle(instrument, bundle, now)
        metrics = calculate_metrics(bundle.bars)
        assessments = []
        for profile_id in instrument.strategy_profile_ids:
            profile = self._settings.strategy_profiles[profile_id]
            assessments.append(
                self._strategies.get(profile.strategy_id).evaluate(
                    instrument,
                    metrics,
                    profile_id=profile.profile_id,
                    parameters=profile.parameters,
                )
            )
        research_plan = self._settings.research_plan_for(symbol)
        notification_policy = self._settings.notification_policy_for(symbol)
        portfolio = self._settings.portfolio_for(symbol)

        packet: dict[str, Any] = {
            "schema_version": 3,
            "as_of": now.isoformat(),
            "instrument": instrument.to_packet(),
            "quote": bundle.quote.to_packet(),
            "metrics": metrics,
            "assessments": [item.to_packet() for item in assessments],
            "research_plan": research_plan.to_packet(),
            "notification_plan": notification_policy.to_packet(),
            "portfolio": {
                "enabled": portfolio.enabled,
                "shares": portfolio.shares,
                "average_cost": portfolio.average_cost,
                "planned_total_amount": portfolio.planned_total_amount,
            },
            "data_quality": {
                "market_source": bundle.source,
                "market_timestamp": bundle.quote.quote_time,
                "history_bars": len(bundle.bars),
                "quote_available": bundle.quote.price is not None,
                "limitations": [
                    "盘中行情快照不等同于最终收盘价",
                    "低频基本面与外部事件需要研究代理补充",
                    "公开数据源可能延迟或暂时不可用",
                ],
            },
        }
        latest_path = self._repository.save_packet(symbol, packet)
        section_text = "、".join(research_plan.sections)
        prompt = (
            f"请使用 {research_plan.skill} Skill 分析"
            f"{instrument.name}（{symbol}）。"
            f"数据包位于 {latest_path.relative_to(self._settings.root)}。"
            f"严格按 research_plan 执行，报告至少覆盖：{section_text}。"
        )
        self._repository.save_prompt(symbol, prompt)
        return latest_path, packet
