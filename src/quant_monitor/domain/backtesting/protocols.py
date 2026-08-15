"""回测信号模型契约。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from ..models import DailyBar, Instrument
from .models import BacktestSignal


class BacktestSignalModel(Protocol):
    """把历史窗口转换为目标仓位，不负责撮合或数据访问。"""

    model_id: str
    model_version: str
    minimum_bars: int

    def validate_parameters(self, parameters: dict[str, Any]) -> None:
        """在回测启动前校验模型参数。"""

    def generate_signal(
        self,
        instrument: Instrument,
        history: Sequence[DailyBar],
        parameters: dict[str, Any],
    ) -> BacktestSignal:
        """仅使用当日及以前的数据生成信号，禁止读取未来数据。"""
