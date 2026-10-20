"""冒烟测试：用合成数据跑通 回测、paper 实盘 与 数据缓存 链路（不依赖网络）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qtrader.backtest import run as run_backtest
from qtrader.data import ParquetStore, fetch_daily
from qtrader.live import run_session
from qtrader.screening import (
    FunnelConfig,
    build_candidates,
    build_etf_candidates,
    evaluate_funnel,
    resample,
    swing_metrics,
    universe_defaults,
    zigzag_swings,
)
from qtrader.settings import Settings
from qtrader.strategy import MaCrossStrategy


def _synthetic(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2023-01-01", periods=n)
    close = 10 + np.cumsum(rng.normal(0, 0.05, n))
    close = np.maximum(close, 1.0)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
        }
    )


def test_backtest_runs() -> None:
    result = run_backtest(
        data=_synthetic(),
        strategy=MaCrossStrategy,
        symbols="sh600000",
    )
    assert "total_return_pct" in result.metrics_df.index


def test_paper_live_runs() -> None:
    run_session(
        strategy=MaCrossStrategy,
        symbols=["sh600000"],
        data={"sh600000": _synthetic()},
        duration="5s",
    )


def test_parquet_store_separates_adjust(tmp_path) -> None:
    """不同复权口径必须落到不同文件，互不覆盖。"""
    store = ParquetStore(tmp_path)
    df = _synthetic(10)

    raw = store.save("sh600000", df)
    qfq = store.save("sh600000", df, adjust="qfq")

    assert raw != qfq
    assert store.has("sh600000")
    assert store.has("sh600000", adjust="qfq")
    assert not store.has("sh600000", adjust="hfq")
    assert store.load("sh600000", adjust="qfq") is not None


def test_fetch_daily_forwards_adjust(monkeypatch) -> None:
    """fetch_daily 必须把 adjust 透传给 AKShare。"""
    import akshare as ak

    seen: dict[str, object] = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return pd.DataFrame(
            {
                "date": pd.bdate_range("2023-01-02", periods=3),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 100,
            }
        )

    monkeypatch.setattr(ak, "stock_zh_a_daily", fake)
    fetch_daily("sh600000", "20230101", "20231231", adjust="qfq")
    assert seen["adjust"] == "qfq"


def test_zigzag_detects_swings() -> None:
    """100 → 120 → 90 → 110 应识别出 3 段超过 15% 的波段。"""
    swings = zigzag_swings(pd.Series([100.0, 120.0, 90.0, 110.0]), threshold=0.15)
    assert len(swings) == 3
    assert abs(swings[0] - 0.20) < 1e-9
    assert abs(swings[1] + 0.25) < 1e-9


def test_swing_metrics_daily_returns_expected_fields() -> None:
    metrics = swing_metrics(_synthetic(), period="daily", swing_threshold=0.15)
    for key in [
        "annual_volatility",
        "median_amplitude",
        "swings_per_year",
        "max_drawdown",
        "longest_underwater_bars",
        "distance_from_52w_high",
        "trend_ratio",
    ]:
        assert key in metrics
    assert metrics["bars"] == 120
    assert metrics["max_drawdown"] <= 0
    assert 0.0 <= metrics["trend_ratio"] <= 1.0


def test_swing_metrics_weekly_resamples() -> None:
    """周线口径应把 120 根日线压缩到约 24 根周线。"""
    metrics = swing_metrics(_synthetic(), period="weekly")
    assert 20 <= metrics["bars"] <= 26


def test_resample_weekly_keeps_ohlc_shape() -> None:
    weekly = resample(_synthetic(), "weekly")
    assert list(weekly.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(weekly) < len(_synthetic())
    assert (weekly["high"] >= weekly["low"]).all()


def test_swing_metrics_rejects_unknown_period() -> None:
    try:
        swing_metrics(_synthetic(), period="monthly")
    except ValueError as exc:
        assert "monthly" in str(exc)
    else:
        raise AssertionError("未知周期应抛出 ValueError")


def _good_metrics() -> dict[str, float]:
    """满足周线口径预设的一组指标。"""
    return {
        "annual_volatility": 0.35,
        "median_amplitude": 0.06,
        "swings_per_year": 4.0,
        "max_drawdown": -0.30,
        "longest_underwater_bars": 60.0,
        "distance_from_52w_high": -0.25,
    }


def test_funnel_requires_all_layers_to_hold() -> None:
    config = FunnelConfig()
    assert evaluate_funnel(_good_metrics(), config) == "通过"

    assert evaluate_funnel(_good_metrics() | {"annual_volatility": 0.10}, config) == "1-波动率越界"
    assert evaluate_funnel(_good_metrics() | {"median_amplitude": 0.01}, config) == "1-周期振幅不足"
    assert evaluate_funnel(_good_metrics() | {"swings_per_year": 1.0}, config) == "1-波段次数不足"
    assert evaluate_funnel(_good_metrics() | {"max_drawdown": -0.60}, config) == "2-回撤过大"
    assert evaluate_funnel(_good_metrics() | {"longest_underwater_bars": 200.0}, config) == "2-水下时间过长"
    assert evaluate_funnel(_good_metrics() | {"distance_from_52w_high": -0.05}, config) == "3-距高点过近"


def test_funnel_presets_differ_by_period() -> None:
    """周线口径窗口更长、入场门槛更高、水下容忍按周计。"""
    weekly = FunnelConfig.for_period("weekly")
    daily = FunnelConfig.for_period("daily")
    assert (weekly.period, weekly.years) == ("weekly", 5.0)
    assert (daily.period, daily.years) == ("daily", 3.0)
    assert weekly.min_drop_from_high > daily.min_drop_from_high
    assert weekly.max_underwater_bars < daily.max_underwater_bars
    assert weekly.swing_threshold < daily.swing_threshold


def _snapshot() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["sh600000", "sz000001", "bj920000", "sh600001"],
            "name": ["浦发银行", "平安银行", "安徽凤凰", "ST示例"],
            "amount": [5e8, 2e8, 3e8, 6e8],
            "turnover_rate": [5.0, 2.0, 6.0, 5.0],
            "market_cap_yi": [1000.0, 500.0, 50.0, 300.0],
            "amplitude": [2.0, 1.5, 3.0, 2.0],
            "price": [10.0, 12.0, 13.0, 5.0],
            "change_pct": [1.0, -1.0, 2.0, 0.5],
        }
    )


def test_build_candidates_applies_layer_zero_filters() -> None:
    """换手率不足、北交所、ST 的标的都应被第 0 层剔除。"""
    kept = build_candidates(_snapshot())
    assert kept["symbol"].tolist() == ["sh600000"]

    assert build_candidates(_snapshot(), include_bj=True)["symbol"].tolist() == [
        "sh600000",
        "bj920000",
    ]


def test_build_candidates_respects_max_candidates() -> None:
    snap = _snapshot()
    snap.loc[1, "turnover_rate"] = 5.0  # 让 sz000001 也通过流动性与活跃度门槛
    snap.loc[3, "name"] = "示例股票"  # 去掉 ST 标记

    assert len(build_candidates(snap)) == 3
    # 截断后按成交额降序，成交额最大的是 sh600001（6 亿）
    assert build_candidates(snap, max_candidates=1)["symbol"].tolist() == ["sh600001"]


def test_build_etf_candidates_sorts_and_caps() -> None:
    snap = pd.DataFrame({"symbol": ["sz159915", "sh510300", "sh588000", "sh512480"]})
    kept = build_etf_candidates(snap, max_candidates=2)
    assert kept["symbol"].tolist() == ["sh510300", "sh512480"]


def test_universe_defaults_relax_turnover_for_weekly() -> None:
    """周级波段不依赖日内活跃度，换手率区间应比日线放宽。"""
    weekly = universe_defaults("stock", "weekly")
    daily = universe_defaults("stock", "daily")
    assert weekly["min_turnover_rate"] < daily["min_turnover_rate"]
    assert weekly["max_turnover_rate"] > daily["max_turnover_rate"]


def test_fee_params_zero_stamp_tax_for_etf() -> None:
    """ETF 免印花税与过户费，个股按配置收取。"""
    stock = Settings(asset_type="stock", stamp_tax_rate=0.0005, transfer_fee_rate=0.00001)
    etf = Settings(asset_type="etf")
    assert etf.fee_params()["stamp_tax_rate"] == 0.0
    assert etf.fee_params()["transfer_fee_rate"] == 0.0
    assert stock.fee_params()["stamp_tax_rate"] == 0.0005
    assert stock.fee_params()["transfer_fee_rate"] == 0.00001
