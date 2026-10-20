"""筛选层：把"适合做波段"翻译成可计算条件，从全市场筛出候选池。"""

from .metrics import PERIODS_PER_YEAR, resample, swing_metrics, zigzag_swings
from .screen import (
    DISPLAY_COLUMNS,
    REPORT_COLUMNS,
    FunnelConfig,
    evaluate_funnel,
    run_out_of_sample,
    run_screen,
    universe_defaults,
)
from .universe import build_candidates, build_etf_candidates, fetch_snapshot

__all__ = [
    "DISPLAY_COLUMNS",
    "PERIODS_PER_YEAR",
    "REPORT_COLUMNS",
    "FunnelConfig",
    "build_candidates",
    "build_etf_candidates",
    "evaluate_funnel",
    "fetch_snapshot",
    "resample",
    "run_out_of_sample",
    "run_screen",
    "swing_metrics",
    "universe_defaults",
    "zigzag_swings",
]
