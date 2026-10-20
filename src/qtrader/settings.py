"""全局配置：回测费率、路径、实盘通道参数。

通过环境变量（前缀 ``QT_``）或项目根目录的 ``.env`` 覆盖默认值。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QT_", env_file=".env", extra="ignore"
    )

    # 路径
    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")

    # 回测默认参数
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    transfer_fee_rate: float = 0.00001
    min_commission: float = 5.0
    slippage: float = 0.0002
    volume_limit_pct: float = 0.2
    t_plus_one: bool = True
    broker_profile: str = ""

    # 实盘/仿真
    live_trading_mode: str = "paper"  # paper | broker_live
    live_market_broker: str = "replay"
    live_trader_broker: str = "miniqmt"

    # 真实柜台连接参数
    md_front: str = ""
    td_front: str = ""
    broker_id: str = ""
    user_id: str = ""
    password: str = ""
    app_id: str = ""
    auth_code: str = ""

    def gateway_options(self) -> dict[str, str]:
        """把非空的柜台连接参数打包成引擎的 gateway_options。"""
        mapping = {
            "md_front": self.md_front,
            "td_front": self.td_front,
            "broker_id": self.broker_id,
            "user_id": self.user_id,
            "password": self.password,
            "app_id": self.app_id,
            "auth_code": self.auth_code,
        }
        return {k: v for k, v in mapping.items() if v}

    @property
    def is_paper(self) -> bool:
        return self.live_trading_mode == "paper"


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """进程内单例，避免重复读取 .env。"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
