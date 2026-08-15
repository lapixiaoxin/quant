"""应用层依赖的外部能力契约。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ..domain.models import Instrument, MarketBundle


class MarketDataProvider(Protocol):
    """行情数据入口，可由公开接口、商业数据源或本地回放实现。"""

    def fetch(self, instrument: Instrument, limit: int) -> MarketBundle:
        """采集一个标的的行情快照与历史日线。"""


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


class NotificationChannel(Protocol):
    """报告发送通道。"""

    channel_id: str

    def send(self, title: str, markdown: str) -> None:
        """发送一份 Markdown 报告。"""


class ResearchAgentRunner(Protocol):
    """可无头运行的外部研究代理。"""

    def is_available(self) -> bool:
        """目标设备是否已具备运行条件。"""

    def run(self, symbol: str, *, send: bool) -> Path:
        """运行一个标的的完整研究命令并返回报告路径。"""
