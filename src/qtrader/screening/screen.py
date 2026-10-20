"""四层漏斗筛选器：从全市场候选池筛出适合做波段的标的。

漏斗设计
--------
0. 流动性：成交额、换手率，剔除 ST/退市（见 ``universe.build_candidates``）
1. 波段弹性：年化波动率、日内振幅、年均波段次数 —— 有没有肉可吃
2. 可做性：最大回撤、最长水下时间 —— 拿了能不能拿住
3. 入场时点：距 52 周高点 —— 现在是不是个买入位置

收益自相关与方差比（VR5）只参与打分偏好（偏向均值回归），**不作为硬门槛**，
否则会把趋势型标的直接筛掉。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional

import pandas as pd

from ..data import ParquetStore, get_daily
from ..settings import get_settings
from .metrics import swing_metrics
from .universe import build_candidates, fetch_snapshot

# 逐个抓取时的礼貌间隔，避免批量请求被数据源限流
_FETCH_INTERVAL_SECONDS = 0.1

# 终端展示列：(字段, 中文表头, 格式)  格式取 num / pct / text
DISPLAY_COLUMNS = [
    ("symbol", "代码", "text"),
    ("name", "名称", "text"),
    ("score", "评分", "num"),
    ("swings_per_year", "波段次数/年", "num"),
    ("avg_swing_amplitude", "波段平均幅度", "pct"),
    ("annual_volatility", "年化波动", "pct"),
    ("median_daily_amplitude", "日均振幅", "pct"),
    ("max_drawdown", "最大回撤", "pct"),
    ("distance_from_52w_high", "距52周高", "pct"),
    ("variance_ratio_5", "VR(5)", "num"),
]

REPORT_COLUMNS = [
    "symbol",
    "name",
    "score",
    "swings_per_year",
    "avg_swing_amplitude",
    "annual_volatility",
    "median_daily_amplitude",
    "max_drawdown",
    "longest_underwater_days",
    "distance_from_52w_high",
    "autocorr_1d",
    "variance_ratio_5",
    "bars",
    "funnel",
]


@dataclass(frozen=True)
class FunnelConfig:
    """四层漏斗阈值。"""

    years: float = 3.0
    swing_threshold: float = 0.15

    # 第 1 层 波段弹性
    min_annual_volatility: float = 0.25
    max_annual_volatility: float = 0.50
    min_median_amplitude: float = 0.02
    min_swings_per_year: float = 3.0

    # 第 2 层 可做性
    max_drawdown_limit: float = 0.45
    max_underwater_days: int = 504

    # 第 3 层 入场时点
    min_drop_from_high: float = 0.15


def evaluate_funnel(metrics: dict[str, float], config: FunnelConfig) -> str:
    """返回 ``"通过"`` 或首个未通过的层名。"""
    if not config.min_annual_volatility <= metrics["annual_volatility"] <= config.max_annual_volatility:
        return "1-波动率越界"
    if metrics["median_daily_amplitude"] < config.min_median_amplitude:
        return "1-日内振幅不足"
    if metrics["swings_per_year"] < config.min_swings_per_year:
        return "1-波段次数不足"
    if metrics["max_drawdown"] < -config.max_drawdown_limit:
        return "2-回撤过大"
    if metrics["longest_underwater_days"] > config.max_underwater_days:
        return "2-水下时间过长"
    if -metrics["distance_from_52w_high"] < config.min_drop_from_high:
        return "3-距高点过近"
    return "通过"


def _composite_score(frame: pd.DataFrame) -> pd.Series:
    """百分位打分：波段次数、振幅、回撤、入场位置、均值回归偏好各占一档。

    分数是相对候选集计算的，因此只用于组内排序，不跨批次比较。
    """
    parts = [
        frame["swings_per_year"].rank(pct=True).fillna(0.5),
        frame["median_daily_amplitude"].rank(pct=True).fillna(0.5),
        (-frame["max_drawdown"]).rank(pct=True).fillna(0.5),
        (-frame["distance_from_52w_high"]).rank(pct=True).fillna(0.5),
        (-frame["variance_ratio_5"]).rank(pct=True).fillna(0.5),
    ]
    return (sum(parts) / len(parts) * 100).round(2)


def _resolve_range(end: Optional[str], years: float) -> tuple[str, str]:
    end_date = datetime.strptime(end, "%Y%m%d").date() if end else date.today()
    start_date = end_date - timedelta(days=int(years * 365.25) + 10)
    return start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")


def run_screen(
    symbols: Optional[Iterable[str]] = None,
    *,
    end: Optional[str] = None,
    config: Optional[FunnelConfig] = None,
    min_amount: float = 1e8,
    min_turnover_rate: float = 3.0,
    max_turnover_rate: float = 12.0,
    include_bj: bool = False,
    max_candidates: int = 200,
    refresh: bool = False,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> pd.DataFrame:
    """跑一次完整筛选，返回全部候选及其指标、漏斗结论与评分。

    :param symbols: 指定标的（给定则不抓快照）；不传则走全市场快照取第 0 层候选。
    :param end: 结束日期 ``YYYYMMDD``，默认今天。
    :param config: 漏斗阈值。
    :param max_candidates: 第 0 层候选上限，直接决定抓取次数与耗时。
    :param progress: 进度回调 ``(已完成, 总数, 当前标的)``。
    """
    cfg = config or FunnelConfig()
    start, end_date = _resolve_range(end, cfg.years)
    min_bars = int(cfg.years * 242 * 0.9)

    if symbols is not None:
        codes = list(symbols)
        names: dict[str, str] = {}
    else:
        snapshot = fetch_snapshot()
        candidates = build_candidates(
            snapshot,
            min_amount=min_amount,
            min_turnover_rate=min_turnover_rate,
            max_turnover_rate=max_turnover_rate,
            include_bj=include_bj,
            max_candidates=max_candidates,
        )
        codes = candidates["symbol"].tolist()
        names = dict(zip(candidates["symbol"], candidates["name"]))

    store = ParquetStore(get_settings().data_dir)
    rows: list[dict[str, object]] = []
    total = len(codes)

    for index, symbol in enumerate(codes, start=1):
        if progress is not None:
            progress(index, total, symbol)
        if not store.has(symbol, adjust="qfq"):
            time.sleep(_FETCH_INTERVAL_SECONDS)

        try:
            bars = get_daily(symbol, start, end_date, refresh=refresh, adjust="qfq")
            if len(bars) < min_bars:
                # 缓存窗口不足时强制重抓，避免用残缺样本算指标
                bars = get_daily(symbol, start, end_date, refresh=True, adjust="qfq")
        except Exception:
            # 单只抓取失败不应中断整轮筛选
            rows.append({"symbol": symbol, "name": names.get(symbol, ""), "funnel": "0-抓取失败"})
            continue

        row: dict[str, object] = {"symbol": symbol, "name": names.get(symbol, "")}
        if len(bars) < min_bars:
            row.update({"bars": float(len(bars)), "funnel": "0-历史长度不足"})
            rows.append(row)
            continue

        metrics = swing_metrics(bars, threshold=cfg.swing_threshold)
        row.update(metrics)
        row["funnel"] = evaluate_funnel(metrics, cfg)
        rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    scored = result["funnel"].eq("通过") & result["swings_per_year"].notna()
    result["passed"] = scored
    if scored.any():
        result.loc[scored, "score"] = _composite_score(result.loc[scored])
    else:
        result["score"] = pd.NA

    result = result.sort_values(
        ["passed", "score", "swings_per_year"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)
    return result
