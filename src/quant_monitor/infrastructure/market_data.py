"""东方财富、腾讯行情适配器及自动降级组合。"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from ..domain.models import DailyBar, Instrument, MarketBundle, MarketQuote


class DataSourceError(RuntimeError):
    """行情源不可用或返回数据不完整。"""


class EastmoneyProvider:
    """东方财富公开行情接口适配器。"""

    name = "东方财富公开行情接口"
    quote_url = "https://push2.eastmoney.com/api/qt/stock/get"
    history_url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self, timeout: float = 12.0, retries: int = 2) -> None:
        self.timeout = timeout
        self.retries = retries

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{url}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 QuantMonitor/0.3",
            },
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                if payload.get("data") is None:
                    raise DataSourceError(f"{url} 返回空数据")
                return payload
            except (OSError, ValueError, DataSourceError) as error:
                last_error = error
                if attempt < self.retries:
                    time.sleep(0.4 * (attempt + 1))
        raise DataSourceError(f"请求重试后仍失败：{last_error}")

    def get_quote(self, instrument: Instrument) -> MarketQuote:
        fields = ",".join(
            [
                "f43",
                "f44",
                "f45",
                "f46",
                "f47",
                "f48",
                "f57",
                "f58",
                "f59",
                "f60",
                "f116",
                "f117",
                "f170",
                "f171",
            ]
        )
        data = self._get_json(
            self.quote_url,
            {"secid": instrument.secid, "fields": fields, "invt": "2"},
        )["data"]
        precision = int(data.get("f59") or 3)
        scale = 10**precision

        def price(field: str) -> float | None:
            value = data.get(field)
            return None if value in (None, "-") else float(value) / scale

        def percent(field: str) -> float | None:
            value = data.get(field)
            return None if value in (None, "-") else float(value) / 100

        return MarketQuote(
            symbol=str(data.get("f57") or instrument.symbol),
            name=str(data.get("f58") or instrument.name),
            price=price("f43"),
            high=price("f44"),
            low=price("f45"),
            open=price("f46"),
            previous_close=price("f60"),
            volume=float(data.get("f47") or 0),
            amount=float(data.get("f48") or 0),
            total_market_value=float(data.get("f116") or 0),
            circulating_market_value=float(data.get("f117") or 0),
            change_pct=percent("f170"),
            amplitude_pct=percent("f171"),
            price_precision=precision,
        )

    def get_daily_bars(
        self, instrument: Instrument, limit: int = 500
    ) -> tuple[DailyBar, ...]:
        fields2 = ",".join(
            [
                "f51",
                "f52",
                "f53",
                "f54",
                "f55",
                "f56",
                "f57",
                "f58",
                "f59",
                "f60",
                "f61",
            ]
        )
        data = self._get_json(
            self.history_url,
            {
                "secid": instrument.secid,
                "klt": "101",
                "fqt": "1",
                "lmt": str(limit),
                "end": "20500101",
                "iscca": "1",
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
                "fields2": fields2,
            },
        )["data"]
        bars: list[DailyBar] = []
        for row in data.get("klines") or []:
            parts = row.split(",")
            if len(parts) < 11:
                continue
            bars.append(
                DailyBar(
                    trading_date=date.fromisoformat(parts[0]),
                    open=float(parts[1]),
                    close=float(parts[2]),
                    high=float(parts[3]),
                    low=float(parts[4]),
                    volume=float(parts[5]),
                    amount=float(parts[6]),
                    amplitude_pct=float(parts[7]),
                    change_pct=float(parts[8]),
                    turnover_pct=float(parts[10]),
                )
            )
        if len(bars) < 20:
            raise DataSourceError(
                f"{instrument.symbol} 历史数据不足：仅 {len(bars)} 根"
            )
        return tuple(bars)

    def fetch(self, instrument: Instrument, limit: int) -> MarketBundle:
        return MarketBundle(
            quote=self.get_quote(instrument),
            bars=self.get_daily_bars(instrument, limit),
            source=self.name,
        )


class TencentProvider:
    """腾讯证券公开行情接口适配器。"""

    name = "腾讯证券公开行情接口"
    kline_url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

    def __init__(self, timeout: float = 12.0, retries: int = 2) -> None:
        self.timeout = timeout
        self.retries = retries

    @staticmethod
    def _key(instrument: Instrument) -> str:
        prefix = "sh" if instrument.exchange.upper() == "SH" else "sz"
        return f"{prefix}{instrument.symbol}"

    def _get_payload(self, instrument: Instrument, limit: int) -> dict[str, Any]:
        key = self._key(instrument)
        query = urllib.parse.urlencode({"param": f"{key},day,,,{limit},qfq"})
        request = urllib.request.Request(
            f"{self.kline_url}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 QuantMonitor/0.3",
            },
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                data = payload.get("data", {}).get(key)
                if payload.get("code") != 0 or not data:
                    raise DataSourceError(f"腾讯接口未返回 {instrument.symbol}")
                return data
            except (OSError, ValueError, DataSourceError) as error:
                last_error = error
                if attempt < self.retries:
                    time.sleep(0.4 * (attempt + 1))
        raise DataSourceError(f"腾讯接口重试后仍失败：{last_error}")

    def fetch(self, instrument: Instrument, limit: int) -> MarketBundle:
        key = self._key(instrument)
        data = self._get_payload(instrument, limit)
        values = data.get("qt", {}).get(key) or []
        if len(values) < 46:
            raise DataSourceError(f"{instrument.symbol} 实时行情字段不完整")

        def number(index: int) -> float | None:
            value = values[index] if index < len(values) else None
            return None if value in ("", None, "-") else float(value)

        transaction = str(values[35]).split("/")
        amount = (
            float(transaction[2])
            if len(transaction) >= 3 and transaction[2]
            else (number(57) or 0) * 10_000
        )
        quote = MarketQuote(
            symbol=str(values[2] or instrument.symbol),
            name=str(values[1] or instrument.name),
            price=number(3),
            high=number(33),
            low=number(34),
            open=number(5),
            previous_close=number(4),
            volume=number(6) or 0,
            amount=amount,
            total_market_value=(number(44) or 0) * 100_000_000,
            circulating_market_value=(number(45) or 0) * 100_000_000,
            change_pct=(number(32) / 100) if number(32) is not None else None,
            amplitude_pct=(number(43) / 100) if number(43) is not None else None,
            price_precision=3,
            quote_time=str(values[30]),
        )

        rows = data.get("qfqday") or data.get("day") or []
        bars: list[DailyBar] = []
        for row in rows:
            if len(row) < 6:
                continue
            open_price = float(row[1])
            close_price = float(row[2])
            high = float(row[3])
            low = float(row[4])
            previous = bars[-1].close if bars else open_price
            bars.append(
                DailyBar(
                    trading_date=date.fromisoformat(row[0]),
                    open=open_price,
                    close=close_price,
                    high=high,
                    low=low,
                    volume=float(row[5]),
                    amount=0.0,
                    amplitude_pct=(high / low - 1) * 100 if low else 0.0,
                    change_pct=(
                        (close_price / previous - 1) * 100 if previous else 0.0
                    ),
                    turnover_pct=0.0,
                )
            )
        if len(bars) < 20:
            raise DataSourceError(
                f"{instrument.symbol} 腾讯历史数据不足：仅 {len(bars)} 根"
            )
        return MarketBundle(quote=quote, bars=tuple(bars), source=self.name)


class FallbackMarketDataProvider:
    """按顺序尝试多个行情源，并汇总失败原因。"""

    def __init__(self, providers: tuple[Any, ...] | None = None) -> None:
        self._providers = providers or (EastmoneyProvider(), TencentProvider())

    def fetch(self, instrument: Instrument, limit: int) -> MarketBundle:
        errors: list[str] = []
        for provider in self._providers:
            try:
                return provider.fetch(instrument, limit)
            except DataSourceError as error:
                errors.append(f"{provider.name}：{error}")
        raise DataSourceError("所有行情源均失败；" + "；".join(errors))
