"""按标的通知策略路由研究报告。"""

from __future__ import annotations

from ..config import Settings
from .ports import NotificationChannel


class NotificationDeliveryError(RuntimeError):
    """报告已生成但一个或多个通知通道发送失败。"""

    def __init__(
        self,
        sent_channels: tuple[str, ...],
        failures: tuple[str, ...],
    ) -> None:
        self.sent_channels = sent_channels
        self.failures = failures
        super().__init__("；".join(failures))


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
        failures: list[str] = []
        for channel_id in policy.channels:
            try:
                channel = self._channels[channel_id]
                channel.send(rendered_title, markdown)
            except (KeyError, OSError, RuntimeError, ValueError) as error:
                failures.append(f"{channel_id}：{error}")
                continue
            sent.append(channel_id)
        if failures:
            raise NotificationDeliveryError(
                tuple(sent),
                tuple(failures),
            )
        return tuple(sent)
