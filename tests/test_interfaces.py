from __future__ import annotations

import unittest

from quant_monitor.interfaces.dashboard import build_dashboard
from quant_monitor.interfaces.reporting import build_base_report


def packet(version: int = 4) -> dict:
    metrics = {
        "latest_trading_date": "2026-08-15",
        "latest_close": 1.25,
        "trend_state": "震荡",
        "returns": {
            "1d": 0.01,
            "5d": 0.02,
            "20d": -0.03,
            "60d": 0.05,
        },
        "moving_averages": {"ma20": 1.2, "ma60": 1.18, "ma120": 1.1},
        "drawdowns": {
            "from_high_20d": -0.03,
            "from_high_60d": -0.05,
            "from_high_120d": -0.08,
        },
        "risk": {"annualized_volatility_20d": 0.18},
    }
    value = {
        "schema_version": version,
        "as_of": "2026-08-15T14:00:00+08:00",
        "quote": {
            "price": 1.25,
            "change_pct": 0.01,
            "amount": 100_000_000,
        },
        "metrics": metrics,
        "portfolio": {
            "enabled": False,
            "shares": 0,
            "average_cost": 0,
            "planned_total_amount": 0,
        },
        "data_quality": {
            "market_source": "测试源",
            "market_timestamp": "2026-08-15 14:00",
            "history_bars": 300,
        },
        "research_plan": {
            "profile_id": "etf_core",
            "skill": "instrument-analyst",
            "sections": ["趋势", "基本面"],
            "focus": ["大类关注", "标的关注"],
            "source_priorities": ["官方来源"],
            "max_sources": 4,
            "instructions": [],
        },
        "notification_plan": {
            "policy_id": "daily",
            "enabled": True,
            "channels": ["primary"],
            "events": ["agent_report"],
            "title_template": "{symbol} 日报",
        },
    }
    instrument = {
        "symbol": "515100",
        "name": "红利<测试>",
        "exchange": "SH",
        "type": "etf",
        "strategy_profiles": ["dividend_default", "risk_guard"],
        "research_profile": "etf_core",
        "notification_policy": "daily",
        "history_days": 500,
        "enabled": True,
        "research_focus": ["标的关注"],
        "research_instructions": [],
        "tracking_index": "测试指数",
        "tracking_index_code": "000001",
    }
    assessment = {
        "profile_id": "dividend_default",
        "id": "dividend_low_vol",
        "name": "红利低波中长线观察",
        "level": "可以观察",
        "score": 62,
        "reasons": ["60日回撤进入关注区间"],
    }
    risk_assessment = {
        "profile_id": "risk_guard",
        "id": "risk_guard",
        "name": "风险约束",
        "level": "保持等待",
        "score": 48,
        "reasons": ["波动率仍需观察"],
    }
    value["instrument"] = instrument
    value["assessments"] = [assessment, risk_assessment]
    if version == 4:
        value["strategy_plan"] = [
            {
                "record_id": "strategy-v1",
                "profile_id": "dividend_default",
                "name": "测试策略",
                "version": "1.0.0",
                "lifecycle": "active",
            }
        ]
        value["analysis_plan"] = {
            "trigger": "manual",
            "cycles": ["daily", "moving_average"],
            "factor_ids": ["market_snapshot", "strategy"],
        }
        value["data_quality"]["sync_mode"] = "incremental"
    return value


class InterfaceTest(unittest.TestCase):
    def test_report_supports_current_packet(self) -> None:
        current = build_base_report(packet())

        self.assertIn("可以观察", current)
        self.assertIn("风险约束", current)
        self.assertIn("测试指数", current)
        self.assertIn("strategy-v1", current)
        self.assertIn("moving_average", current)

    def test_report_keeps_schema_v3_read_compatibility(self) -> None:
        legacy = build_base_report(packet(version=3))

        self.assertIn("可以观察", legacy)

    def test_report_rejects_old_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "schema_version=3"):
            build_base_report(packet(version=2))

    def test_dashboard_escapes_content(self) -> None:
        content = build_dashboard([packet()])

        self.assertIn("投资观察台", content)
        self.assertIn("红利&lt;测试&gt;", content)
        self.assertNotIn("红利<测试>", content)
        self.assertIn("标的关注", content)
        self.assertIn("风险约束", content)

    def test_dashboard_handles_empty_data(self) -> None:
        content = build_dashboard([])

        self.assertIn("暂无可展示的数据", content)
        self.assertIn("./quant daily", content)


if __name__ == "__main__":
    unittest.main()
