"""冒烟测试：用合成数据跑通 回测、paper 实盘 与 数据缓存 链路（不依赖网络）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qtrader.backtest import run as run_backtest
from qtrader.data import ParquetStore, fetch_daily
from qtrader.live import run_session
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
