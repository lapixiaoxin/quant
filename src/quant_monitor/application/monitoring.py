"""行情准备用例：采集、计算、策略评估与数据落盘。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from ..config import Settings
from ..domain.control_plane import AnalysisRequest
from ..domain.metrics import calculate_metrics
from ..domain.models import MarketBundle
from ..domain.strategies import StrategyRegistry
from ..infrastructure.strategy_catalog import (
    StrategyCatalog,
    strategy_profile_fingerprint,
)
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
        strategy_catalog: StrategyCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._market_data = market_data
        self._history_repository = history_repository
        self._repository = repository
        self._strategies = strategies
        self._strategy_catalog = strategy_catalog
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

    def _fetch_limit(self, symbol: str, history_days: int, now: datetime) -> int:
        summary = self._history_repository.summarize(symbol)
        if (
            summary.bar_count < history_days
            or summary.last_date is None
            or (now.date() - summary.last_date).days > 12
        ):
            return history_days
        return min(history_days, 40)

    def _repaired_dates(
        self,
        symbol: str,
        bundle: MarketBundle,
    ) -> tuple[date, ...]:
        """识别增量响应补回的近期历史缺口，不把正常新增交易日算作修复。"""

        summary = self._history_repository.summarize(symbol)
        if summary.last_date is None or not bundle.bars:
            return ()
        first_incoming = bundle.bars[0].trading_date
        existing_dates = {
            item.trading_date
            for item in self._history_repository.load_bars(
                symbol,
                start_date=first_incoming,
                end_date=summary.last_date,
            )
        }
        return tuple(
            item.trading_date
            for item in bundle.bars
            if item.trading_date <= summary.last_date
            and item.trading_date not in existing_dates
        )

    def _strategy_plan(self, symbol: str) -> list[dict[str, Any]]:
        instrument = self._settings.instrument_for(symbol)
        if self._strategy_catalog is not None:
            self._strategy_catalog.validate_instrument(
                self._settings,
                symbol,
            )
            return [
                item.to_packet()
                for item in self._strategy_catalog.active_for(
                    symbol,
                    instrument.strategy_profile_ids,
                )
            ]
        return [
            {
                "record_id": f"unmanaged:{profile_id}",
                "profile_id": profile_id,
                "version": "unmanaged",
                "lifecycle": "unmanaged",
                "parameters_fingerprint": strategy_profile_fingerprint(
                    self._settings.strategy_profiles[profile_id]
                ),
            }
            for profile_id in instrument.strategy_profile_ids
        ]

    def prepare(
        self,
        symbol: str,
        analysis_request: AnalysisRequest | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        instrument = self._settings.instrument_for(symbol)
        now = self._clock().replace(microsecond=0)
        fetch_limit = self._fetch_limit(symbol, instrument.history_days, now)
        bundle = self._market_data.fetch(
            instrument,
            fetch_limit,
        )
        bundle = self._repair_intraday_amount(bundle, now)
        repaired_dates = self._repaired_dates(symbol, bundle)
        self._history_repository.save_bundle(instrument, bundle, now)
        stored_bars = self._history_repository.load_bars(
            symbol,
            limit=instrument.history_days,
        )
        bundle = MarketBundle(
            quote=bundle.quote,
            bars=stored_bars,
            source=bundle.source,
        )
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
            "schema_version": 4,
            "as_of": now.isoformat(),
            "instrument": instrument.to_packet(),
            "strategy_plan": self._strategy_plan(symbol),
            "analysis_plan": (
                analysis_request.for_symbol(symbol)
                if analysis_request
                else {
                    "request_id": None,
                    "trigger": "manual",
                    "mode": "base",
                    "symbol": symbol,
                    "cycles": ["daily", "moving_average"],
                    "factor_ids": [
                        "market_snapshot",
                        "moving_average",
                        "return_window",
                        "drawdown",
                        "volatility",
                        "liquidity",
                        "strategy",
                    ],
                    "send": False,
                }
            ),
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
                "sync_mode": (
                    "full" if fetch_limit == instrument.history_days else "incremental"
                ),
                "requested_bars": fetch_limit,
                "repaired_history_dates": [
                    item.isoformat() for item in repaired_dates
                ],
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
            f"严格按 strategy_plan、analysis_plan 和 research_plan 执行，"
            f"报告至少覆盖：{section_text}。"
        )
        self._repository.save_prompt(symbol, prompt)
        return latest_path, packet
