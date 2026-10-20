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


def build_etf_candidates(
    snapshot: pd.DataFrame,
    *,
    max_candidates: int = 150,
) -> pd.DataFrame:
    """ETF 第 0 层：按代码排序后截断。

    当前网络环境下没有可用的 ETF 流动性快照（新浪 ETF 分类接口的成交额字段恒为
    0，东财源不可达），因此不在此处做流动性过滤——ETF 的流动性门槛在拉取历史后
    用历史成交额（成交量 × 收盘价）自行判定，见 ``screen.run_screen``。

    :param max_candidates: 抓取上限。代码排序不代表流动性排序，因此若要做全市场
        ETF 筛选，应把它调大（全量约 1700 只，首次抓取耗时较长，之后走缓存）。
    """
    return snapshot.sort_values("symbol").head(max_candidates).reset_index(drop=True)
