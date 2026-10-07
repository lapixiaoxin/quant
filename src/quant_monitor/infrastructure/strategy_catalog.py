"""版本化策略目录读取、参数指纹和配置一致性校验。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9
    import tomli as tomllib

from ..application.strategy_catalog import StrategyCatalog as StrategyCatalog
from ..application.strategy_catalog import (
    strategy_profile_fingerprint as strategy_profile_fingerprint,
)
from ..domain.control_plane import (
    InvestmentHorizon,
    StrategyLifecycle,
    StrategyRecord,
    ValidationState,
    parse_optional_datetime,
)


def _required(values: dict[str, Any], key: str, owner: str) -> str:
    value = str(values.get(key, "")).strip()
    if not value:
        raise ValueError(f"{owner} 必须提供 {key}")
    return value


def _datetime(values: dict[str, Any], key: str, owner: str) -> datetime:
    value = parse_optional_datetime(values.get(key))
    if value is None:
        raise ValueError(f"{owner} 必须提供 {key}")
    return value


def load_strategy_catalog(path: Path) -> StrategyCatalog:
    """读取 `research/strategies/catalog.toml`。"""

    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    version = int(raw.get("schema_version", 0))
    if version != 1:
        raise ValueError(f"策略目录 schema_version 必须为 1，实际为 {version}")
    records: list[StrategyRecord] = []
    for index, values in enumerate(raw.get("strategies", [])):
        if not isinstance(values, dict):
            raise ValueError(f"strategies[{index}] 必须是对象")
        owner = f"strategies[{index}]"
        symbols = tuple(
            str(item).strip() for item in values.get("symbols", []) if str(item).strip()
        )
        lifecycle = StrategyLifecycle(_required(values, "lifecycle", owner).lower())
        validation = ValidationState(
            str(values.get("validation_state", "pending")).lower()
        )
        backtest_parameters = values.get("backtest_parameters", {})
        if not isinstance(backtest_parameters, dict):
            raise ValueError(f"{owner}.backtest_parameters 必须是键值表")
        records.append(
            StrategyRecord(
                record_id=_required(values, "record_id", owner),
                profile_id=_required(values, "profile_id", owner),
                version=_required(values, "version", owner),
                name=_required(values, "name", owner),
                symbols=symbols,
                horizon=InvestmentHorizon.parse(_required(values, "horizon", owner)),
                lifecycle=lifecycle,
                validation_state=validation,
                created_at=_datetime(values, "created_at", owner),
                enabled_at=parse_optional_datetime(values.get("enabled_at")),
                retired_at=parse_optional_datetime(values.get("retired_at")),
                thesis=_required(values, "thesis", owner),
                parameters_fingerprint=_required(
                    values,
                    "parameters_fingerprint",
                    owner,
                ),
                backtest_model_id=str(values.get("backtest_model_id", "")).strip(),
                backtest_model_version=str(
                    values.get("backtest_model_version", "")
                ).strip(),
                backtest_parameters=dict(backtest_parameters),
            )
        )
    return StrategyCatalog(schema_version=version, records=tuple(records))
