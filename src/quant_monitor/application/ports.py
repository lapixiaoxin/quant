"""应用层依赖的外部能力契约。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from ..domain.control_plane import (
    AnalysisRequest,
    BacktestRunRecord,
    ReportRecord,
    SelectionRunRecord,
)
from ..domain.models import DailyBar, HistorySummary, Instrument, MarketBundle


class MarketDataProvider(Protocol):
    """行情数据入口，可由公开接口、商业数据源或本地回放实现。"""

    def fetch(self, instrument: Instrument, limit: int) -> MarketBundle:
        """采集一个标的的行情快照与历史日线。"""


class MarketHistoryRepository(Protocol):
    """标准化日线行情的本地查询与持久化契约。"""

    def save_bundle(
        self,
        instrument: Instrument,
        bundle: MarketBundle,
        fetched_at: datetime,
    ) -> None:
        """以幂等方式保存一次行情采集中的历史日线。"""

    def load_bars(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
    ) -> tuple[DailyBar, ...]:
        """按时间升序读取日线，供指标和未来回测使用。"""

    def summarize(self, symbol: str) -> HistorySummary:
        """返回一个标的在本地历史库中的覆盖情况。"""


class ResearchRepository(Protocol):
    """研究数据的持久化契约。"""

    def save_packet(self, symbol: str, packet: dict[str, Any]) -> Path:
        """保存最新数据包和带时间戳的不可变快照。"""

    def load_latest_packet(self, symbol: str) -> dict[str, Any]:
        """读取指定标的的最新数据包。"""

    def save_prompt(self, symbol: str, prompt: str) -> Path:
        """保存供分析代理使用的紧凑提示。"""

    def save_base_report(
        self, symbol: str, as_of: str, content: str
    ) -> Path:
        """保存基础报告及 latest 副本。"""

    def list_latest_packets(self) -> list[dict[str, Any]]:
        """读取所有可解析的最新数据包。"""

    def save_selection_packet(
        self,
        universe_id: str,
        packet: dict[str, Any],
    ) -> Path:
        """保存候选池最新结果和带时间戳的不可变快照。"""

    def save_analysis_request(
        self,
        request_id: str,
        packet: dict[str, Any],
    ) -> Path:
        """保存分析请求文件，供 CLI 和外部 Agent 共享。"""


class ControlPlaneRepository(Protocol):
    """选择、分析、回测、报告和发布状态的统一运行索引。"""

    def save_analysis_request(
        self,
        request: AnalysisRequest,
        *,
        status: str = "pending",
    ) -> None:
        """登记分析请求。"""

    def complete_analysis(
        self,
        request_id: str,
        *,
        completed_at: datetime,
        status: str,
        error: str = "",
    ) -> None:
        """完成或失败一个分析请求。"""

    def save_report(self, record: ReportRecord) -> None:
        """登记报告及发布状态。"""

    def save_selection(self, record: SelectionRunRecord) -> None:
        """登记候选筛选运行。"""

    def save_backtest(self, record: BacktestRunRecord) -> None:
        """登记回测运行。"""


class NotificationChannel(Protocol):
    """报告发送通道。"""

    channel_id: str

    def send(self, title: str, markdown: str) -> None:
        """发送一份 Markdown 报告。"""


class ResearchAgentRunner(Protocol):
    """可无头运行的外部研究代理。"""

    def is_available(self) -> bool:
        """目标设备是否已具备运行条件。"""

    def run(
        self,
        symbol: str,
        *,
        send: bool,
        analysis_request_path: Path | None = None,
    ) -> Path:
        """运行一个标的的完整研究命令并返回报告路径。"""
