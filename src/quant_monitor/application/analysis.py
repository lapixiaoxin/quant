"""标准分析请求：统一 CLI、定时任务和飞书入口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..config import Settings
from ..domain.control_plane import (
    AnalysisCycle,
    AnalysisRequest,
    AnalysisTrigger,
    ReportRecord,
)
from ..domain.factors import FactorRegistry
from ..infrastructure.strategy_catalog import StrategyCatalog
from .automation import AutomationResult, AutomationService
from .ports import ControlPlaneRepository, ResearchRepository


@dataclass(frozen=True)
class AnalysisExecution:
    """一次多标的分析请求的完成状态。"""

    request: AnalysisRequest
    request_path: Path
    results: tuple[AutomationResult, ...]
    errors: tuple[str, ...]


def _delivery_status(result: AutomationResult) -> str:
    if result.delivery_errors:
        return "partial" if result.sent_channels else "failed"
    return "sent" if result.sent_channels else "not_requested"


class AnalysisService:
    """把目标范围、周期、因子、策略和发布状态串成一条作业链。"""

    def __init__(
        self,
        settings: Settings,
        automation: AutomationService,
        repository: ResearchRepository,
        control_repository: ControlPlaneRepository,
        strategy_catalog: StrategyCatalog,
        factors: FactorRegistry,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._automation = automation
        self._repository = repository
        self._control = control_repository
        self._strategies = strategy_catalog
        self._factors = factors
        self._clock = clock or self._system_now

    def _system_now(self) -> datetime:
        return datetime.now(ZoneInfo(self._settings.timezone)).replace(
            microsecond=0
        )

    def create_request(
        self,
        *,
        symbols: tuple[str, ...],
        cycles: tuple[AnalysisCycle, ...],
        factor_ids: tuple[str, ...] = (),
        trigger: AnalysisTrigger,
        mode: str,
        send: bool,
    ) -> AnalysisRequest:
        for symbol in symbols:
            instrument = self._settings.instrument_for(symbol)
            if not instrument.enabled:
                raise ValueError(f"标的 {symbol} 已停用")
        resolved_factors = self._factors.resolve(cycles, factor_ids)
        now = self._clock()
        return AnalysisRequest(
            request_id=(
                f"{now:%Y%m%dT%H%M%S}-"
                f"{uuid4().hex[:8]}"
            ),
            requested_at=now,
            trigger=trigger,
            mode=mode,
            symbols=symbols,
            cycles=cycles,
            factor_ids=tuple(item.factor_id for item in resolved_factors),
            send=send,
        )

    def run(self, request: AnalysisRequest) -> AnalysisExecution:
        request_path = self._repository.save_analysis_request(
            request.request_id,
            request.to_packet(),
        )
        self._control.save_analysis_request(request, status="running")
        results: list[AutomationResult] = []
        errors: list[str] = []
        for symbol in request.symbols:
            try:
                result = self._automation.run(
                    symbol,
                    mode=request.mode,
                    send=request.send,
                    event=(
                        "scheduled_report"
                        if request.trigger is AnalysisTrigger.SCHEDULED
                        else "agent_report"
                    ),
                    analysis_request=request,
                    analysis_request_path=request_path,
                )
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(f"{symbol}：{error}")
                continue
            results.append(result)
            errors.extend(
                f"{symbol} 发布失败：{error}"
                for error in result.delivery_errors
            )
            strategy_records = self._strategies.active_for(
                symbol,
                self._settings.instrument_for(symbol).strategy_profile_ids,
            )
            report_id = f"{request.request_id}:{symbol}:{result.mode}"
            self._control.save_report(
                ReportRecord(
                    report_id=report_id,
                    analysis_request_id=request.request_id,
                    symbol=symbol,
                    report_type=(
                        "strategy_report"
                        if result.mode == "traecli"
                        else "base_report"
                    ),
                    title=f"{symbol} 策略分析报告",
                    path=str(
                        result.report_path.resolve().relative_to(
                            self._settings.root
                        )
                    ),
                    generated_at=self._clock(),
                    strategy_record_ids=tuple(
                        item.record_id for item in strategy_records
                    ),
                    cycles=tuple(item.value for item in request.cycles),
                    factor_ids=request.factor_ids,
                    channels=result.sent_channels,
                    delivery_status=_delivery_status(result),
                )
            )
        status = "completed"
        if errors and results:
            status = "partial"
        elif errors:
            status = "failed"
        self._control.complete_analysis(
            request.request_id,
            completed_at=self._clock(),
            status=status,
            error="；".join(errors),
        )
        return AnalysisExecution(
            request=request,
            request_path=request_path,
            results=tuple(results),
            errors=tuple(errors),
        )
