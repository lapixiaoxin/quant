"""以股息率历史分位为主锚的红利 ETF 动态研究策略。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import Instrument
from ..base import StrategyAssessment


@dataclass(frozen=True)
class DividendYieldDecision:
    """动态估值策略的确定性决策，不包含订单或买入金额。"""

    status: str
    band: str
    target_weight: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _Policy:
    minimum_history_observations: int
    expensive_percentile: float
    first_add_percentile: float
    second_add_percentile: float
    full_add_percentile: float
    minimum_weight: float
    base_weight: float
    first_add_weight: float
    second_add_weight: float
    full_weight: float
    first_add_drawdown: float
    second_add_drawdown: float
    full_add_drawdown: float
    dividend_cut_limit: float


class DividendYieldDynamicStrategy:
    """以估值分位定仓，回撤确认增配，基本面门禁防止价值陷阱。"""

    strategy_id = "dividend_yield_dynamic"
    name = "红利股息率动态配置"

    @staticmethod
    def _policy(
        parameters: dict[str, Any],
        profile_id: str,
    ) -> _Policy:
        policy = _Policy(
            minimum_history_observations=int(
                parameters.get("minimum_history_observations", 726)
            ),
            expensive_percentile=float(
                parameters.get("expensive_percentile", 0.20)
            ),
            first_add_percentile=float(
                parameters.get("first_add_percentile", 0.70)
            ),
            second_add_percentile=float(
                parameters.get("second_add_percentile", 0.85)
            ),
            full_add_percentile=float(
                parameters.get("full_add_percentile", 0.95)
            ),
            minimum_weight=float(parameters.get("minimum_weight", 0.20)),
            base_weight=float(parameters.get("base_weight", 0.30)),
            first_add_weight=float(parameters.get("first_add_weight", 0.50)),
            second_add_weight=float(
                parameters.get("second_add_weight", 0.75)
            ),
            full_weight=float(parameters.get("full_weight", 1.00)),
            first_add_drawdown=float(
                parameters.get("first_add_drawdown", -0.05)
            ),
            second_add_drawdown=float(
                parameters.get("second_add_drawdown", -0.10)
            ),
            full_add_drawdown=float(
                parameters.get("full_add_drawdown", -0.15)
            ),
            dividend_cut_limit=float(
                parameters.get("dividend_cut_limit", -0.15)
            ),
        )
        percentiles = (
            policy.expensive_percentile,
            policy.first_add_percentile,
            policy.second_add_percentile,
            policy.full_add_percentile,
        )
        if not (
            0
            <= percentiles[0]
            < percentiles[1]
            < percentiles[2]
            < percentiles[3]
            <= 1
        ):
            raise ValueError(f"策略画像 {profile_id} 的股息率分位阈值无效")
        weights = (
            policy.minimum_weight,
            policy.base_weight,
            policy.first_add_weight,
            policy.second_add_weight,
            policy.full_weight,
        )
        if not (
            0
            <= weights[0]
            <= weights[1]
            <= weights[2]
            <= weights[3]
            <= weights[4]
            <= 1
        ):
            raise ValueError(f"策略画像 {profile_id} 的研究目标仓位无效")
        if not (
            -1
            < policy.full_add_drawdown
            <= policy.second_add_drawdown
            <= policy.first_add_drawdown
            <= 0
        ):
            raise ValueError(f"策略画像 {profile_id} 的回撤确认阈值无效")
        if policy.minimum_history_observations < 242:
            raise ValueError(
                f"策略画像 {profile_id} 的估值历史至少需要 242 个观察值"
            )
        if not -1 < policy.dividend_cut_limit < 0:
            raise ValueError(
                f"策略画像 {profile_id} 的分红削减阈值必须在 -1 到 0 之间"
            )
        return policy

    def validate_parameters(
        self,
        parameters: dict[str, Any],
        *,
        profile_id: str,
    ) -> None:
        self._policy(parameters, profile_id)

    def decide(
        self,
        metrics: dict[str, Any],
        *,
        profile_id: str,
        parameters: dict[str, Any],
    ) -> DividendYieldDecision:
        """根据当期已知估值和基本面事实形成研究目标仓位。"""

        policy = self._policy(parameters, profile_id)
        valuation = metrics.get("valuation")
        if not isinstance(valuation, dict):
            return DividendYieldDecision(
                status="blocked",
                band="估值数据不足",
                target_weight=None,
                reasons=("缺少可回放的股息率估值数据",),
            )
        percentile = valuation.get("dividend_yield_percentile")
        observations = valuation.get("history_observations")
        if percentile is None or observations is None:
            return DividendYieldDecision(
                status="blocked",
                band="估值数据不足",
                target_weight=None,
                reasons=("缺少股息率历史分位或历史观察数量",),
            )
        percentile = float(percentile)
        observations = int(observations)
        if not 0 <= percentile <= 1:
            raise ValueError("股息率历史分位必须在 0 到 1 之间")
        if bool(valuation.get("stale", False)):
            return DividendYieldDecision(
                status="blocked",
                band="估值数据陈旧",
                target_weight=None,
                reasons=("股息率事实已被标记为陈旧",),
            )
        if observations < policy.minimum_history_observations:
            return DividendYieldDecision(
                status="blocked",
                band="估值历史不足",
                target_weight=None,
                reasons=(
                    "股息率历史观察不足："
                    f"{observations} < {policy.minimum_history_observations}",
                ),
            )

        fundamental = metrics.get("fundamental_guard", {})
        if not isinstance(fundamental, dict):
            fundamental = {}
        fundamental_status = str(
            fundamental.get("status", "unknown")
        ).lower()
        dividend_cut = fundamental.get("dividend_cut_pct")
        if (
            fundamental_status == "fail"
            or (
                dividend_cut is not None
                and float(dividend_cut) <= policy.dividend_cut_limit
            )
        ):
            return DividendYieldDecision(
                status="invalidated",
                band="基本面失效",
                target_weight=policy.minimum_weight,
                reasons=("分红能力或基本面门禁未通过，禁止越跌越加",),
            )

        yield_value = valuation.get("dividend_yield")
        yield_reason = (
            f"当前股息率 {float(yield_value):.2%}"
            if yield_value is not None
            else "当前股息率已核验"
        )
        percentile_reason = f"历史分位 {percentile:.2%}"
        if percentile <= policy.expensive_percentile:
            return DividendYieldDecision(
                status="eligible",
                band="估值偏贵",
                target_weight=policy.minimum_weight,
                reasons=(yield_reason, percentile_reason, "不新增动态仓位"),
            )
        if percentile < policy.first_add_percentile:
            return DividendYieldDecision(
                status="eligible",
                band="核心观察",
                target_weight=policy.base_weight,
                reasons=(yield_reason, percentile_reason, "维持核心研究仓位"),
            )
        if fundamental_status != "pass":
            return DividendYieldDecision(
                status="blocked",
                band="待补基本面",
                target_weight=None,
                reasons=(
                    yield_reason,
                    percentile_reason,
                    "估值进入关注区，但分红可持续性尚未通过门禁",
                ),
            )

        drawdown = metrics.get("drawdowns", {}).get("from_high_242d")
        if drawdown is None:
            return DividendYieldDecision(
                status="blocked",
                band="待补回撤",
                target_weight=None,
                reasons=(yield_reason, percentile_reason, "缺少 242 日回撤"),
            )
        drawdown = float(drawdown)
        if percentile >= policy.full_add_percentile:
            target = policy.full_weight
            band = "极端低估"
            if drawdown > policy.full_add_drawdown:
                target = policy.second_add_weight
                band = "极端分位待回撤确认"
        elif percentile >= policy.second_add_percentile:
            target = policy.second_add_weight
            band = "显著低估"
            if drawdown > policy.second_add_drawdown:
                target = policy.first_add_weight
                band = "显著分位待回撤确认"
        else:
            target = policy.first_add_weight
            band = "进入增配区"
            if drawdown > policy.first_add_drawdown:
                target = policy.base_weight
                band = "增配分位待回撤确认"
        return DividendYieldDecision(
            status="eligible",
            band=band,
            target_weight=target,
            reasons=(
                yield_reason,
                percentile_reason,
                f"242 日高点回撤 {drawdown:.2%}",
            ),
        )

    def evaluate(
        self,
        instrument: Instrument,
        metrics: dict[str, Any],
        *,
        profile_id: str = "dividend_yield_dynamic_v1",
        parameters: dict[str, Any] | None = None,
    ) -> StrategyAssessment:
        del instrument
        decision = self.decide(
            metrics,
            profile_id=profile_id,
            parameters=parameters or {},
        )
        if decision.status == "invalidated":
            score = 10
        elif decision.target_weight is None:
            score = 0
        else:
            score = round(decision.target_weight * 100)
        return StrategyAssessment(
            profile_id=profile_id,
            strategy_id=self.strategy_id,
            strategy_name=self.name,
            level=decision.band,
            score=score,
            reasons=decision.reasons,
        )
