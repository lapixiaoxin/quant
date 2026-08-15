"""红利低波类 ETF 的中长线观察策略。"""

from __future__ import annotations

from typing import Any

from ...models import Instrument
from ..base import StrategyAssessment


class DividendLowVolStrategy:
    """根据回撤、均线和波动率计算红利低波关注度。"""

    strategy_id = "dividend_low_vol"
    name = "红利低波中长线观察"

    @staticmethod
    def _thresholds(
        parameters: dict[str, Any],
        profile_id: str,
    ) -> tuple[float, float, float, float, float]:
        deep_drawdown = float(parameters.get("deep_drawdown", -0.08))
        attention_drawdown = float(
            parameters.get("attention_drawdown", -0.05)
        )
        mild_drawdown = float(parameters.get("mild_drawdown", -0.03))
        near_high = float(parameters.get("near_high", -0.01))
        high_volatility = float(parameters.get("high_volatility", 0.25))
        if not deep_drawdown <= attention_drawdown <= mild_drawdown <= near_high:
            raise ValueError(f"策略画像 {profile_id} 的回撤阈值顺序无效")
        if high_volatility <= 0:
            raise ValueError(
                f"策略画像 {profile_id}.high_volatility 必须大于 0"
            )
        return (
            deep_drawdown,
            attention_drawdown,
            mild_drawdown,
            near_high,
            high_volatility,
        )

    def validate_parameters(
        self,
        parameters: dict[str, Any],
        *,
        profile_id: str,
    ) -> None:
        self._thresholds(parameters, profile_id)

    def evaluate(
        self,
        instrument: Instrument,
        metrics: dict[str, Any],
        *,
        profile_id: str = "dividend_low_vol_default",
        parameters: dict[str, Any] | None = None,
    ) -> StrategyAssessment:
        del instrument
        parameters = parameters or {}
        (
            deep_drawdown,
            attention_drawdown,
            mild_drawdown,
            near_high,
            high_volatility,
        ) = self._thresholds(parameters, profile_id)
        score = 50
        reasons: list[str] = []
        drawdown60 = metrics["drawdowns"]["from_high_60d"]
        close = metrics["latest_close"]
        ma60 = metrics["moving_averages"]["ma60"]
        ma120 = metrics["moving_averages"]["ma120"]
        volatility = metrics["risk"]["annualized_volatility_20d"]

        if drawdown60 is not None:
            if drawdown60 <= deep_drawdown:
                score += 18
                reasons.append("60日回撤达到较深区间")
            elif drawdown60 <= attention_drawdown:
                score += 12
                reasons.append("60日回撤进入关注区间")
            elif drawdown60 <= mild_drawdown:
                score += 6
                reasons.append("60日出现温和回撤")
            elif drawdown60 > near_high:
                score -= 8
                reasons.append("价格接近60日高位")

        if ma60 is not None:
            if close >= ma60:
                score += 6
                reasons.append("价格仍在60日均线上方")
            else:
                score -= 8
                reasons.append("价格位于60日均线下方")
        if ma120 is not None and close < ma120:
            score -= 12
            reasons.append("价格跌破120日均线")
        if volatility is not None and volatility > high_volatility:
            score -= 8
            reasons.append("近期波动率偏高")

        score = max(0, min(100, score))
        if score >= 68:
            level = "较适合关注"
        elif score >= 52:
            level = "可以观察"
        elif score >= 38:
            level = "保持等待"
        else:
            level = "暂不适合"
        return StrategyAssessment(
            profile_id=profile_id,
            strategy_id=self.strategy_id,
            strategy_name=self.name,
            level=level,
            score=score,
            reasons=tuple(reasons),
        )
