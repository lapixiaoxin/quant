"""显式研究请求：准备数据、评估规则并登记本地草稿。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
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
from .monitoring import MonitoringService
from .ports import ControlPlaneRepository, ResearchRepository


@dataclass(frozen=True)
class AnalysisResult:
    """一次确定性分析的产物，不代表完成了 Agent 深度研究。"""

    symbol: str
    packet_path: Path
    report_path: Path


@dataclass(frozen=True)
class AnalysisExecution:
    """多标的运行保留各标的成功产物与独立失败原因。"""

    request: AnalysisRequest
    request_path: Path
    results: tuple[AnalysisResult, ...]
    errors: tuple[str, ...]


class AnalysisService:
    """不启动 Agent、不通知；研究者按需调用确定性基线。"""

    def __init__(
        self,
        settings: Settings,
        monitoring: MonitoringService,
        repository: ResearchRepository,
        control_repository: ControlPlaneRepository,
        factors: FactorRegistry,
        report_renderer: Callable[[dict[str, Any]], str],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._monitoring = monitoring
        self._repository = repository
        self._control = control_repository
        self._factors = factors
        self._render = report_renderer
        self._clock = clock or (lambda: datetime.now(ZoneInfo(settings.timezone)))

    def create_request(
        self,
        *,
        symbols: tuple[str, ...],
        cycles: tuple[AnalysisCycle, ...],
        factor_ids: tuple[str, ...] = (),
    ) -> AnalysisRequest:
        for symbol in symbols:
            self._settings.instrument_for(symbol)
        resolved = self._factors.resolve(cycles, factor_ids)
        now = self._clock()
        return AnalysisRequest(
            request_id=f"{now:%Y%m%dT%H%M%S}-{uuid4().hex[:8]}",
            requested_at=now,
            trigger=AnalysisTrigger.MANUAL,
            mode="research",
            symbols=tuple(dict.fromkeys(symbols)),
            cycles=cycles,
            factor_ids=tuple(item.factor_id for item in resolved),
            send=False,
        )

    def run(self, request: AnalysisRequest) -> AnalysisExecution:
        if request.send or request.mode != "research":
            raise ValueError("旧自动化请求只能读取，请创建新的 research 分析请求")
        path = self._repository.save_analysis_request(
            request.request_id,
            request.to_packet(),
        )
        self._control.save_analysis_request(request, status="running")
        results, errors = [], []
        for symbol in request.symbols:
            try:
                packet_path, packet = self._monitoring.prepare(
                    symbol,
                    request,
                    evaluate_strategies=True,
                )
                report = self._repository.save_base_report(
                    symbol,
                    str(packet["as_of"]),
                    self._render(packet),
                )
                self._control.save_report(
                    ReportRecord(
                        report_id=f"{request.request_id}:{symbol}",
                        analysis_request_id=request.request_id,
                        symbol=symbol,
                        report_type="base_report",
                        title=f"{symbol} 确定性研究基线",
                        path=str(report.relative_to(self._settings.root)),
                        generated_at=self._clock(),
                        strategy_record_ids=tuple(
                            item["record_id"] for item in packet["strategy_plan"]
                        ),
                        cycles=tuple(item.value for item in request.cycles),
                        factor_ids=request.factor_ids,
                        channels=(),
                        delivery_status="draft",
                    )
                )
                results.append(AnalysisResult(symbol, packet_path, report))
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(f"{symbol}：{error}")
        self._control.complete_analysis(
            request.request_id,
            completed_at=self._clock(),
            status="partial"
            if errors and results
            else "failed"
            if errors
            else "completed",
            error="；".join(errors),
        )
        return AnalysisExecution(request, path, tuple(results), tuple(errors))
