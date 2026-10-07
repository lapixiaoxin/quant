"""研究配置：标的、采集窗口、可选策略和研究关注点。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .domain.models import Instrument, InstrumentType

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9-3.10
    import tomli as tomllib


@dataclass(frozen=True)
class PortfolioConfig:
    """仅保存在本机的可选资金语境。"""

    enabled: bool = False
    shares: float = 0.0
    average_cost: float = 0.0
    planned_total_amount: float = 0.0


@dataclass(frozen=True)
class ProductTypeConfig:
    """类别默认值不强制绑定策略或研究流程。"""

    instrument_type: InstrumentType
    strategy_profile_ids: tuple[str, ...] = ()
    research_profile_id: str = ""
    history_days: int = 500


@dataclass(frozen=True)
class StrategyProfileConfig:
    """算法标识与一组业务参数。"""

    profile_id: str
    strategy_id: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ResearchPlan:
    """提供给 Agent 的可选研究提示，不限制工具、章节或来源数量。"""

    profile_id: str = ""
    sections: tuple[str, ...] = ()
    focus: tuple[str, ...] = ()
    source_priorities: tuple[str, ...] = ()
    instructions: tuple[str, ...] = ()

    def to_packet(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "sections": list(self.sections),
            "focus": list(self.focus),
            "source_priorities": list(self.source_priorities),
            "instructions": list(self.instructions),
        }


@dataclass(frozen=True)
class Settings:
    """保留原始本机配置但不执行旧自动化与通知字段。"""

    root: Path
    config_path: Path
    raw: dict[str, Any]
    product_types: dict[InstrumentType, ProductTypeConfig]
    strategy_profiles: dict[str, StrategyProfileConfig]
    research_profiles: dict[str, ResearchPlan]
    instruments: tuple[Instrument, ...]

    @property
    def data_dir(self) -> Path:
        return self.root / self.raw.get("app", {}).get("data_dir", "data")

    @property
    def timezone(self) -> str:
        return str(self.raw.get("app", {}).get("timezone", "Asia/Shanghai"))

    @property
    def ignored_legacy_sections(self) -> tuple[str, ...]:
        return tuple(
            key
            for key in (
                "automation",
                "remote",
                "notification_channels",
                "notification_policies",
            )
            if key in self.raw
        )

    @property
    def enabled_instruments(self) -> tuple[Instrument, ...]:
        return tuple(item for item in self.instruments if item.enabled)

    def instrument_for(self, symbol: str) -> Instrument:
        for item in self.instruments:
            if item.symbol == symbol:
                return item
        raise ValueError(f"配置中不存在标的 {symbol}")

    def portfolio_for(self, symbol: str) -> PortfolioConfig:
        values = self.raw.get("portfolio", {}).get(symbol, {})
        return PortfolioConfig(
            enabled=bool(values.get("enabled", False)),
            shares=float(values.get("shares", 0)),
            average_cost=float(values.get("average_cost", 0)),
            planned_total_amount=float(values.get("planned_total_amount", 0)),
        )

    def research_plan_for(self, symbol: str) -> ResearchPlan:
        item = self.instrument_for(symbol)
        profile = self.research_profiles.get(item.research_profile_id, ResearchPlan())
        return ResearchPlan(
            profile_id=profile.profile_id,
            sections=profile.sections,
            focus=tuple(dict.fromkeys(profile.focus + item.research_focus)),
            source_priorities=profile.source_priorities,
            instructions=tuple(
                dict.fromkeys(
                    profile.instructions + item.research_instructions,
                )
            ),
        )


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValueError(f"{field} 必须是字符串数组")
    return tuple(dict.fromkeys(v.strip() for v in value if v.strip()))


def _required(values: dict[str, Any], field: str, owner: str) -> str:
    value = str(values.get(field, "")).strip()
    if not value:
        raise ValueError(f"{owner} 必须配置 {field}")
    return value


def ensure_user_config(root: Path) -> Path:
    path = root / "config" / "config.toml"
    if not path.exists():
        template = root / "config" / "config.example.toml"
        if not template.exists():
            raise FileNotFoundError(f"缺少配置模板：{template}")
        shutil.copyfile(template, path)
        path.chmod(0o600)
    return path


def load_settings(root: Path, config_path: Path | None = None) -> Settings:
    """应用类别默认值；旧本机配置可读取，但不恢复已移除的能力。"""

    path = (config_path or ensure_user_config(root)).resolve()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    products = {}
    for name, values in raw.get("product_types", {}).items():
        kind = InstrumentType.parse(name)
        days = int(values.get("history_days", 500))
        if days < 20:
            raise ValueError(f"product_types.{name}.history_days 不能小于 20")
        products[kind] = ProductTypeConfig(
            kind,
            _strings(values.get("strategy_profiles", []), f"{name}.strategy_profiles"),
            str(values.get("research_profile", "")),
            days,
        )
    profiles = {}
    for name, values in raw.get("strategy_profiles", {}).items():
        parameters = values.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError(f"strategy_profiles.{name}.parameters 必须是键值表")
        profiles[name] = StrategyProfileConfig(
            name,
            _required(values, "strategy", name),
            dict(parameters),
        )
    research = {}
    for name, values in raw.get("research_profiles", {}).items():
        research[name] = ResearchPlan(
            profile_id=name,
            **{
                key: _strings(values.get(key, []), f"{name}.{key}")
                for key in (
                    "sections",
                    "focus",
                    "source_priorities",
                    "instructions",
                )
            },
        )
    instruments = []
    for values in raw.get("instruments", []):
        symbol = _required(values, "symbol", "instruments")
        kind = InstrumentType.parse(_required(values, "type", symbol))
        defaults = products.get(kind, ProductTypeConfig(kind))
        days = int(values.get("history_days", defaults.history_days))
        if days < 20:
            raise ValueError(f"标的 {symbol}.history_days 不能小于 20")
        start = values.get("history_start_date")
        try:
            start_date = date.fromisoformat(str(start)) if start else None
        except ValueError as error:
            raise ValueError(
                f"标的 {symbol}.history_start_date 必须是 YYYY-MM-DD"
            ) from error
        exchange = str(values.get("exchange", "SH")).upper()
        if exchange not in {"SH", "SZ"} or len(symbol) != 6 or not symbol.isdigit():
            raise ValueError(f"标的 {symbol} 必须是六位代码，exchange 仅支持 SH/SZ")
        instruments.append(
            Instrument(
                symbol=symbol,
                name=_required(values, "name", symbol),
                exchange=exchange,
                instrument_type=kind,
                strategy_profile_ids=_strings(
                    values.get(
                        "strategy_profiles", list(defaults.strategy_profile_ids)
                    ),
                    f"{symbol}.strategy_profiles",
                ),
                research_profile_id=str(
                    values.get(
                        "research_profile",
                        defaults.research_profile_id,
                    )
                ),
                notification_policy_id="",  # 旧构造协议保留，运行和 v5 数据包不使用
                history_days=days,
                history_start_date=start_date,
                enabled=bool(values.get("enabled", True)),
                research_focus=_strings(
                    values.get("research_focus", []), f"{symbol}.focus"
                ),
                research_instructions=_strings(
                    values.get("research_instructions", []),
                    f"{symbol}.instructions",
                ),
                tracking_index=str(values.get("tracking_index", "")),
                tracking_index_code=str(values.get("tracking_index_code", "")),
            )
        )
    if len({item.symbol for item in instruments}) != len(instruments):
        raise ValueError("标的代码重复")
    for owner in [*products.values(), *instruments]:
        for profile_id in owner.strategy_profile_ids:
            if profile_id not in profiles:
                raise ValueError(f"引用了不存在的策略画像 {profile_id}")
        if owner.research_profile_id and owner.research_profile_id not in research:
            raise ValueError(f"引用了不存在的研究画像 {owner.research_profile_id}")
    return Settings(
        root.resolve(),
        path,
        raw,
        products,
        profiles,
        research,
        tuple(instruments),
    )
