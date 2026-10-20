"""筛选器：从候选池筛出适合做波段的标的。

漏斗设计
--------
0. 流动性：成交额、换手率，剔除 ST/退市（见 ``universe``）
1. 波段弹性：年化波动率、周期振幅、年均波段次数 —— 有没有肉可吃
2. 可做性：最大回撤、最长水下根数 —— 拿了能不能拿住
3. 入场时点：距 52 周高点回撤 —— 现在是不是个买入位置

两套周期预设
------------
``period="weekly"``（默认）面向以周为最小决策单位的中期波段：窗口 5 年、
zigzag 阈值 12%、振幅门槛按周振幅给、水下上限 104 周（约 2 年）、入场回撤门槛 20%。
``period="daily"`` 保留日线口径：窗口 3 年、阈值 15%、水下 504 个交易日、入场门槛 15%。

趋势结构（``trend_ratio``：周期收盘站上周期均线的占比）与均值回归偏好
（``autocorr_1`` / ``variance_ratio_5``）只参与打分，**不作为硬门槛**，
避免把趋势型标的直接筛掉。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional

import pandas as pd

from ..data import ParquetStore, fetch_etf_snapshot, get_daily, get_etf_daily
from ..settings import get_settings
from .metrics import PERIODS_PER_YEAR, swing_metrics
from .universe import build_candidates, build_etf_candidates, fetch_snapshot

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
    ("median_amplitude", "周期振幅", "pct"),
    ("max_drawdown", "最大回撤", "pct"),
    ("distance_from_52w_high", "距52周高", "pct"),
    ("trend_ratio", "均线上占比", "pct"),
    ("variance_ratio_5", "VR(5)", "num"),
]

REPORT_COLUMNS = [
    "symbol",
    "name",
    "score",
    "swings_per_year",
    "swing_count",
    "avg_swing_amplitude",
    "annual_volatility",
    "median_amplitude",
    "max_drawdown",
    "longest_underwater_bars",
    "distance_from_52w_high",
    "trend_ratio",
    "autocorr_1",
    "variance_ratio_5",
    "bars",
    "funnel",
]


@dataclass(frozen=True)
class FunnelConfig:
    """漏斗阈值。默认是**周线口径**，日线口径用 ``FunnelConfig.for_period("daily")``。"""

    period: str = "weekly"
    years: float = 5.0
    swing_threshold: float = 0.12

    # 第 1 层 波段弹性
    min_annual_volatility: float = 0.25
    max_annual_volatility: float = 0.50
    min_median_amplitude: float = 0.04
    min_swings_per_year: float = 3.0

    # 第 2 层 可做性
    max_drawdown_limit: float = 0.45
    max_underwater_bars: int = 104

    # 第 3 层 入场时点
    min_drop_from_high: float = 0.20

    @classmethod
    def for_period(cls, period: str = "weekly", years: Optional[float] = None) -> "FunnelConfig":
        """返回指定周期的预设阈值。"""
        if period == "daily":
            return cls(
                period="daily",
                years=years if years is not None else 3.0,
                swing_threshold=0.15,
                min_median_amplitude=0.02,
                max_underwater_bars=504,
                min_drop_from_high=0.15,
            )
        return cls(period="weekly", years=years if years is not None else 5.0)


def universe_defaults(asset: str, period: str) -> dict[str, float]:
    """按资产类型与周期给出第 0 层默认门槛。

    周级波段不依赖日内活跃度，故换手率区间比日线放宽；ETF 无换手率口径，
    其流动性在拉取历史后用成交额判定。
    """
    if asset == "etf":
        return {
            "min_amount": 1e8,
            "min_turnover_rate": 0.0,
            "max_turnover_rate": float("inf"),
            "max_candidates": 150,
        }
    if period == "weekly":
        return {
            "min_amount": 1e8,
            "min_turnover_rate": 1.0,
            "max_turnover_rate": 30.0,
            "max_candidates": 300,
        }
    return {
        "min_amount": 1e8,
        "min_turnover_rate": 3.0,
        "max_turnover_rate": 12.0,
        "max_candidates": 200,
    }


def evaluate_funnel(metrics: dict[str, float], config: FunnelConfig) -> str:
    """返回 ``"通过"`` 或首个未通过的层名。"""
    if not config.min_annual_volatility <= metrics["annual_volatility"] <= config.max_annual_volatility:
        return "1-波动率越界"
    if metrics["median_amplitude"] < config.min_median_amplitude:
        return "1-周期振幅不足"
    if metrics["swings_per_year"] < config.min_swings_per_year:
        return "1-波段次数不足"
    if metrics["max_drawdown"] < -config.max_drawdown_limit:
        return "2-回撤过大"
    if metrics["longest_underwater_bars"] > config.max_underwater_bars:
        return "2-水下时间过长"
    if -metrics["distance_from_52w_high"] < config.min_drop_from_high:
        return "3-距高点过近"
    return "通过"


def _composite_score(frame: pd.DataFrame) -> pd.Series:
    """百分位打分：波段次数、振幅、回撤、入场位置、趋势结构、均值回归偏好各占一档。

    分数是相对候选集计算的，因此只用于组内排序，不跨批次比较。
    """
    parts = [
        frame["swings_per_year"].rank(pct=True).fillna(0.5),
        frame["median_amplitude"].rank(pct=True).fillna(0.5),
        (-frame["max_drawdown"]).rank(pct=True).fillna(0.5),
        (-frame["distance_from_52w_high"]).rank(pct=True).fillna(0.5),
        frame["trend_ratio"].rank(pct=True).fillna(0.5),
        (-frame["variance_ratio_5"]).rank(pct=True).fillna(0.5),
    ]
    return (sum(parts) / len(parts) * 100).round(2)


def _resolve_range(end: Optional[str], years: float) -> tuple[str, str]:
    end_date = datetime.strptime(end, "%Y%m%d").date() if end else date.today()
    start_date = end_date - timedelta(days=int(years * 365.25) + 10)
    return start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")


def _candidate_symbols(
    symbols: Optional[Iterable[str]],
    asset: str,
    *,
    min_amount: float,
    min_turnover_rate: float,
    max_turnover_rate: float,
    include_bj: bool,
    max_candidates: int,
) -> tuple[list[str], dict[str, str]]:
    if symbols is not None:
        return list(symbols), {}

    if asset == "etf":
        candidates = build_etf_candidates(fetch_etf_snapshot(), max_candidates=max_candidates)
    else:
        candidates = build_candidates(
            fetch_snapshot(),
            min_amount=min_amount,
            min_turnover_rate=min_turnover_rate,
            max_turnover_rate=max_turnover_rate,
            include_bj=include_bj,
            max_candidates=max_candidates,
        )
    return candidates["symbol"].tolist(), dict(zip(candidates["symbol"], candidates["name"]))


def run_screen(
    symbols: Optional[Iterable[str]] = None,
    *,
    asset: str = "stock",
    period: str = "weekly",
    end: Optional[str] = None,
    config: Optional[FunnelConfig] = None,
    min_amount: Optional[float] = None,
    min_turnover_rate: Optional[float] = None,
    max_turnover_rate: Optional[float] = None,
    include_bj: bool = False,
    max_candidates: Optional[int] = None,
    refresh: bool = False,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> pd.DataFrame:
    """跑一次完整筛选，返回全部候选及其指标、漏斗结论与评分。

    :param symbols: 指定标的（给定则不抓快照）；不传则按 ``asset`` 走快照取第 0 层。
    :param asset: ``stock`` 个股 / ``etf`` 基金。
    :param period: ``daily`` 或 ``weekly``，指标在该周期上计算。
    :param end: 结束日期 ``YYYYMMDD``，默认今天。
    :param config: 漏斗阈值，默认按 ``period`` 取预设。
    :param min_amount: 第 0 层最小成交额（元）。ETF 模式下用于历史成交额判定。
    :param max_candidates: 第 0 层候选上限。为 ``None`` 时按 asset+period 取默认。
    :param progress: 进度回调 ``(已完成, 总数, 当前标的)``。
    """
    if asset not in {"stock", "etf"}:
        raise ValueError(f"不支持的资产类型: {asset!r}，可选 ['stock', 'etf']")

    cfg = config or FunnelConfig.for_period(period)
    defaults = universe_defaults(asset, period)
    amount_floor = min_amount if min_amount is not None else defaults["min_amount"]
    turnover_min = min_turnover_rate if min_turnover_rate is not None else defaults["min_turnover_rate"]
    turnover_max = max_turnover_rate if max_turnover_rate is not None else defaults["max_turnover_rate"]
    candidate_cap = int(max_candidates if max_candidates is not None else defaults["max_candidates"])

    start, end_date = _resolve_range(end, cfg.years)
    min_bars = int(cfg.years * PERIODS_PER_YEAR[cfg.period] * 0.9)

    codes, names = _candidate_symbols(
        symbols,
        asset,
        min_amount=amount_floor,
        min_turnover_rate=turnover_min,
        max_turnover_rate=turnover_max,
        include_bj=include_bj,
        max_candidates=candidate_cap,
    )

    store = (
        ParquetStore(get_settings().data_dir / "etf")
        if asset == "etf"
        else ParquetStore(get_settings().data_dir)
    )
    loader = get_etf_daily if asset == "etf" else get_daily
    load_kwargs = {} if asset == "etf" else {"adjust": "qfq"}

    rows: list[dict[str, object]] = []
    total = len(codes)

    for index, symbol in enumerate(codes, start=1):
        if progress is not None:
            progress(index, total, symbol)
        if not store.has(symbol, **load_kwargs):
            time.sleep(_FETCH_INTERVAL_SECONDS)

        try:
            bars = loader(symbol, start, end_date, refresh=refresh, **load_kwargs)
            if len(bars) < min_bars:
                # 缓存窗口不足时强制重抓，避免用残缺样本算指标
                bars = loader(symbol, start, end_date, refresh=True, **load_kwargs)
        except Exception:
            # 单只抓取失败不应中断整轮筛选
            rows.append({"symbol": symbol, "name": names.get(symbol, ""), "funnel": "0-抓取失败"})
            continue

        row: dict[str, object] = {"symbol": symbol, "name": names.get(symbol, "")}
        if len(bars) < min_bars:
            row.update({"bars": float(len(bars)), "funnel": "0-历史长度不足"})
            rows.append(row)
            continue

        # ETF 无快照成交额，用历史成交额（成交量 × 收盘价）代理流动性门槛
        if asset == "etf":
            avg_amount = float((bars["volume"].astype(float) * bars["close"].astype(float)).tail(60).mean())
            row["avg_amount"] = avg_amount
            if avg_amount < amount_floor:
                row["funnel"] = "0-成交额不足"
                rows.append(row)
                continue

        metrics = swing_metrics(bars, period=cfg.period, swing_threshold=cfg.swing_threshold)
        row.update(metrics)
        row["funnel"] = evaluate_funnel(metrics, cfg)
        rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    passed = result["funnel"].eq("通过") & result["swings_per_year"].notna()
    result["passed"] = passed
    result["score"] = pd.NA
    if passed.any():
        result.loc[passed, "score"] = _composite_score(result.loc[passed])

    result = result.sort_values(
        ["passed", "score", "swings_per_year"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)
    return result


def run_out_of_sample(
    symbols: Optional[Iterable[str]] = None,
    *,
    asset: str = "stock",
    period: str = "weekly",
    train_years: float = 3.0,
    test_years: float = 2.0,
    end: Optional[str] = None,
    config: Optional[FunnelConfig] = None,
    refresh: bool = False,
    progress: Optional[Callable[[int, int, str], None]] = None,
    **universe_kwargs: object,
) -> pd.DataFrame:
    """样本外验证：用前一段窗口筛选，再看这些标的在后一段窗口是否仍通过。

    返回入选标的的前段/后段指标与漏斗结论，``survived`` 表示后段仍然通过。
    这是检验筛选器是否只是"事后拟合"的关键步骤。
    """
    cfg = config or FunnelConfig.for_period(period)
    end_date = datetime.strptime(end, "%Y%m%d").date() if end else date.today()
    train_end = end_date - timedelta(days=int(test_years * 365.25))

    keep = [
        "funnel",
        "score",
        "swings_per_year",
        "avg_swing_amplitude",
        "annual_volatility",
        "median_amplitude",
        "max_drawdown",
        "longest_underwater_bars",
        "distance_from_52w_high",
        "trend_ratio",
    ]
    merged_columns = [
        "symbol",
        "name",
        *(f"train_{c}" for c in keep),
        *(f"test_{c}" for c in keep),
        "survived",
    ]

    train = run_screen(
        symbols,
        asset=asset,
        period=cfg.period,
        end=train_end.strftime("%Y%m%d"),
        config=replace(cfg, years=train_years),
        refresh=refresh,
        progress=progress,
        **universe_kwargs,
    )
    selected = train.loc[train["passed"], "symbol"].tolist() if not train.empty else []
    if not selected:
        # 前段没有标的通过：返回结构一致的空结果，便于调用方统一处理
        return pd.DataFrame(columns=merged_columns)

    test = run_screen(
        selected,
        asset=asset,
        period=cfg.period,
        end=end_date.strftime("%Y%m%d"),
        config=replace(cfg, years=test_years),
        refresh=refresh,
        **universe_kwargs,
    )

    left = train.loc[train["passed"], ["symbol", "name", *keep]].rename(
        columns={c: f"train_{c}" for c in keep}
    )
    right = test[["symbol", *keep]].rename(columns={c: f"test_{c}" for c in keep})
    merged = left.merge(right, on="symbol", how="left")
    merged["survived"] = merged["test_funnel"].eq("通过")
    return merged.sort_values(["survived", "test_swings_per_year"], ascending=[False, False]).reset_index(
        drop=True
    )
