"""资金配置研究的全部方案、分段结果及账本展示。"""

from __future__ import annotations

from html import escape
from typing import Any

from .site_navigation import ASSET_VERSION, build_site_header


def build_capital_report(packet: dict[str, Any], json_name: str) -> str:
    """不按收益隐藏方案；压力结果与正常结果同屏展示。"""
    from .backtest_study import _table

    spec = packet["specification"]
    configs = spec["configurations"]
    reference_label = next(
        config["label"] for config in configs
        if config["id"] == spec["reference_configuration"]
    )
    rows, period_rows, ledgers = [], [], []
    for config in configs:
        key, label = config["id"], config["label"]
        full = packet["comparisons"][key]["full"]
        metrics = full["metrics"]
        stress = packet["slippage_stress"][key]["full"]["metrics"]
        rows.append([
            label, f'{metrics["net_profit_yuan"]:+,.2f}',
            f'{metrics["total_return"]:+.2%}', f'{metrics["annualized_return"]:+.2%}',
            f'{metrics["max_drawdown"]:.2%}',
            f'{metrics["annualized_volatility"]:.2%}',
            f'{metrics["average_weight"]:.1%} / {metrics["max_weight"]:.1%}',
            str(metrics["completed_rounds"]), f'{metrics["fees_yuan"]:.2f}',
            f'{metrics["net_dividends_yuan"]:.2f}',
            f'{stress["total_return"]:+.2%}',
            f'{metrics["blocked_sale_shock_19pct"]:.1%}',
        ])
        period_rows.append([label] + [
            f'{packet["comparisons"][key][period]["metrics"]["total_return"]:+.2%}'
            for period in ("train", "validation", "holdout")
        ])
        orders = _table(
            ["子账户", "初始预算/元", "首次成交", "股数", "价格", "计划止损损失/元"],
            [
                [
                    name, f'{order["budget_yuan"]:,.0f}',
                    (
                        order["first_buy"]["trading_date"]
                        if order["first_buy"] else "未成交"
                    ),
                    str(order["first_buy"]["quantity"]) if order["first_buy"] else "0",
                    (
                        f'{order["first_buy"]["price"]:.2f}'
                        if order["first_buy"] else "—"
                    ),
                    (
                        "未成交" if order["first_buy"] is None else
                        "未设止损" if order["first_buy_planned_loss_yuan"] is None else
                        f'{order["first_buy_planned_loss_yuan"]:.2f}'
                    ),
                ]
                for name, order in full["initial_orders"].items()
            ],
        )
        ledger = _table(
            [
                "日期", "子账户", "买卖", "股数", "价格/元",
                "费用/元", "原因", "净盈亏/元",
            ],
            [
                [
                    fill["trading_date"], fill["sleeve"],
                    "买" if fill["side"] == "buy" else "卖",
                    str(fill["quantity"]), f'{fill["price"]:.2f}',
                    f'{fill["fee"]:.2f}', fill["reason"],
                    "—" if fill["net_pnl"] is None else f'{fill["net_pnl"]:+.2f}',
                ]
                for fill in full["fills"]
            ],
        )
        ledgers.append(
            f"<details><summary>{escape(label)}：资金与完整成交</summary>"
            f"{orders}{ledger}</details>"
        )
    table = _table(
        [
            "方案", "净利润/元", "区间收益", "折算年化", "最大回撤", "年化波动",
            "平均/收盘峰值仓位", "平仓批数", "费用/元", "税后股息/元",
            "2分滑点区间收益", "19%股价冲击估算",
        ],
        rows,
    )
    periods = _table(["方案", "前116日", "中60日", "后65日"], period_rows)
    limits = "".join(f"<li>{escape(item)}</li>" for item in spec["limitations"])
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(spec["name"])}2万元资金配置比较 · Quant</title>
<link rel="stylesheet" href="../../../docs/assets/docs.css?v={ASSET_VERSION}">
<style>
main{{max-width:1180px;margin:auto;padding:24px 20px}}
details{{margin:18px 0;border:1px solid #ccd5dd;border-radius:10px;padding:14px}}
summary{{font-weight:650;cursor:pointer}}td,th{{white-space:nowrap}}
.table-wrap{{max-width:100%;overflow:auto}}
.notice{{background:#fff4d9;color:#604400;padding:18px;border-radius:10px}}
</style></head><body>
{build_site_header("../../../", "strategy")}
<main><p>策略与回测 / {escape(spec["symbol"])} / 资金配置比较</p>
<h1>{escape(spec["name"])}：2万元资金配置比较</h1>
<p>{spec["start"]} 至 {spec["end"]} · {spec["initial_cash_yuan"]:,.0f} 元
· {len(configs)}组冻结规则 · 草稿，待前瞻验证</p>
<p class="notice">这是看过走势后的资金敏感性研究。提高仓位会同时放大盈亏；
历史超过20%不能证明未来能实现20%。不以本轮最高收益自动选择配置。</p>
<p><a href="../../../{escape(spec["method_path"])}">冻结方法</a> ·
<a href="{escape(json_name)}">全部分账、权益、参数与结果 JSON</a></p>
<p>策略运行索引展示“{escape(reference_label)}”的对照收益；
各资金配置的收益与风险分别列在下表，不以单个数字代表全部方案。</p>
<p>各子账户独立滚存盈亏；保留现金不参与补亏，无杠杆。百分比是初始预算，
实际仓位会漂移。买入遵守100股整手、最低5元佣金、T+1及1分限价穿透。
年化按全期首末日期都包含的日历天数折算，季度不年化。</p>
{table}
<p>19%冲击是假设在收盘峰值仓位下，股价连续下跌且无法卖出时的近似组合损失；
不代表发生概率、回测回撤或最大损失上限。10%冲击与压力账本详见JSON。</p>
<details open><summary>固定规则的分段稳定性</summary>{periods}
<p>每段独立起算并清算；全期连续运行，分段收益不能相加。
分段均已被观察，不是真正的样本外检验。</p></details>
{''.join(ledgers)}
<h2>局限与失效边界</h2><ul>{limits}</ul>
<p>研究材料，不构成投资建议或自动交易指令。</p>
</main><script src="../../../docs/assets/navigation.js?v={ASSET_VERSION}"></script>
</body></html>"""
