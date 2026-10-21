"""批量全历史同步：清单驱动的可续跑抓取。

与 ``get_daily`` 的区别：后者只缓存调用方请求的窗口，``sync`` 一次拉取
**从上市到最新**的完整历史，从而支持任意年份区间的回测。

可续跑性由 ``_meta`` 清单保证：每只标的分文件记录 ``first_date/last_date/rows``
与抓取时间，已完整且较新的标的会直接跳过，中断后重跑不会重复抓取。
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

from ..settings import get_settings
from .akshare_source import normalize_daily
from .etf_source import fetch_etf_daily
from .store import ParquetStore

# 全历史抓取起点：早于 A 股最早交易日，等价于"从上市起"
FULL_START = "19900101"
# 清单里 last_date 距今超过该天数则视为需要增量刷新
STALE_DAYS = 7


def _store_root(asset: str) -> Path:
    cfg = get_settings()
    return cfg.data_dir / "etf" if asset == "etf" else cfg.data_dir


def _meta_dir(root: Path) -> Path:
    return root / "bars" / "1d" / "_meta"


def _meta_path(root: Path, symbol: str, tag: str) -> Path:
    return _meta_dir(root) / f"{symbol}.{tag}.json"


def _tag(asset: str, adjust: str) -> str:
    return "raw" if asset == "etf" else (adjust or "raw")


@dataclass
class SyncResult:
    """单只标的的同步结果。"""

    symbol: str
    status: str  # fetched / skipped / failed
    rows: int = 0
    first_date: str = ""
    last_date: str = ""
    error: str = ""


def read_meta(root: Path, symbol: str, tag: str) -> Optional[dict]:
    path = _meta_path(root, symbol, tag)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_meta(root: Path, symbol: str, tag: str, payload: dict) -> None:
    path = _meta_path(root, symbol, tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_fresh(meta: Optional[dict]) -> bool:
    if not meta or not meta.get("complete") or not meta.get("last_date"):
        return False
    try:
        last = datetime.strptime(meta["last_date"], "%Y-%m-%d").date()
    except ValueError:
        return False
    return (date.today() - last).days <= STALE_DAYS


def _fetch_full(symbol: str, asset: str, adjust: str, end: str) -> pd.DataFrame:
    if asset == "etf":
        return fetch_etf_daily(symbol)

    import akshare as ak

    raw = ak.stock_zh_a_daily(symbol=symbol, start_date=FULL_START, end_date=end, adjust=adjust)
    df = normalize_daily(raw)
    return df[df["date"] <= pd.Timestamp(end)].reset_index(drop=True)


def sync_symbols(
    symbols: Iterable[str],
    *,
    asset: str = "stock",
    adjust: str = "qfq",
    end: Optional[str] = None,
    delay: float = 0.2,
    retries: int = 3,
    force: bool = False,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> pd.DataFrame:
    """批量抓取全历史并落盘，返回每只标的的同步结果。

    :param asset: ``stock`` 个股 / ``etf`` 基金。
    :param adjust: 个股复权方式，默认 ``qfq``。
    :param delay: 每次联网请求后的休眠秒数，避免被数据源限流。
    :param retries: 单只失败重试次数（指数退避 1s/2s/4s）。
    :param force: 忽略清单强制重抓。
    :param progress: 进度回调 ``(已完成, 总数, 当前标的)``。
    """
    cfg = get_settings()
    end_date = end or date.today().strftime("%Y%m%d")
    root = _store_root(asset)
    store = ParquetStore(root)
    tag = _tag(asset, adjust)
    codes = list(symbols)
    total = len(codes)
    results: list[SyncResult] = []

    for index, symbol in enumerate(codes, start=1):
        if progress is not None:
            progress(index, total, symbol)

        if not force and _is_fresh(read_meta(root, symbol, tag)):
            meta = read_meta(root, symbol, tag) or {}
            results.append(
                SyncResult(
                    symbol=symbol,
                    status="skipped",
                    rows=int(meta.get("rows", 0)),
                    first_date=str(meta.get("first_date", "")),
                    last_date=str(meta.get("last_date", "")),
                )
            )
            continue

        error = ""
        for attempt in range(retries):
            try:
                df = _fetch_full(symbol, asset, adjust, end_date)
                if len(df) == 0:
                    raise ValueError("返回空数据")
                store.save(symbol, df, adjust="" if asset == "etf" else adjust)
                first = f"{df['date'].min():%Y-%m-%d}"
                last = f"{df['date'].max():%Y-%m-%d}"
                write_meta(
                    root,
                    symbol,
                    tag,
                    {
                        "symbol": symbol,
                        "asset": asset,
                        "adjust": adjust,
                        "rows": int(len(df)),
                        "first_date": first,
                        "last_date": last,
                        "fetched_at": datetime.now().isoformat(timespec="seconds"),
                        "complete": True,
                    },
                )
                results.append(
                    SyncResult(symbol=symbol, status="fetched", rows=len(df), first_date=first, last_date=last)
                )
                error = ""
                break
            except Exception as exc:  # noqa: BLE001
                error = str(exc)[:160]
                if attempt < retries - 1:
                    time.sleep(2**attempt)
        else:
            results.append(SyncResult(symbol=symbol, status="failed", error=error))

        if delay > 0:
            time.sleep(delay)

    return pd.DataFrame([asdict(r) for r in results])


def coverage_summary(asset: str = "stock", adjust: str = "qfq") -> pd.DataFrame:
    """统计缓存覆盖情况：按上市年份分组的标的数与最新日期。"""
    root = _store_root(asset)
    tag = _tag(asset, adjust)
    meta_root = _meta_dir(root)
    rows = []
    if meta_root.exists():
        for path in sorted(meta_root.glob(f"*.{tag}.json")):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rows.append(meta)
    if not rows:
        return pd.DataFrame(columns=["上市年份", "标的数", "累计K线", "最新日期"])

    frame = pd.DataFrame(rows)
    frame["上市年份"] = pd.to_datetime(frame["first_date"]).dt.year
    return (
        frame.groupby("上市年份")
        .agg(标的数=("symbol", "size"), 累计K线=("rows", "sum"), 最新日期=("last_date", "max"))
        .reset_index()
    )
