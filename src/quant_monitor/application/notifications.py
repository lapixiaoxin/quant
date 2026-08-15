"""按标的通知策略路由研究报告。"""

from __future__ import annotations

from ..config import Settings
from .ports import NotificationChannel


class NotificationService:
    """将业务事件发送到标的最终解析出的通知通道。"""

    def __init__(
        self,
        settings: Settings,
        channels: dict[str, NotificationChannel],
    ) -> None:
        self._settings = settings
        self._channels = channels

    def send(
        self,
        symbol: str,
        event: str,
        markdown: str,
        *,
        title: str | None = None,
        force: bool = False,
    ) -> tuple[str, ...]:
        instrument = self._settings.instrument_for(symbol)
        policy = self._settings.notification_policy_for(symbol)
        if not policy.enabled:
            raise ValueError(f"标的 {symbol} 的通知策略 {policy.policy_id} 未启用")
        if event not in policy.events and not force:
            raise ValueError(
                f"通知策略 {policy.policy_id} 不接收事件 {event!r}"
            )
        if not policy.channels:
            raise ValueError(f"通知策略 {policy.policy_id} 未配置通道")

        rendered_title = title or policy.title_template.format(
            symbol=instrument.symbol,
            name=instrument.name,
            type=instrument.instrument_type.value,
            event=event,
        )
        sent: list[str] = []
        for channel_id in policy.channels:
            try:
                channel = self._channels[channel_id]
            except KeyError as error:
                raise ValueError(f"通知通道 {channel_id} 未装配") from error
            channel.send(rendered_title, markdown)
            sent.append(channel_id)
        return tuple(sent)
