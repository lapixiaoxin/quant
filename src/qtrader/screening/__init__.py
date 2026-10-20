"""筛选层：把"适合做波段"翻译成可计算条件，从全市场筛出候选池。"""

from .metrics import swing_metrics, zigzag_swings
from .screen import (
    DISPLAY_COLUMNS,
    REPORT_COLUMNS,
    FunnelConfig,
    evaluate_funnel,
    run_screen,
)
from .universe import build_candidates, fetch_snapshot

__all__ = [
    "DISPLAY_COLUMNS",
    "REPORT_COLUMNS",
    "FunnelConfig",
    "build_candidates",
    "evaluate_funnel",
    "fetch_snapshot",
    "run_screen",
    "swing_metrics",
    "zigzag_swings",
]
