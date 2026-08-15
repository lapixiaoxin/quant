"""报告因子注册表：确定性能力与未来外部能力统一描述。"""

from __future__ import annotations

from .control_plane import AnalysisCycle, FactorDefinition


class FactorRegistry:
    """集中声明因子能力，报告编排不硬编码特定产品。"""

    def __init__(self, factors: tuple[FactorDefinition, ...]) -> None:
        self._factors = {item.factor_id: item for item in factors}

    @classmethod
    def default(cls) -> FactorRegistry:
        return cls(
            (
                FactorDefinition(
                    "market_snapshot",
                    "行情快照",
                    "deterministic",
                    "available",
                    "价格、涨跌、成交额和数据时间",
                ),
                FactorDefinition(
                    "moving_average",
                    "均线结构",
                    "deterministic",
                    "available",
                    "MA20、MA60、MA120 及价格距离",
                ),
                FactorDefinition(
                    "return_window",
                    "区间收益",
                    "deterministic",
                    "available",
                    "日、月、季度和近一年收益窗口",
                ),
                FactorDefinition(
                    "drawdown",
                    "回撤",
                    "deterministic",
                    "available",
                    "当前回撤和最大回撤",
                ),
                FactorDefinition(
                    "volatility",
                    "波动率",
                    "deterministic",
                    "available",
                    "近期年化波动及异常状态",
                ),
                FactorDefinition(
                    "liquidity",
                    "流动性",
                    "deterministic",
                    "available",
                    "成交量、成交额和相对活跃度",
                ),
                FactorDefinition(
                    "strategy",
                    "策略评估",
                    "strategy",
                    "available",
                    "注入当前生效策略版本、参数指纹和判断",
                ),
                FactorDefinition(
                    "policy",
                    "政策环境",
                    "external",
                    "reserved",
                    "未来由外部研究适配器提供带来源政策事件",
                ),
                FactorDefinition(
                    "sentiment",
                    "市场情绪",
                    "external",
                    "reserved",
                    "未来由情绪数据适配器提供可追溯指标",
                ),
                FactorDefinition(
                    "news",
                    "舆情事件",
                    "external",
                    "reserved",
                    "未来由新闻适配器提供去重和时间对齐事件",
                ),
            )
        )

    def get(self, factor_id: str) -> FactorDefinition:
        try:
            return self._factors[factor_id]
        except KeyError as error:
            available = "、".join(sorted(self._factors))
            raise ValueError(
                f"未知分析因子 {factor_id!r}，当前可用：{available}"
            ) from error

    def resolve(
        self,
        cycles: tuple[AnalysisCycle, ...],
        requested: tuple[str, ...] = (),
    ) -> tuple[FactorDefinition, ...]:
        if requested:
            return tuple(self.get(item) for item in dict.fromkeys(requested))
        factor_ids: list[str] = ["market_snapshot", "strategy"]
        for cycle in cycles:
            if cycle is AnalysisCycle.DAILY:
                factor_ids.extend(("return_window", "liquidity", "volatility"))
            elif cycle in {
                AnalysisCycle.MONTHLY,
                AnalysisCycle.YEARLY,
            }:
                factor_ids.extend(("return_window", "drawdown", "volatility"))
            elif cycle is AnalysisCycle.MOVING_AVERAGE:
                factor_ids.extend(("moving_average", "drawdown"))
        return tuple(self.get(item) for item in dict.fromkeys(factor_ids))

    @property
    def all(self) -> tuple[FactorDefinition, ...]:
        return tuple(self._factors[key] for key in sorted(self._factors))
