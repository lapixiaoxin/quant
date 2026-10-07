"""策略目录的纯规则：版本查找、启用约束与参数指纹。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..config import Settings, StrategyProfileConfig
from ..domain.control_plane import StrategyLifecycle, StrategyRecord


def strategy_profile_fingerprint(profile: StrategyProfileConfig) -> str:
    """固定算法和参数的序列化，保持历史指纹不变。"""
    payload = {"strategy_id": profile.strategy_id, "parameters": profile.parameters}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class StrategyCatalog:
    """目录本身不读文件；配置与历史版本通过参数指纹绑定。"""

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
        records = []
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
        """doctor 校验启用标的；显式研究只校验目标标的。"""
        for instrument in settings.enabled_instruments:
            self.validate_instrument(settings, instrument.symbol)

    def validate_instrument(self, settings: Settings, symbol: str) -> None:
        instrument = settings.instrument_for(symbol)
        for record in self.active_for(symbol, instrument.strategy_profile_ids):
            profile = settings.strategy_profiles[record.profile_id]
            if record.parameters_fingerprint != strategy_profile_fingerprint(profile):
                raise ValueError(f"策略记录 {record.record_id} 的参数指纹与配置不一致")
