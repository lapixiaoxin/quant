"""使用本地历史库执行无未来数据泄漏的长线回测。"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..domain.backtesting import (
    AttentionScoreAllocationModel,
    BacktestMetrics,
    BacktestResult,
    BacktestSignalModel,
    BacktestSpecification,
    DividendYieldPercentileAllocationModel,
    EquityPoint,
)
from ..domain.models import DailyBar, Instrument
from ..domain.strategies import StrategyRegistry
from ..domain.strategies.etf import DividendYieldDynamicStrategy
from .ports import MarketHistoryRepository
from .strategy_catalog import StrategyCatalog


def _max_drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def _annualized_volatility(values: list[float]) -> float | None:
    returns = [
        values[index] / values[index - 1] - 1
        for index in range(1, len(values))
        if values[index - 1] != 0
    ]
    return (
        statistics.stdev(returns) * math.sqrt(242)
        if len(returns) >= 2
        else None
    )


def _metrics(
    specification: BacktestSpecification,
    equity_curve: tuple[EquityPoint, ...],
    traded_notional: float,
    trade_count: int,
    benchmark_return: float | None,
    benchmark_max_drawdown: float | None,
    benchmark_annualized_volatility: float | None,
) -> BacktestMetrics:
    equities = [item.equity for item in equity_curve]
    total_return = equities[-1] / specification.initial_cash - 1
    years = (
        equity_curve[-1].trading_date - equity_curve[0].trading_date
    ).days / 365.25
    annualized_return = (
        (1 + total_return) ** (1 / years) - 1
        if years > 0 and total_return > -1
        else None
    )
    returns = [
        equities[index] / equities[index - 1] - 1
        for index in range(1, len(equities))
        if equities[index - 1] != 0
    ]
    volatility = _annualized_volatility(equities)
    sharpe = (
        statistics.fmean(returns) / statistics.stdev(returns) * math.sqrt(242)
        if len(returns) >= 2 and statistics.stdev(returns) > 0
        else None
    )
    average_equity = statistics.fmean(equities)
    return BacktestMetrics(
        total_return=total_return,
        annualized_return=annualized_return,
        max_drawdown=_max_drawdown(equities),
        annualized_volatility=volatility,
        sharpe_ratio=sharpe,
        turnover=traded_notional / average_equity,
        trade_count=trade_count,
        benchmark_return=benchmark_return,
        benchmark_max_drawdown=benchmark_max_drawdown,
        benchmark_annualized_volatility=benchmark_annualized_volatility,
        excess_return=(
            total_return - benchmark_return
            if benchmark_return is not None
            else None
        ),
    )


def result_to_packet(result: BacktestResult) -> dict[str, Any]:
    return {
        "specification": {
            **asdict(result.specification),
            "start_date": result.specification.start_date.isoformat(),
            "end_date": result.specification.end_date.isoformat(),
        },
        "metrics": asdict(result.metrics),
        "equity_curve": [
            {
                **asdict(item),
                "trading_date": item.trading_date.isoformat(),
            }
            for item in result.equity_curve
        ],
        "warnings": list(result.warnings),
    }


class BacktestService:
    """按策略目录中的冻结模型执行可复现回测。"""

    def __init__(
        self,
        history_repository: MarketHistoryRepository,
        strategies: StrategyRegistry,
        strategy_catalog: StrategyCatalog,
    ) -> None:
        self._history = history_repository
        self._strategies = strategies
        self._catalog = strategy_catalog

    def run(
        self,
        instrument: Instrument,
        profile_parameters: dict[str, Any],
        specification: BacktestSpecification,
        *,
        strategy_record_id: str,
    ) -> BacktestResult:
        record = self._catalog.record(strategy_record_id)
        if not record.applies_to(instrument.symbol):
            raise ValueError(
                f"策略记录 {strategy_record_id} 不适用于 {instrument.symbol}"
            )
        if specification.model_id != record.backtest_model_id:
            raise ValueError("回测规格模型与策略目录不一致")
        if specification.model_version != record.backtest_model_version:
            raise ValueError("回测规格模型版本与策略目录不一致")
        if specification.parameters_fingerprint != record.parameters_fingerprint:
            raise ValueError("回测规格参数指纹与策略目录不一致")
        strategy = self._strategies.get(
            str(record.backtest_parameters.get(
                "strategy_id",
                "dividend_low_vol",
            ))
        )
        model: BacktestSignalModel
        model_warnings: tuple[str, ...] = ()
        if record.backtest_model_id == "attention_score_allocation":
            model = AttentionScoreAllocationModel(strategy)
        elif (
            record.backtest_model_id
            == "dividend_yield_percentile_allocation"
        ):
            valuation_symbol = str(
                record.backtest_parameters.get("valuation_symbol", "")
            )
            if not valuation_symbol:
                raise ValueError("动态股息率回测缺少 valuation_symbol")
            if not isinstance(strategy, DividendYieldDynamicStrategy):
                raise ValueError(
                    "动态股息率回测模型必须绑定 dividend_yield_dynamic 策略"
                )
            valuations = self._history.load_valuation_observations(
                valuation_symbol,
                metric=str(
                    record.backtest_parameters.get(
                        "valuation_metric",
                        "dividend_yield",
                    )
                ),
                weighting=str(
                    record.backtest_parameters.get(
                        "valuation_weighting",
                        "market_cap_weighted",
                    )
                ),
                history_window=str(
                    record.backtest_parameters.get(
                        "valuation_history_window",
                        "y3",
                    )
                ),
                end_date=specification.end_date,
            )
            model = DividendYieldPercentileAllocationModel(
                strategy,
                valuations,
            )
            model_warnings = (
                "基本面门禁暂以指数编制规则代理，未逐日回放盈利、现金流和分红削减",
                "价格使用前复权 ETF 日线近似含分红表现，未单列现金分红与再投资税费",
                "公开估值窗口只有三年，且 ETF 成立较晚，"
                "本次有效验证区间不足一个完整周期",
            )
        else:
            raise ValueError(
                f"未注册回测模型 {record.backtest_model_id!r}"
            )
        parameters = {
            **record.backtest_parameters,
            "profile_id": record.profile_id,
            "strategy_parameters": profile_parameters,
        }
        model.validate_parameters(parameters)
        bars = self._history.load_bars(
            instrument.symbol,
            start_date=specification.start_date,
            end_date=specification.end_date,
        )
        if len(bars) <= model.minimum_bars:
            raise ValueError(
                f"回测历史不足：{len(bars)} <= {model.minimum_bars}"
            )
        return self._simulate(
            instrument,
            tuple(bars),
            specification,
            model,
            parameters,
            warnings=model_warnings,
        )

    @staticmethod
    def _simulate(
        instrument: Instrument,
        bars: tuple[DailyBar, ...],
        specification: BacktestSpecification,
        model: BacktestSignalModel,
        parameters: dict[str, Any],
        *,
        warnings: tuple[str, ...] = (),
    ) -> BacktestResult:
        cash = specification.initial_cash
        shares = 0.0
        last_target = -1.0
        traded_notional = 0.0
        trade_count = 0
        equity_curve: list[EquityPoint] = []
        cost_rate = (
            specification.commission_bps + specification.slippage_bps
        ) / 10_000

        for index in range(model.minimum_bars, len(bars)):
            current = bars[index]
            history = bars[:index]
            signal = model.generate_signal(
                instrument,
                history,
                parameters,
            )
            equity_at_open = cash + shares * current.open
            if not math.isclose(signal.target_weight, last_target):
                desired_value = equity_at_open * signal.target_weight
                current_value = shares * current.open
                trade_value = desired_value - current_value
                if trade_value > 0:
                    trade_value = min(
                        trade_value,
                        cash / (1 + cost_rate),
                    )
                if abs(trade_value) > 1e-8:
                    cash -= trade_value
                    cash -= abs(trade_value) * cost_rate
                    shares += trade_value / current.open
                    traded_notional += abs(trade_value)
                    trade_count += 1
                last_target = signal.target_weight
            equity = cash + shares * current.close
            equity_curve.append(
                EquityPoint(
                    trading_date=current.trading_date,
                    equity=equity,
                    cash=cash,
                    position_value=shares * current.close,
                    target_weight=signal.target_weight,
                )
            )
        if not equity_curve:
            raise ValueError("回测没有生成权益曲线")
        benchmark_values = [bars[model.minimum_bars].open] + [
            item.close for item in bars[model.minimum_bars :]
        ]
        benchmark_return = (
            benchmark_values[-1] / benchmark_values[0] - 1
            if benchmark_values[0]
            else None
        )
        benchmark_max_drawdown = _max_drawdown(benchmark_values)
        benchmark_volatility = _annualized_volatility(benchmark_values)
        result = BacktestResult(
            specification=specification,
            metrics=_metrics(
                specification,
                tuple(equity_curve),
                traded_notional,
                trade_count,
                benchmark_return,
                benchmark_max_drawdown,
                benchmark_volatility,
            ),
            equity_curve=tuple(equity_curve),
            warnings=(
                "信号使用前一交易日及更早数据，在下一交易日开盘执行",
                "该目标仓位映射仅用于验证，不是线上自动交易指令",
                "结果未包含涨跌停、停牌和申赎冲击",
            )
            + warnings,
        )
        return result


def save_backtest_result(path: Path, result: BacktestResult) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result_to_packet(result), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path
