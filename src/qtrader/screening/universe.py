"""候选池构建：全市场快照 + 流动性过滤（漏斗第 0 层）。

快照取自腾讯源 ``stock_zh_a_spot_tx``（东财源在部分网络下不可用），其 ``code``
字段已带 ``sh/sz/bj`` 前缀，与 ``stock_zh_a_daily`` 的符号口径一致，可直接复用。
"""

from __future__ import annotations

import pandas as pd

# 快照字段含义：turnover 单位万元，zsz 单位亿元，hsl/zf 单位 %
SNAPSHOT_RENAME = {
    "code": "symbol",
    "name": "name",
    "turnover": "amount_wan",
    "hsl": "turnover_rate",
    "zsz": "market_cap_yi",
    "zf": "amplitude",
    "zxj": "price",
    "zdf": "change_pct",
}

NUMERIC_COLUMNS = [
    "amount_wan",
    "turnover_rate",
    "market_cap_yi",
    "amplitude",
    "price",
    "change_pct",
]


def fetch_snapshot() -> pd.DataFrame:
    """抓取全市场快照并归一列名；新增 ``amount`` 列（单位：元）。"""
    import akshare as ak

    raw = ak.stock_zh_a_spot_tx()
    missing = sorted(set(SNAPSHOT_RENAME) - set(raw.columns))
    if missing:
        raise RuntimeError(f"全市场快照字段缺失，接口可能已变更: {missing}")

    out = raw[list(SNAPSHOT_RENAME)].rename(columns=SNAPSHOT_RENAME).copy()
    for col in NUMERIC_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["symbol"] = out["symbol"].astype(str)
    out["name"] = out["name"].astype(str)
    out["amount"] = out["amount_wan"] * 1e4
    return out


def build_candidates(
    snapshot: pd.DataFrame,
    *,
    min_amount: float = 1e8,
    min_turnover_rate: float = 3.0,
    max_turnover_rate: float = 12.0,
    include_bj: bool = False,
    max_candidates: int = 200,
) -> pd.DataFrame:
    """第 0 层过滤：流动性、活跃度与可交易性。

    默认排除北交所（30% 涨跌幅、流动性偏弱），可用 ``include_bj`` 打开。
    返回按成交额降序、截断到 ``max_candidates`` 的候选表。
    """
    df = snapshot.copy()
    name = df["name"]
    keep = (
        ~name.str.contains("ST", na=False)
        & ~name.str.contains("退", na=False)
        & df["amount"].notna()
        & (df["amount"] > min_amount)
        & df["turnover_rate"].between(min_turnover_rate, max_turnover_rate)
    )
    if not include_bj:
        keep &= ~df["symbol"].str.startswith("bj")

    out = df[keep].sort_values("amount", ascending=False).head(max_candidates)
    return out.reset_index(drop=True)
