"""行情准备用例：采集、计算、策略评估与数据落盘。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from ..config import Settings
from ..domain.control_plane import AnalysisRequest
from ..domain.metrics import calculate_metrics
from ..domain.models import HistorySummary, Instrument, MarketBundle
from ..domain.strategies import StrategyRegistry
from .ports import (
    MarketDataProvider,
    MarketHistoryRepository,
    ResearchRepository,
)
from .strategy_catalog import StrategyCatalog, strategy_profile_fingerprint


@dataclass(frozen=True)
class HistorySyncResult:
    """一次行情同步的可审计结果。"""

    bundle: MarketBundle
    summary: HistorySummary
    sync_mode: str
    requested_bars: int
    repaired_dates: tuple[date, ...]


class MonitoringService:
    """供 CLI 与任意研究 Agent 复用的行情工具。"""

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

    def _fetch_plan(
        self,
        instrument: Instrument,
        now: datetime,
    ) -> tuple[int, str]:
        summary = self._history_repository.summarize(instrument.symbol)
        if (
            instrument.history_start_date is not None
            and (
                summary.first_date is None
                or summary.first_date > instrument.history_start_date
            )
        ):
            return max(instrument.history_days, 1_000), "full"
        if (
            summary.bar_count < instrument.history_days
            or summary.last_date is None
            or (now.date() - summary.last_date).days > 12
        ):
            return instrument.history_days, "full"
        return min(instrument.history_days, 40), "incremental"

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

    def sync_history(self, symbol: str) -> HistorySyncResult:
        """同步一个标的的历史行情，不执行策略、报告或通知。"""

        instrument = self._settings.instrument_for(symbol)
        now = self._clock().replace(microsecond=0)
        fetch_limit, sync_mode = self._fetch_plan(instrument, now)
        bundle = self._market_data.fetch(instrument, fetch_limit)
        bundle = self._repair_intraday_amount(bundle, now)
        repaired_dates = self._repaired_dates(symbol, bundle)
        self._history_repository.save_bundle(instrument, bundle, now)
        summary = self._history_repository.summarize(symbol)
        if (
            instrument.history_start_date is not None
            and (
                summary.first_date is None
                or summary.first_date > instrument.history_start_date
            )
        ):
            actual = summary.first_date.isoformat() if summary.first_date else "无"
            raise ValueError(
                f"{symbol} 历史仍不完整：期望从 "
                f"{instrument.history_start_date.isoformat()} 开始，"
                f"实际首日为 {actual}"
            )
        return HistorySyncResult(
            bundle=bundle,
            summary=summary,
            sync_mode=sync_mode,
            requested_bars=fetch_limit,
            repaired_dates=repaired_dates,
        )

    def prepare(
        self,
        symbol: str,
        analysis_request: AnalysisRequest | None = None,
        *,
        evaluate_strategies: bool = False,
    ) -> tuple[Path, dict[str, Any]]:
        """采集与计算默认独立于策略；正式评估显式校验策略版本。"""
        instrument = self._settings.instrument_for(symbol)
        strategy_plan = self._strategy_plan(symbol) if evaluate_strategies else []
        now = self._clock().replace(microsecond=0)
        sync = self.sync_history(symbol)
        bundle = sync.bundle
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
        for profile_id in (
            instrument.strategy_profile_ids if evaluate_strategies else ()
        ):
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
        portfolio = self._settings.portfolio_for(symbol)
        identity = instrument.to_packet()
        identity.pop("notification_policy", None)

        packet: dict[str, Any] = {
            "schema_version": 5,
            "as_of": now.isoformat(),
            "instrument": identity,
            "strategy_plan": strategy_plan,
            "analysis_plan": (
                analysis_request.for_symbol(symbol)
                if analysis_request
                else {
                    "request_id": None,
                    "trigger": "manual",
                    "mode": "research",
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
                }
            ),
            "quote": bundle.quote.to_packet(),
            "metrics": metrics,
            "assessments": [item.to_packet() for item in assessments],
            "research_plan": research_plan.to_packet(),
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
                "sync_mode": sync.sync_mode,
                "requested_bars": sync.requested_bars,
                "repaired_history_dates": [
                    item.isoformat() for item in sync.repaired_dates
                ],
                "quote_available": bundle.quote.price is not None,
                "strategy_evaluated": evaluate_strategies,
                "limitations": [
                    "盘中行情快照不等同于最终收盘价",
                    "低频基本面与外部事件需要研究代理补充",
                    "公开数据源可能延迟或暂时不可用",
                ],
            },
        }
        latest_path = self._repository.save_packet(symbol, packet)
        prompt = (
            f"研究 {instrument.name}（{symbol}），数据包：{latest_path}。"
            "自主选择分析方法和工具；research_plan 是参考关注点。"
            "区分事实、假设与预测，检查数据时间，保存实验及失败结果。"
            "人的研究报告按 AGENTS.md 约定归档到飞书标的主页下。"
        )
        self._repository.save_prompt(symbol, prompt)
        return latest_path, packet
