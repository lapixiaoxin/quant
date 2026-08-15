"""候选池 TOML 配置读取与结构校验。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9
    import tomli as tomllib

from ..domain.control_plane import InvestmentHorizon
from ..domain.models import InstrumentType
from ..domain.selection import (
    CandidateMetadata,
    SelectionCandidate,
    SelectionRules,
    SelectionUniverse,
)


def _optional_float(values: dict[str, Any], key: str) -> float | None:
    value = values.get(key)
    return None if value in (None, "") else float(value)


def _optional_date(values: dict[str, Any], key: str) -> date | None:
    value = values.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _strings(value: object, owner: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{owner} 必须是非空字符串数组")
    return tuple(item.strip() for item in value)


def load_selection_universe(path: Path) -> SelectionUniverse:
    """从可提交 TOML 读取一个候选池。"""

    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    schema_version = int(raw.get("schema_version", 0))
    if schema_version not in {1, 2}:
        raise ValueError(
            f"候选池 schema_version 必须为 1 或 2，实际为 {schema_version}"
        )
    instrument_type = InstrumentType.parse(str(raw.get("instrument_type", "")))
    rule_values = raw.get("rules", {})
    if not isinstance(rule_values, dict):
        raise ValueError("候选池 rules 必须是对象")
    rules = SelectionRules(
        min_history_bars=int(rule_values.get("min_history_bars", 120)),
        min_average_amount_cny=float(
            rule_values.get("min_average_amount_cny", 10_000_000)
        ),
        min_fund_size_cny=_optional_float(
            rule_values,
            "min_fund_size_cny",
        ),
        max_total_fee_pct=_optional_float(
            rule_values,
            "max_total_fee_pct",
        ),
        required_metadata=_strings(
            rule_values.get("required_metadata", []),
            "rules.required_metadata",
        ),
    )
    candidate_values = raw.get("candidates", [])
    if not isinstance(candidate_values, list):
        raise ValueError("候选池 candidates 必须是数组")
    candidates: list[SelectionCandidate] = []
    for index, values in enumerate(candidate_values):
        if not isinstance(values, dict):
            raise ValueError(f"candidates[{index}] 必须是对象")
        owner = f"candidates[{index}]"
        symbol = str(values.get("symbol", "")).strip()
        name = str(values.get("name", "")).strip()
        exchange = str(values.get("exchange", "")).strip().upper()
        if not symbol or not name or exchange not in {"SH", "SZ", "BJ"}:
            raise ValueError(f"{owner} 缺少有效的 symbol、name 或 exchange")
        metadata = CandidateMetadata(
            tracking_index=str(values.get("tracking_index", "")).strip(),
            tracking_index_code=str(
                values.get("tracking_index_code", "")
            ).strip(),
            management_fee_pct=_optional_float(
                values,
                "management_fee_pct",
            ),
            custody_fee_pct=_optional_float(values, "custody_fee_pct"),
            service_fee_pct=_optional_float(values, "service_fee_pct"),
            fund_size_cny=_optional_float(values, "fund_size_cny"),
            average_amount_20d_cny=_optional_float(
                values,
                "average_amount_20d_cny",
            ),
            tracking_error_pct=_optional_float(values, "tracking_error_pct"),
            tracking_error_as_of=_optional_date(
                values,
                "tracking_error_as_of",
            ),
            inception_date=_optional_date(values, "inception_date"),
            as_of=_optional_date(values, "metadata_as_of"),
            source_urls=_strings(
                values.get("source_urls", []),
                f"{owner}.source_urls",
            ),
        )
        candidates.append(
            SelectionCandidate(
                symbol=symbol,
                name=name,
                exchange=exchange,
                instrument_type=instrument_type,
                metadata=metadata,
            )
        )
    return SelectionUniverse(
        universe_id=str(raw.get("universe_id", "")).strip(),
        name=str(raw.get("name", "")).strip(),
        objective=str(raw.get("objective", "")).strip(),
        instrument_type=instrument_type,
        history_days=int(raw.get("history_days", 500)),
        shortlist_size=int(raw.get("shortlist_size", 3)),
        rules=rules,
        candidates=tuple(candidates),
        horizon=InvestmentHorizon.parse(
            str(raw.get("horizon", "long"))
        ),
        theme=str(raw.get("theme", "general")).strip(),
        created_at=_optional_date(raw, "created_at"),
    )
