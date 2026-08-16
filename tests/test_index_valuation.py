from __future__ import annotations

import json
import unittest
from datetime import date

from quant_monitor.infrastructure.index_valuation import (
    LixingerIndexValuationProvider,
)


def script(records: list[dict], granularity: str = "y3") -> str:
    payload = {
        "priceMetricsChartInfo": {
            "granularity": granularity,
            "priceMetricsList": records,
        }
    }
    return "window.pageData = " + json.dumps(payload)


class LixingerIndexValuationProviderTest(unittest.TestCase):
    def test_parses_china_trading_date_and_sorts_rows(self) -> None:
        records = [
            {
                "date": "2026-08-13T16:00:00.000Z",
                "dyr": {"mcw": 0.0433},
                "statistics": {
                    "dyr": {
                        "mcw": {
                            "cvpos": 0.1157,
                            "q2v": 0.0443,
                            "q5v": 0.0529,
                            "q8v": 0.0662,
                        }
                    }
                },
            },
            {
                "date": "2026-08-12T16:00:00.000Z",
                "dyr": {"mcw": 0.0434},
                "statistics": {
                    "dyr": {
                        "mcw": {
                            "cvpos": 0.1198,
                            "q2v": 0.0444,
                            "q5v": 0.0529,
                            "q8v": 0.0662,
                        }
                    }
                },
            },
        ]

        observations = LixingerIndexValuationProvider.parse(
            script(records),
            index_code="000151",
            source_url="https://example.com",
        )

        self.assertEqual(
            [item.observation_date for item in observations],
            [date(2026, 8, 13), date(2026, 8, 14)],
        )
        self.assertEqual(observations[-1].value, 0.0433)
        self.assertEqual(observations[-1].percentile, 0.1157)
        self.assertEqual(observations[-1].history_window, "y3")

    def test_rejects_missing_point_in_time_statistics(self) -> None:
        invalid = [
            {
                "date": "2026-08-13T16:00:00.000Z",
                "dyr": {"mcw": 0.0433},
            }
        ]

        with self.assertRaisesRegex(ValueError, "字段不完整"):
            LixingerIndexValuationProvider.parse(
                script(invalid),
                index_code="000151",
                source_url="https://example.com",
            )

    def test_rejects_unknown_history_window(self) -> None:
        with self.assertRaisesRegex(ValueError, "历史窗口"):
            LixingerIndexValuationProvider.parse(
                script([{}], granularity="month"),
                index_code="000151",
                source_url="https://example.com",
            )


if __name__ == "__main__":
    unittest.main()
