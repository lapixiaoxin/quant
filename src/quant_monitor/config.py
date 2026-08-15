"""分层配置加载、引用校验与敏感信息边界。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any

from .domain.models import Instrument, InstrumentType

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9-3.10 使用兼容包
    import tomli as tomllib


@dataclass(frozen=True)
class PortfolioConfig:
    """单个标的的持仓上下文。"""

    enabled: bool = False
    shares: float = 0.0
    average_cost: float = 0.0
    planned_total_amount: float = 0.0


@dataclass(frozen=True)
class ProductTypeConfig:
    """产品大类提供的默认行为，可被单个标的覆盖。"""

    instrument_type: InstrumentType
    strategy_profile_ids: tuple[str, ...]
    research_profile_id: str
    notification_policy_id: str
    history_days: int


@dataclass(frozen=True)
class ResearchProfileConfig:
    """研究代理需要遵循的内容画像。"""

    profile_id: str
    skill: str
    sections: tuple[str, ...]
    focus: tuple[str, ...]
    source_priorities: tuple[str, ...]
    max_sources: int
    instructions: tuple[str, ...]


@dataclass(frozen=True)
class StrategyProfileConfig:
    """策略实现及其业务可调参数。"""

    profile_id: str
    strategy_id: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ResearchPlan:
    """合并研究画像与标的个性化关注点后的执行计划。"""

    profile_id: str
    skill: str
    sections: tuple[str, ...]
    focus: tuple[str, ...]
    source_priorities: tuple[str, ...]
    max_sources: int
    instructions: tuple[str, ...]

    def to_packet(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "skill": self.skill,
            "sections": list(self.sections),
            "focus": list(self.focus),
            "source_priorities": list(self.source_priorities),
            "max_sources": self.max_sources,
            "instructions": list(self.instructions),
        }


@dataclass(frozen=True)
class NotificationChannelConfig:
    """一个通知通道及其适配器参数，敏感值只保存环境变量名。"""

    channel_id: str
    channel_type: str
    enabled: bool
    options: dict[str, Any]


@dataclass(frozen=True)
class NotificationPolicyConfig:
    """通知事件与通道的路由规则。"""

    policy_id: str
    enabled: bool
    channels: tuple[str, ...]
    events: tuple[str, ...]
    title_template: str

    def to_packet(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "enabled": self.enabled,
            "channels": list(self.channels),
            "events": list(self.events),
            "title_template": self.title_template,
        }


@dataclass(frozen=True)
class Settings:
    """经过继承解析和交叉引用校验的运行配置。"""

    root: Path
    config_path: Path
    raw: dict[str, Any]
    product_types: dict[InstrumentType, ProductTypeConfig]
    strategy_profiles: dict[str, StrategyProfileConfig]
    research_profiles: dict[str, ResearchProfileConfig]
    notification_policies: dict[str, NotificationPolicyConfig]
    notification_channels: dict[str, NotificationChannelConfig]
    instruments: tuple[Instrument, ...]

    @property
    def data_dir(self) -> Path:
        return self.root / self.raw["app"].get("data_dir", "data")

    @property
    def log_dir(self) -> Path:
        return self.root / self.raw["app"].get("log_dir", "logs")

    @property
    def timezone(self) -> str:
        return str(self.raw["app"].get("timezone", "Asia/Shanghai"))

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
        instrument = self.instrument_for(symbol)
        profile = self.research_profiles[instrument.research_profile_id]
        return ResearchPlan(
            profile_id=profile.profile_id,
            skill=profile.skill,
            sections=profile.sections,
            focus=_unique(profile.focus + instrument.research_focus),
            source_priorities=profile.source_priorities,
            max_sources=profile.max_sources,
            instructions=_unique(
                profile.instructions + instrument.research_instructions
            ),
        )

    def notification_policy_for(self, symbol: str) -> NotificationPolicyConfig:
        instrument = self.instrument_for(symbol)
        return self.notification_policies[instrument.notification_policy_id]


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _strings(
    value: Any,
    field: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} 必须是字符串数组")
    normalized = tuple(item.strip() for item in value if item.strip())
    if not normalized and not allow_empty:
        raise ValueError(f"{field} 不能为空")
    return normalized


def _required_string(values: dict[str, Any], field: str, owner: str) -> str:
    value = str(values.get(field, "")).strip()
    if not value:
        raise ValueError(f"{owner} 必须配置 {field}")
    return value


def _title_template(value: Any, owner: str) -> str:
    template = str(value)
    allowed = {"symbol", "name", "type", "event"}
    try:
        fields = {
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name
        }
    except ValueError as error:
        raise ValueError(f"{owner}.title_template 格式无效") from error
    unknown = sorted(fields - allowed)
    if unknown:
        raise ValueError(
            f"{owner}.title_template 使用了未知字段：{'、'.join(unknown)}"
        )
    return template


def ensure_user_config(root: Path) -> Path:
    config_path = root / "config" / "config.toml"
    if config_path.exists():
        return config_path
    example_path = root / "config" / "config.example.toml"
    if not example_path.exists():
        raise FileNotFoundError(f"缺少配置模板：{example_path}")
    shutil.copyfile(example_path, config_path)
    return config_path


def _load_product_types(raw: dict[str, Any]) -> dict[InstrumentType, ProductTypeConfig]:
    result: dict[InstrumentType, ProductTypeConfig] = {}
    for type_name, values in raw.get("product_types", {}).items():
        instrument_type = InstrumentType.parse(type_name)
        owner = f"product_types.{type_name}"
        result[instrument_type] = ProductTypeConfig(
            instrument_type=instrument_type,
            strategy_profile_ids=_strings(
                values.get("strategy_profiles"),
                f"{owner}.strategy_profiles",
            ),
            research_profile_id=_required_string(
                values, "research_profile", owner
            ),
            notification_policy_id=_required_string(
                values, "notification_policy", owner
            ),
            history_days=int(values.get("history_days", 500)),
        )
    if not result:
        raise ValueError("至少需要一个 [product_types.<type>] 配置")
    return result


def _load_strategy_profiles(
    raw: dict[str, Any],
) -> dict[str, StrategyProfileConfig]:
    result: dict[str, StrategyProfileConfig] = {}
    for profile_id, values in raw.get("strategy_profiles", {}).items():
        owner = f"strategy_profiles.{profile_id}"
        parameters = values.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError(f"{owner}.parameters 必须是键值表")
        result[profile_id] = StrategyProfileConfig(
            profile_id=profile_id,
            strategy_id=_required_string(values, "strategy", owner),
            parameters=dict(parameters),
        )
    if not result:
        raise ValueError("至少需要一个 [strategy_profiles.<id>] 配置")
    return result


def _load_research_profiles(
    raw: dict[str, Any],
) -> dict[str, ResearchProfileConfig]:
    result: dict[str, ResearchProfileConfig] = {}
    for profile_id, values in raw.get("research_profiles", {}).items():
        owner = f"research_profiles.{profile_id}"
        max_sources = int(values.get("max_sources", 6))
        if max_sources <= 0:
            raise ValueError(f"{owner}.max_sources 必须大于 0")
        result[profile_id] = ResearchProfileConfig(
            profile_id=profile_id,
            skill=_required_string(values, "skill", owner),
            sections=_strings(values.get("sections"), f"{owner}.sections"),
            focus=_strings(
                values.get("focus", []),
                f"{owner}.focus",
                allow_empty=True,
            ),
            source_priorities=_strings(
                values.get("source_priorities"),
                f"{owner}.source_priorities",
            ),
            max_sources=max_sources,
            instructions=_strings(
                values.get("instructions", []),
                f"{owner}.instructions",
                allow_empty=True,
            ),
        )
    if not result:
        raise ValueError("至少需要一个 [research_profiles.<id>] 配置")
    return result


def _load_notification_channels(
    raw: dict[str, Any],
) -> dict[str, NotificationChannelConfig]:
    result: dict[str, NotificationChannelConfig] = {}
    for channel_id, values in raw.get("notification_channels", {}).items():
        result[channel_id] = NotificationChannelConfig(
            channel_id=channel_id,
            channel_type=_required_string(
                values,
                "type",
                f"notification_channels.{channel_id}",
            ),
            enabled=bool(values.get("enabled", True)),
            options={
                key: value
                for key, value in values.items()
                if key not in {"type", "enabled"}
            },
        )
    return result


def _load_notification_policies(
    raw: dict[str, Any],
) -> dict[str, NotificationPolicyConfig]:
    result: dict[str, NotificationPolicyConfig] = {}
    for policy_id, values in raw.get("notification_policies", {}).items():
        owner = f"notification_policies.{policy_id}"
        result[policy_id] = NotificationPolicyConfig(
            policy_id=policy_id,
            enabled=bool(values.get("enabled", True)),
            channels=_strings(
                values.get("channels", []),
                f"{owner}.channels",
                allow_empty=True,
            ),
            events=_strings(
                values.get("events", []),
                f"{owner}.events",
                allow_empty=True,
            ),
            title_template=_title_template(
                values.get("title_template", "{symbol} {name} 研究简报"),
                owner,
            ),
        )
    if not result:
        raise ValueError("至少需要一个 [notification_policies.<id>] 配置")
    return result


def _load_instruments(
    raw: dict[str, Any],
    product_types: dict[InstrumentType, ProductTypeConfig],
) -> tuple[Instrument, ...]:
    instruments: list[Instrument] = []
    for item in raw.get("instruments", []):
        symbol = _required_string(item, "symbol", "instruments")
        name = _required_string(item, "name", f"标的 {symbol}")
        instrument_type = InstrumentType.parse(str(item.get("type", "")))
        try:
            defaults = product_types[instrument_type]
        except KeyError as error:
            raise ValueError(
                f"标的 {symbol} 缺少 product_types.{instrument_type.value} 默认配置"
            ) from error
        strategy_profile_ids = (
            _strings(
                item["strategy_profiles"],
                f"标的 {symbol}.strategy_profiles",
            )
            if "strategy_profiles" in item
            else defaults.strategy_profile_ids
        )
        history_days = int(item.get("history_days", defaults.history_days))
        if history_days < 20:
            raise ValueError(f"标的 {symbol}.history_days 不能小于 20")
        instruments.append(
            Instrument(
                symbol=symbol,
                name=name,
                exchange=str(item.get("exchange", "SH")).upper(),
                instrument_type=instrument_type,
                strategy_profile_ids=strategy_profile_ids,
                research_profile_id=str(
                    item.get("research_profile", defaults.research_profile_id)
                ),
                notification_policy_id=str(
                    item.get(
                        "notification_policy",
                        defaults.notification_policy_id,
                    )
                ),
                history_days=history_days,
                enabled=bool(item.get("enabled", True)),
                research_focus=_strings(
                    item.get("research_focus", []),
                    f"标的 {symbol}.research_focus",
                    allow_empty=True,
                ),
                research_instructions=_strings(
                    item.get("research_instructions", []),
                    f"标的 {symbol}.research_instructions",
                    allow_empty=True,
                ),
                tracking_index=str(item.get("tracking_index", "")),
                tracking_index_code=str(item.get("tracking_index_code", "")),
            )
        )
    if not instruments:
        raise ValueError("至少需要一个 [[instruments]] 配置")
    symbols = [item.symbol for item in instruments]
    duplicates = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
    if duplicates:
        raise ValueError(f"标的代码重复：{'、'.join(duplicates)}")
    return tuple(instruments)


def _validate_references(settings: Settings) -> None:
    for product_type in settings.product_types.values():
        for profile_id in product_type.strategy_profile_ids:
            if profile_id not in settings.strategy_profiles:
                raise ValueError(
                    f"产品类型 {product_type.instrument_type.value} 引用了不存在的"
                    f"策略画像 {profile_id}"
                )
        if product_type.research_profile_id not in settings.research_profiles:
            raise ValueError(
                f"产品类型 {product_type.instrument_type.value} 引用了不存在的"
                f"研究画像 {product_type.research_profile_id}"
            )
        if product_type.notification_policy_id not in settings.notification_policies:
            raise ValueError(
                f"产品类型 {product_type.instrument_type.value} 引用了不存在的"
                f"通知策略 {product_type.notification_policy_id}"
            )
    for instrument in settings.instruments:
        for profile_id in instrument.strategy_profile_ids:
            if profile_id not in settings.strategy_profiles:
                raise ValueError(
                    f"标的 {instrument.symbol} 引用了不存在的策略画像 "
                    f"{profile_id}"
                )
        if instrument.research_profile_id not in settings.research_profiles:
            raise ValueError(
                f"标的 {instrument.symbol} 引用了不存在的研究画像 "
                f"{instrument.research_profile_id}"
            )
        if instrument.notification_policy_id not in settings.notification_policies:
            raise ValueError(
                f"标的 {instrument.symbol} 引用了不存在的通知策略 "
                f"{instrument.notification_policy_id}"
            )
    for policy in settings.notification_policies.values():
        for channel_id in policy.channels:
            if channel_id not in settings.notification_channels:
                raise ValueError(
                    f"通知策略 {policy.policy_id} 引用了不存在的通道 {channel_id}"
                )


def load_settings(root: Path, config_path: Path | None = None) -> Settings:
    """读取 TOML，应用产品类别默认值并校验全部引用。"""

    path = (config_path or ensure_user_config(root)).resolve()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    app = raw.setdefault("app", {})
    app.setdefault("data_dir", "data")
    app.setdefault("log_dir", "logs")

    product_types = _load_product_types(raw)
    strategy_profiles = _load_strategy_profiles(raw)
    research_profiles = _load_research_profiles(raw)
    notification_channels = _load_notification_channels(raw)
    notification_policies = _load_notification_policies(raw)
    instruments = _load_instruments(raw, product_types)
    settings = Settings(
        root=root.resolve(),
        config_path=path,
        raw=raw,
        product_types=product_types,
        strategy_profiles=strategy_profiles,
        research_profiles=research_profiles,
        notification_policies=notification_policies,
        notification_channels=notification_channels,
        instruments=instruments,
    )
    _validate_references(settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    return settings
