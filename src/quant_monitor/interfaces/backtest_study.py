"""冻结研究回测的 CLI 装配与可审计 HTML 输出。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from ..application.backtest_study import BacktestStudyService, fingerprint
from ..application.ports import ControlPlaneRepository
from ..domain.control_plane import BacktestRunRecord
from ..domain.models import Instrument, InstrumentType
from ..infrastructure.frozen_history import FrozenCSVHistoryRepository
from ..infrastructure.strategy_catalog import StrategyCatalog
from .site_navigation import ASSET_VERSION, build_site_header

LABELS = {
    "selected": "按前期规则选出（以验证状态为准）",
    "previous_v01": "原 v0.1：20% 底仓 + 20% 波段",
    "reference_870_900": "8.70 限价 / 盈利 0.30 / 风险 0.20",
    "buy_hold_40": "初始 40% 买入持有",
    "buy_hold_100": "近满仓买入持有",
    "selected_with_core": "选出规则 + 原均线退出底仓",
    "hindsight_best": "全期事后最佳（不可据此选参）",
    "matched_exposure_hold": "近似匹配平均仓位的买入持有",
}
PERIODS = {"train": "训练", "validation": "验证", "holdout": "留出", "full": "全期"}


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(item)}</td>" for item in row) + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap" tabindex="0"><table>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def build_study_report(packet: dict[str, Any], json_name: str) -> str:
    """每组结果都保留；展示失败与完整成交记录。"""
    spec = packet["specification"]
    selection = packet["selection"]
    status = "通过前期门槛，仍待前瞻验证" if selection["validation_passed"] else (
        "未通过前期门槛：选出项仅用于失败诊断"
    )
    sections = []
    for period, period_label in PERIODS.items():
        rows = []
        for key, result in packet["comparisons"].items():
            metrics = result[period]["metrics"]
            win = metrics["win_rate"]
            rows.append([
                LABELS[key], f'{metrics["total_return"]:+.2%}',
                f'{metrics["max_drawdown"]:.2%}',
                f'{metrics["average_weight"]:.2%}',
                str(metrics["completed_rounds"]),
                "—" if win is None else f"{win:.1%}",
                f'{metrics["fees_yuan"]:.2f}',
                f'{metrics["net_dividends_yuan"]:.2f}',
            ])
        table = _table(
            [
                "规则", "净收益", "最大回撤", "平均仓位", "平仓轮次",
                "胜率", "费用/元", "税后股息/元",
            ],
            rows,
        )
        sections.append(f"<details {'open' if period == 'full' else ''}>"
                        f"<summary>{period_label}比较</summary>{table}</details>")
    grid_rows = []
    for key in packet["candidates"]:
        metrics = packet["scores"]["full"][key]
        grid_rows.append(
            [key] + [
                f'{packet["scores"][period][key]["total_return"]:+.2%}'
                for period in PERIODS
            ] + [
                f'{metrics["max_drawdown"]:.2%}',
                f'{metrics["average_weight"]:.2%}', str(metrics["completed_rounds"]),
            ],
        )
    grid = _table(
        ["参数 ID", "训练", "验证", "留出", "全期", "全期回撤", "平均仓位", "轮次"],
        grid_rows,
    )
    ledgers = []
    for key, result in packet["comparisons"].items():
        rows = [
            [
                fill["trading_date"], "买" if fill["side"] == "buy" else "卖",
                "底仓" if fill["sleeve"] == "core" else "波段/持有",
                str(fill["quantity"]), f'{fill["price"]:.2f}',
                f'{fill["fee"]:.2f}', fill["reason"],
                "—" if fill["net_pnl"] is None else f'{fill["net_pnl"]:+.2f}',
            ]
            for fill in result["full"]["fills"]
        ]
        ledger = _table(
            [
                "日期", "方向", "子仓", "股数", "成交价",
                "费用/元", "原因", "本轮净盈亏/元",
            ],
            rows,
        )
        ledgers.append(f"<details><summary>{LABELS[key]}：全期逐笔成交</summary>"
                       f"{ledger}</details>")
    limitations = "".join(f"<li>{escape(item)}</li>" for item in spec["limitations"])
    parameters = escape(json.dumps(
        selection["parameters"], ensure_ascii=False, indent=2,
    ))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(spec["name"])}一年波段回测 · Quant</title>
<link rel="stylesheet" href="../../../docs/assets/docs.css?v={ASSET_VERSION}">
<style>
main{{max-width:1180px;margin:auto;padding:24px 20px}}
details{{margin:18px 0;border:1px solid #ccd5dd;border-radius:10px;padding:14px}}
summary{{font-weight:650;cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
td,th{{white-space:nowrap}}.table-wrap{{max-width:100%;overflow:auto}}
.notice{{background:#fff4d9;color:#604400;padding:18px;border-radius:10px}}
</style></head><body>
{build_site_header("../../../", "strategy")}
<main><p>策略与回测 / {escape(spec["symbol"])} / 一年波段比较</p>
<h1>{escape(spec["name"])}：一年波段资金回测</h1>
<p>{spec["start"]} 至 {spec["end"]} · 模拟资金 {spec["initial_cash_yuan"]:,.0f} 元
 · 模型 v{escape(spec["model_version"])} · 草稿，未启用，未发送通知</p>
<p class="notice">{status}。诊断/候选：{escape(selection["selected_id"])}。
历史收益不代表未来表现；全期走势事前已看过，时间留出不是盲测。</p>
<p><a href="../../../{escape(spec["method_path"])}">
冻结方法与验收规则</a>
 · <a href="{escape(json_name)}">完整结果、参数、现金权益与成交 JSON</a></p>
<p>仓位是模拟账户占比；低回撤必须结合平均仓位阅读。成交遵守整手、T+1、
最低佣金、印花税和限价穿透；各样本段独立起算并计末日清算成本。</p>
{''.join(sections)}
<details><summary>全部候选参数与分段收益</summary>{grid}</details>
<details><summary>冻结选出项参数</summary><pre>{parameters}</pre></details>
{''.join(ledgers)}
<h2>局限与失效边界</h2><ul>{limitations}</ul>
<p>研究材料，不构成投资建议或自动交易指令。</p>
</main><script src="../../../docs/assets/navigation.js?v={ASSET_VERSION}"></script>
</body></html>"""


def run_study(
    root: Path,
    path: Path,
    data_dir: Path,
    control: ControlPlaneRepository,
    catalog: StrategyCatalog,
) -> Path:
    """装配冻结仓储、登记运行，并写出结果与报告。"""
    specification = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "study_id", "symbol", "name", "exchange", "model_id", "model_version",
        "history_path", "history_sha256",
    }
    if not isinstance(specification, dict) or not required <= specification.keys():
        raise ValueError("冻结研究规格必须是对象，并包含身份、模型及行情来源字段")
    study_id = str(specification["study_id"])
    symbol = str(specification["symbol"])
    if (
        not re.fullmatch(r"[a-zA-Z0-9_-]+", study_id)
        or not re.fullmatch(r"\d{6}", symbol)
    ):
        raise ValueError("研究 ID 或证券代码格式无效")
    record = catalog.record(study_id)
    if not record.applies_to(symbol) or (
        record.parameters_fingerprint != fingerprint(specification)
        or record.backtest_model_id != specification["model_id"]
        or record.backtest_model_version != specification["model_version"]
    ):
        raise ValueError("研究规格与策略目录的模型或参数指纹不一致")
    instrument = Instrument(
        symbol, specification["name"], specification["exchange"],
        InstrumentType.STOCK, (), "", "", 500, enabled=False,
    )
    started_at = datetime.now().astimezone()
    run_id = f"{study_id}-{started_at:%Y%m%dT%H%M%S%f}"
    directory = data_dir / "backtests" / symbol
    json_path = directory / f"{run_id}.json"
    html_path = directory / f"{run_id}.html"
    pending = BacktestRunRecord(
        run_id, study_id, symbol, started_at, None, "running",
        str(html_path.relative_to(root)),
    )
    control.save_backtest(pending)
    try:
        history = FrozenCSVHistoryRepository(
            root / specification["history_path"],
            symbol, specification["history_sha256"],
        )
        packet = BacktestStudyService(history).run(instrument, specification)
        packet["generated_at"] = started_at.isoformat()
        packet["source_sha256"] = {
            str(source.relative_to(root)): hashlib.sha256(
                source.read_bytes(),
            ).hexdigest()
            for source in (
                root / "src/quant_monitor/domain/backtesting/swing.py",
                root / "src/quant_monitor/application/backtest_study.py",
                root / "src/quant_monitor/infrastructure/frozen_history.py",
            )
        }
        directory.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(
                packet, ensure_ascii=False, indent=2, default=str, allow_nan=False,
            ),
            encoding="utf-8",
        )
        html_path.write_text(
            build_study_report(packet, json_path.name), encoding="utf-8",
        )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        control.save_backtest(replace(
            pending, status="failed", completed_at=datetime.now().astimezone(),
            error=str(error),
        ))
        raise ValueError(f"冻结研究回测失败：{error}") from error
    metrics = packet["comparisons"]["selected"]["full"]["metrics"]
    control.save_backtest(replace(
        pending, status="completed", completed_at=datetime.now().astimezone(),
        total_return=metrics["total_return"], max_drawdown=metrics["max_drawdown"],
        trade_count=metrics["trade_count"],
    ))
    return html_path
