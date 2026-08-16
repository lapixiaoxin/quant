"""公开指数估值页面适配器。"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from ..domain.models import ValuationObservation
from .market_data import DataSourceError


class LixingerIndexValuationProvider:
    """读取理杏仁公开页面脚本中的逐日指数估值。"""

    name = "理杏仁公开指数估值页面"
    page_url_template = (
        "https://www.lixinger.com/equity/index/detail/"
        "{exchange}/{index_code}/{ticker_id}/fundamental/valuation/dyr"
    )

    def __init__(self, timeout: float = 20.0, retries: int = 2) -> None:
        self.timeout = timeout
        self.retries = retries

    def fetch(
        self,
        *,
        exchange: str,
        index_code: str,
        ticker_id: int,
    ) -> tuple[ValuationObservation, ...]:
        page_url = self.page_url_template.format(
            exchange=exchange,
            index_code=index_code,
            ticker_id=ticker_id,
        )
        script_url = f"{page_url}.js"
        request = urllib.request.Request(
            script_url,
            headers={
                "Accept": "application/javascript,text/javascript,*/*",
                "User-Agent": "Mozilla/5.0 QuantMonitor/0.11",
            },
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout,
                ) as response:
                    script = response.read().decode("utf-8")
                return self.parse(
                    script,
                    index_code=index_code,
                    source_url=page_url,
                )
            except (OSError, UnicodeError, ValueError) as error:
                last_error = error
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        raise DataSourceError(f"指数估值请求重试后仍失败：{last_error}")

    @classmethod
    def parse(
        cls,
        script: str,
        *,
        index_code: str,
        source_url: str,
    ) -> tuple[ValuationObservation, ...]:
        prefix = "window.pageData = "
        if not script.startswith(prefix):
            raise ValueError("指数估值脚本缺少 window.pageData")
        try:
            page_data = json.loads(script[len(prefix) :].rstrip(";\n "))
        except json.JSONDecodeError as error:
            raise ValueError("指数估值脚本中的 pageData 不是有效 JSON") from error
        chart = page_data.get("priceMetricsChartInfo")
        if not isinstance(chart, dict):
            raise ValueError("指数估值脚本缺少 priceMetricsChartInfo")
        history_window = str(chart.get("granularity", "")).strip()
        if history_window not in {"y3", "y5", "y10", "fs"}:
            raise ValueError(f"不支持的估值历史窗口 {history_window!r}")
        records = chart.get("priceMetricsList")
        if not isinstance(records, list) or not records:
            raise ValueError("指数估值脚本没有逐日估值")

        observations: list[ValuationObservation] = []
        china_tz = ZoneInfo("Asia/Shanghai")
        for position, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(f"逐日估值第 {position} 项不是对象")
            try:
                raw_date = str(record["date"]).replace("Z", "+00:00")
                observation_date = (
                    datetime.fromisoformat(raw_date)
                    .astimezone(china_tz)
                    .date()
                )
                value = float(record["dyr"]["mcw"])
                statistics = record["statistics"]["dyr"]["mcw"]
                percentile = float(statistics["cvpos"])
                q20 = float(statistics["q2v"])
                q50 = float(statistics["q5v"])
                q80 = float(statistics["q8v"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"逐日估值第 {position} 项字段不完整"
                ) from error
            if not (
                0 <= percentile <= 1
                and value >= 0
                and 0 <= q20 <= q50 <= q80
            ):
                raise ValueError(
                    f"{observation_date} 的股息率或分位字段越界"
                )
            observations.append(
                ValuationObservation(
                    valuation_symbol=index_code,
                    observation_date=observation_date,
                    metric="dividend_yield",
                    weighting="market_cap_weighted",
                    history_window=history_window,
                    value=value,
                    percentile=percentile,
                    percentile_20_value=q20,
                    percentile_50_value=q50,
                    percentile_80_value=q80,
                    source=cls.name,
                    source_url=source_url,
                )
            )
        observations.sort(key=lambda item: item.observation_date)
        dates = [item.observation_date for item in observations]
        if len(dates) != len(set(dates)):
            raise ValueError("指数估值脚本包含重复交易日")
        return tuple(observations)
