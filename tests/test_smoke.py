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
    evaluate_funnel,
    swing_metrics,
    zigzag_swings,
)
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


def test_swing_metrics_returns_expected_fields() -> None:
    metrics = swing_metrics(_synthetic(), threshold=0.15)
    for key in [
        "annual_volatility",
        "median_daily_amplitude",
        "swings_per_year",
        "max_drawdown",
        "longest_underwater_days",
        "distance_from_52w_high",
    ]:
        assert key in metrics
    assert metrics["bars"] == 120
    assert metrics["max_drawdown"] <= 0


def _good_metrics() -> dict[str, float]:
    return {
        "annual_volatility": 0.35,
        "median_daily_amplitude": 0.03,
        "swings_per_year": 4.0,
        "max_drawdown": -0.30,
        "longest_underwater_days": 300.0,
        "distance_from_52w_high": -0.20,
    }


def test_funnel_requires_all_layers_to_hold() -> None:
    config = FunnelConfig()
    assert evaluate_funnel(_good_metrics(), config) == "通过"

    assert evaluate_funnel(_good_metrics() | {"annual_volatility": 0.10}, config) == "1-波动率越界"
    assert evaluate_funnel(_good_metrics() | {"swings_per_year": 1.0}, config) == "1-波段次数不足"
    assert evaluate_funnel(_good_metrics() | {"max_drawdown": -0.60}, config) == "2-回撤过大"
    assert evaluate_funnel(_good_metrics() | {"distance_from_52w_high": -0.01}, config) == "3-距高点过近"


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
