"""固定资金方案的事后敏感性比较；不选参、不启用策略。"""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import date
from typing import Any

from ..domain.backtesting.capital import combine_sleeves, prior_holding_dates
from ..domain.backtesting.swing import (
    CashDividend,
    ExecutionCosts,
    PriceSwingModel,
    SwingResult,
    simulate_swing,
)
from ..domain.models import Instrument
from .backtest_study import _packet, fingerprint
from .ports import MarketHistoryRepository


class CapitalStudyService:
    """所有子账户复用同一执行模型，保留逐日现金与独立盈亏账本。"""

    def __init__(self, history: MarketHistoryRepository) -> None:
        self._history = history

    def run(
        self, instrument: Instrument, specification: dict[str, Any],
    ) -> dict[str, Any]:
        spec = specification
        if spec.get("study_schema_version") != 2:
            raise ValueError("资金研究仅支持 study_schema_version=2")
        model = PriceSwingModel()
        if (
            spec.get("model_id") != model.model_id
            or spec.get("model_version") != model.model_version
        ):
            raise ValueError("资金研究的冻结执行模型不一致")
        names = (
            "start", "train_end", "validation_start", "validation_end",
            "holdout_start", "end",
        )
        dates = [date.fromisoformat(spec[name]) for name in names]
        if dates != sorted(set(dates)):
            raise ValueError("资金研究分段日期必须严格按时间分离")
        start, train_end, validation_start, validation_end, holdout_start, end = dates
        periods = {
            "full": (start, end), "train": (start, train_end),
            "validation": (validation_start, validation_end),
            "holdout": (holdout_start, end),
        }
        bars = self._history.load_bars(instrument.symbol, end_date=end)
        trading_dates = {bar.trading_date for bar in bars}
        if not bars or bars[-1].trading_date != end or not set(dates) <= trading_dates:
            raise ValueError("冻结行情未覆盖资金研究的所有分段端点")
        cash = float(spec["initial_cash_yuan"])
        if not math.isfinite(cash) or cash <= 0:
            raise ValueError("总预算必须是有限正数")
        components = spec["components"]
        for parameters in components.values():
            model.validate_parameters(parameters)
            if parameters.get("core_weight", 0):
                raise ValueError("资金研究必须显式分账，不允许子账户隐含底仓")
        configurations = spec["configurations"]
        ids = [item["id"] for item in configurations]
        if not 1 <= len(ids) <= 30 or len(set(ids)) != len(ids):
            raise ValueError("资金方案必须包含 1 至 30 个唯一 ID")
        if spec["reference_configuration"] not in ids:
            raise ValueError("研究索引引用了不存在的资金方案")
        for config in configurations:
            seen: set[str] = set()
            total = 0.0
            for sleeve in config["sleeves"]:
                key, fraction = sleeve["id"], sleeve["fraction"]
                if (
                    key in seen or sleeve["component"] not in components
                    or not math.isfinite(fraction) or not 0 < fraction <= 1
                    or (
                        sleeve.get("requires_previous_holding") is not None
                        and sleeve["requires_previous_holding"] not in seen
                    )
                ):
                    raise ValueError("子账户预算、身份或前日依赖无效")
                seen.add(key)
                total += fraction
            if not seen or total > 1 + 1e-9:
                raise ValueError("子账户预算必须非空且合计不超过总资金")
        actions = tuple(
            CashDividend(
                date.fromisoformat(item["ex_date"]), item["per_share"], item["source"],
            )
            for item in spec["dividends"]
        )
        costs = ExecutionCosts(**spec["costs"])

        def run(
            config: dict[str, Any], period: str, execution_costs: ExecutionCosts,
        ) -> dict[str, Any]:
            first, last = periods[period]
            results: dict[str, SwingResult] = {}
            budgets: dict[str, float] = {}
            orders = {}
            for sleeve in config["sleeves"]:
                key = sleeve["id"]
                budgets[key] = cash * sleeve["fraction"]
                parameters = components[sleeve["component"]]
                dependency = sleeve.get("requires_previous_holding")
                allowed = (
                    prior_holding_dates(results[dependency]) if dependency else None
                )
                results[key] = simulate_swing(
                    instrument, bars, first, last, parameters,
                    dividends=actions, costs=execution_costs,
                    initial_cash=budgets[key], allowed_entry_dates=allowed,
                )
                buy = next(
                    (fill for fill in results[key].fills if fill.side == "buy"), None,
                )
                risk = None
                if buy and parameters["mode"] != "hold":
                    stop = max(0.01, buy.price - parameters["stop"])
                    risk = buy.quantity * (
                        buy.price - stop + execution_costs.slippage_yuan
                    ) + buy.fee + execution_costs.fee(buy.quantity, stop, sell=True)
                orders[key] = {
                    "budget_yuan": budgets[key],
                    "first_buy": None if buy is None else {
                        **asdict(buy), "trading_date": buy.trading_date.isoformat(),
                    },
                    "first_buy_planned_loss_yuan": risk,
                }
            result = combine_sleeves(results, budgets, bars, cash)
            packet = _packet(result)
            calendar_days = (last - first).days + 1
            packet["metrics"]["calendar_days"] = calendar_days
            packet["metrics"]["annualized_return"] = (
                (1 + result.metrics["total_return"]) ** (365.25 / calendar_days) - 1
                if period == "full" else None
            )
            packet["sleeves"] = {key: _packet(value) for key, value in results.items()}
            packet["initial_orders"] = orders
            return packet

        comparisons = {
            config["id"]: {period: run(config, period, costs) for period in periods}
            for config in configurations
        }
        stress_costs = ExecutionCosts(**{**asdict(costs), "slippage_yuan": 0.02})
        stress = {
            config["id"]: {
                period: run(config, period, stress_costs) for period in periods
            }
            for config in configurations
        }
        return {
            "study_schema_version": 2, "specification": spec,
            "specification_fingerprint": fingerprint(spec),
            "status": "research_only_pending",
            "comparisons": comparisons, "slippage_stress": stress,
        }
