"""版本化策略目录读取、参数指纹和配置一致性校验。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9
    import tomli as tomllib

from ..config import Settings, StrategyProfileConfig
from ..domain.control_plane import (
    InvestmentHorizon,
    StrategyLifecycle,
    StrategyRecord,
    ValidationState,
    parse_optional_datetime,
)


def strategy_profile_fingerprint(profile: StrategyProfileConfig) -> str:
    """冻结算法标识与参数，检测配置和生命周期目录是否漂移。"""

    payload = {
        "strategy_id": profile.strategy_id,
        "parameters": profile.parameters,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class StrategyCatalog:
    """策略版本集合及其运行配置一致性约束。"""

    schema_version: int
    records: tuple[StrategyRecord, ...]

    def __post_init__(self) -> None:
        record_ids = [item.record_id for item in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("策略目录不能包含重复 record_id")
        active_keys = [
            (symbol, item.profile_id)
            for item in self.records
            if item.lifecycle is StrategyLifecycle.ACTIVE
            for symbol in item.symbols
        ]
        if len(active_keys) != len(set(active_keys)):
            raise ValueError("同一标的和策略画像只能有一个启用版本")

    def record(self, record_id: str) -> StrategyRecord:
        for item in self.records:
            if item.record_id == record_id:
                return item
        raise ValueError(f"策略目录不存在记录 {record_id}")

    def active_for(
        self,
        symbol: str,
        profile_ids: tuple[str, ...],
    ) -> tuple[StrategyRecord, ...]:
        records: list[StrategyRecord] = []
        for profile_id in profile_ids:
            matched = [
                item
                for item in self.records
                if item.lifecycle is StrategyLifecycle.ACTIVE
                and item.profile_id == profile_id
                and item.applies_to(symbol)
            ]
            if len(matched) != 1:
                raise ValueError(
                    f"标的 {symbol} 的策略画像 {profile_id} "
                    f"需要且只能有一个启用版本，实际 {len(matched)} 个"
                )
            records.append(matched[0])
        return tuple(records)

    def validate_settings(self, settings: Settings) -> None:
        """保证网页状态、运行参数和实际策略引用来自同一组事实。"""

        for instrument in settings.enabled_instruments:
            self.validate_instrument(settings, instrument.symbol)

    def validate_instrument(self, settings: Settings, symbol: str) -> None:
        """校验单个标的的启用版本、画像引用和冻结参数。"""

        instrument = settings.instrument_for(symbol)
        for record in self.active_for(
            instrument.symbol,
            instrument.strategy_profile_ids,
        ):
            profile = settings.strategy_profiles[record.profile_id]
            fingerprint = strategy_profile_fingerprint(profile)
            if record.parameters_fingerprint != fingerprint:
                raise ValueError(
                    f"策略记录 {record.record_id} 的参数指纹与配置不一致"
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
            str(item).strip()
            for item in values.get("symbols", [])
            if str(item).strip()
        )
        lifecycle = StrategyLifecycle(
            _required(values, "lifecycle", owner).lower()
        )
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
                horizon=InvestmentHorizon.parse(
                    _required(values, "horizon", owner)
                ),
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
                backtest_model_id=str(
                    values.get("backtest_model_id", "")
                ).strip(),
                backtest_model_version=str(
                    values.get("backtest_model_version", "")
                ).strip(),
                backtest_parameters=dict(backtest_parameters),
            )
        )
    if not records:
        raise ValueError("策略目录至少需要一条策略记录")
    return StrategyCatalog(schema_version=version, records=tuple(records))
