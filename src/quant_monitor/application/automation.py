"""无人值守研究任务编排。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings
from .monitoring import MonitoringService
from .notifications import NotificationService
from .ports import ResearchAgentRunner, ResearchRepository


@dataclass(frozen=True)
class AutomationResult:
    """单个标的的一次自动化执行结果。"""

    symbol: str
    mode: str
    report_path: Path
    sent_channels: tuple[str, ...]
    fallback_used: bool = False


class AutomationService:
    """按配置选择完整 Agent 研究或确定性基础分析。"""

    def __init__(
        self,
        settings: Settings,
        monitoring: MonitoringService,
        repository: ResearchRepository,
        notifications: NotificationService,
        agent_runner: ResearchAgentRunner,
        report_renderer: Callable[[dict[str, Any]], str],
    ) -> None:
        self._settings = settings
        self._monitoring = monitoring
        self._repository = repository
        self._notifications = notifications
        self._agent_runner = agent_runner
        self._report_renderer = report_renderer

    def _run_base(
        self,
        symbol: str,
        send: bool,
        event: str,
    ) -> AutomationResult:
        _, packet = self._monitoring.prepare(symbol)
        report_path = self._repository.save_base_report(
            symbol,
            str(packet["as_of"]),
            self._report_renderer(packet),
        )
        channels: tuple[str, ...] = ()
        if send:
            markdown = report_path.read_text(encoding="utf-8")
            channels = self._notifications.send(
                symbol,
                event,
                markdown,
            )
        return AutomationResult(
            symbol=symbol,
            mode="base",
            report_path=report_path,
            sent_channels=channels,
        )

    def run(
        self,
        symbol: str,
        *,
        mode: str | None = None,
        send: bool | None = None,
        event: str = "scheduled_report",
    ) -> AutomationResult:
        config = self._settings.automation
        selected_mode = mode or config.mode
        should_send = config.send if send is None else send
        if selected_mode == "base":
            return self._run_base(symbol, should_send, event)
        if selected_mode != "traecli":
            raise ValueError(f"不支持的自动化模式：{selected_mode}")

        if self._agent_runner.is_available():
            report_path = self._agent_runner.run(symbol, send=should_send)
            return AutomationResult(
                symbol=symbol,
                mode="traecli",
                report_path=report_path,
                sent_channels=("按 Agent 命令路由",) if should_send else (),
            )
        if not config.fallback_to_base:
            raise RuntimeError("TraeCode CLI 不可用，且未允许降级为基础分析")
        fallback = self._run_base(symbol, should_send, event)
        return AutomationResult(
            symbol=fallback.symbol,
            mode=fallback.mode,
            report_path=fallback.report_path,
            sent_channels=fallback.sent_channels,
            fallback_used=True,
        )
