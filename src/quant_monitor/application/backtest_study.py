"""候选波段的时间顺序比较；选参不能读取留出结果。"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import asdict
from datetime import date
from typing import Any

from ..domain.backtesting.swing import (
    CashDividend,
    ExecutionCosts,
    PriceSwingModel,
    SwingResult,
    adjusted_signal_window,
    simulate_swing,
)
from ..domain.models import Instrument
from .ports import MarketHistoryRepository


def fingerprint(values: dict[str, Any]) -> str:
    """冻结输入及参数身份，不依赖文件排列。"""
    return hashlib.sha256(json.dumps(
        values, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def candidate_parameters(grid: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """展开事前冻结的有限网格，固定顺序就是同分时的次序。"""
    result = {}
    for entry, take, hold in itertools.product(
        grid["entry"], grid["take"], grid["max_hold"],
    ):
        result[f"fixed-{entry:.2f}-{take:.2f}-{hold}"] = dict(
            mode="fixed", entry=entry, take=take, stop=0.20, max_hold=hold,
            weight=0.4, risk_fraction=0.005,
        )
    for pullback, take, hold, trend in itertools.product(
        grid["pullback_atr"], grid["take_atr"], grid["max_hold"], (False, True),
    ):
        result[f"atr-{pullback:g}-{take:g}-{hold}-{int(trend)}"] = dict(
            mode="atr", pullback_atr=pullback, take_atr=take, max_hold=hold,
            trend=trend, weight=0.4, risk_fraction=0.005,
        )
    if not 1 <= len(result) <= 50:
        raise ValueError("研究网格必须包含 1 至 50 个不重复候选")
    for parameters in result.values():
        PriceSwingModel().validate_parameters(parameters)
    return result


def _rank(metrics: dict[str, Any], key: str) -> tuple[Any, ...]:
    return (
        -metrics["total_return"], -metrics["max_drawdown"],
        metrics["fees_yuan"], key,
    )


def _eligible(metrics: dict[str, Any], rounds: int) -> bool:
    return (
        metrics["total_return"] > 0 and metrics["max_drawdown"] >= -0.05
        and metrics["completed_rounds"] >= rounds
        and metrics["open_shares"] == 0
    )


def choose_candidate(
    training: dict[str, dict[str, Any]],
    validation: dict[str, dict[str, Any]],
) -> tuple[str, tuple[str, ...], bool]:
    """该函数不接收留出或全期数据，失败时也不放宽规则。"""
    ranked = sorted(training, key=lambda key: _rank(training[key], key))
    shortlist = tuple(key for key in ranked if _eligible(training[key], 3))[:3]
    passed = [key for key in shortlist if _eligible(validation[key], 2)]
    if passed:
        selected = min(passed, key=lambda key: _rank(validation[key], key))
        return selected, shortlist, True
    return (shortlist[0] if shortlist else ranked[0]), shortlist, False


def _packet(result: SwingResult) -> dict[str, Any]:
    return {
        "metrics": result.metrics,
        "diagnostics": result.diagnostics,
        "curve": [
            {**asdict(point), "trading_date": point.trading_date.isoformat()}
            for point in result.curve
        ],
        "fills": [
            {**asdict(fill), "trading_date": fill.trading_date.isoformat()}
            for fill in result.fills
        ],
    }


class BacktestStudyService:
    """隔离日常配置与研究实验，不改变任何策略启用或验证状态。"""

    def __init__(self, history: MarketHistoryRepository) -> None:
        self._history = history

    def run(
        self, instrument: Instrument, specification: dict[str, Any],
    ) -> dict[str, Any]:
        if specification.get("study_schema_version") != 1:
            raise ValueError("仅支持 study_schema_version=1")
        model = PriceSwingModel()
        if (
            specification.get("model_id") != model.model_id
            or specification.get("model_version") != model.model_version
        ):
            raise ValueError("冻结的研究模型标识或版本不一致")
        start = date.fromisoformat(specification["start"])
        train_end = date.fromisoformat(specification["train_end"])
        validation_start = date.fromisoformat(specification["validation_start"])
        validation_end = date.fromisoformat(specification["validation_end"])
        holdout_start = date.fromisoformat(specification["holdout_start"])
        end = date.fromisoformat(specification["end"])
        if not (
            start < train_end < validation_start < validation_end
            < holdout_start < end
        ):
            raise ValueError("训练、验证和留出日期必须严格按时间分离")
        bars = self._history.load_bars(instrument.symbol, end_date=end)
        if (
            not bars or bars[-1].trading_date != end
            or not any(bar.trading_date == start for bar in bars)
        ):
            raise ValueError("冻结行情未覆盖完整研究起止交易日")
        actions = tuple(
            CashDividend(
                date.fromisoformat(item["ex_date"]), item["per_share"], item["source"],
            )
            for item in specification["dividends"]
        )
        costs = ExecutionCosts(**specification["costs"])
        initial_cash = float(specification["initial_cash_yuan"])
        candidates = candidate_parameters(specification["grid"])
        periods = {
            "train": (start, train_end),
            "validation": (validation_start, validation_end),
            "holdout": (holdout_start, end),
            "full": (start, end),
        }

        def run(
            parameters: dict[str, Any], period: str, *,
            execution_costs: ExecutionCosts = costs,
            cash: float = initial_cash,
        ) -> SwingResult:
            first, last = periods[period]
            return simulate_swing(
                instrument, bars, first, last, parameters, dividends=actions,
                costs=execution_costs, initial_cash=cash,
            )

        scores: dict[str, dict[str, Any]] = {}
        for period in ("train", "validation"):
            scores[period] = {
                key: run(parameters, period).metrics
                for key, parameters in candidates.items()
            }
        selected, shortlist, validation_passed = choose_candidate(
            scores["train"], scores["validation"],
        )
        # 从这里才开始计算留出和全期；之后不得重选。
        for period in ("holdout", "full"):
            scores[period] = {
                key: run(parameters, period).metrics
                for key, parameters in candidates.items()
            }
        hindsight = min(
            candidates, key=lambda key: _rank(scores["full"][key], key),
        )
        selected_parameters = candidates[selected]
        comparison_parameters = {
            "selected": selected_parameters,
            "previous_v01": dict(
                mode="previous", weight=0.20, core_weight=0.20,
                max_hold=20, risk_fraction=0.005,
            ),
            "reference_870_900": dict(
                mode="fixed", entry=8.70, take=0.30, stop=0.20,
                weight=0.40, max_hold=20, risk_fraction=0.005,
            ),
            "buy_hold_40": dict(mode="hold", weight=0.40),
            "buy_hold_100": dict(mode="hold", weight=1.0),
            "selected_with_core": {
                **selected_parameters, "weight": 0.20, "core_weight": 0.20,
            },
            "hindsight_best": candidates[hindsight],
        }
        comparisons = {
            key: {period: _packet(run(parameters, period)) for period in periods}
            for key, parameters in comparison_parameters.items()
        }
        # 仅解释暴露；这个基准不能回流到候选筛选。
        comparisons["matched_exposure_hold"] = {
            period: _packet(run(
                dict(mode="hold", weight=max(
                    0.000001,
                    comparisons["selected"][period]["metrics"]["average_weight"],
                )),
                period,
            ))
            for period in periods
        }
        stress_costs = ExecutionCosts(**{
            **asdict(costs), "slippage_yuan": 0.02,
        })
        stress = {
            period: _packet(run(
                selected_parameters, period, execution_costs=stress_costs,
            ))
            for period in ("holdout", "full")
        }
        sizes = {
            str(int(cash)): run(selected_parameters, "full", cash=cash).metrics
            for cash in (20_000.0, 100_000.0, 500_000.0)
        }
        return {
            "study_schema_version": 1,
            "specification": specification,
            "specification_fingerprint": fingerprint(specification),
            "status": "research_only_pending",
            "selection": {
                "selected_id": selected, "shortlist": shortlist,
                "validation_passed": validation_passed,
                "holdout_passed_basic_threshold": _eligible(
                    scores["holdout"][selected], 2,
                ),
                "hindsight_best_id": hindsight,
                "parameters": selected_parameters,
            },
            "candidates": candidates, "scores": scores,
            "comparisons": comparisons, "slippage_stress": stress,
            "capital_sensitivity": sizes,
            "latest_signal": asdict(model.generate_signal(
                instrument,
                # 使用同一因果除息窗口，不依赖期末 qfq 文件。
                adjusted_signal_window(bars, actions),
                selected_parameters,
            )),
        }
