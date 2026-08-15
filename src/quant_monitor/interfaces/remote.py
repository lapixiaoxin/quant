"""飞书白名单命令路由。"""

from __future__ import annotations

from collections import deque

from ..application.automation import AutomationService
from ..application.monitoring import MonitoringService
from ..config import Settings
from ..infrastructure.lark_events import LarkCliEventSource, LarkCliReplier
from ..infrastructure.storage import FileResearchRepository
from .dashboard import write_dashboard
from .portal import write_portal


class RemoteCommandRouter:
    """把固定命令映射为应用用例，不接受任意 Shell。"""

    def __init__(
        self,
        settings: Settings,
        monitoring: MonitoringService,
        automation: AutomationService,
        repository: FileResearchRepository,
    ) -> None:
        self._settings = settings
        self._monitoring = monitoring
        self._automation = automation
        self._repository = repository

    def help_text(self) -> str:
        prefix = self._settings.remote.prefix
        return "\n".join(
            [
                "Quant Monitor 可用命令：",
                f"{prefix} status",
                f"{prefix} analyze [标的代码]",
                f"{prefix} base [标的代码]",
                f"{prefix} prepare [标的代码]",
                f"{prefix} dashboard",
                f"{prefix} help",
            ]
        )

    def _symbol(self, arguments: list[str]) -> str:
        if len(arguments) > 1:
            raise ValueError("命令最多接受一个标的代码")
        if arguments:
            symbol = arguments[0]
        elif self._settings.enabled_instruments:
            symbol = self._settings.enabled_instruments[0].symbol
        else:
            raise ValueError("配置中没有已启用的标的")
        instrument = self._settings.instrument_for(symbol)
        if not instrument.enabled:
            raise ValueError(f"标的 {symbol} 已停用")
        return symbol

    def is_long_running(self, content: str) -> bool:
        parts = content.strip().split()
        return (
            len(parts) >= 2
            and parts[0] == self._settings.remote.prefix
            and parts[1].lower() in {"analyze", "base", "prepare"}
        )

    def handle(self, content: str) -> str | None:
        parts = content.strip().split()
        if not parts or parts[0] != self._settings.remote.prefix:
            return None
        if len(parts) == 1:
            return self.help_text()
        command = parts[1].lower()
        arguments = parts[2:]
        if command == "help":
            return self.help_text()
        if command == "status":
            instruments = "、".join(
                f"{item.symbol}({item.name})"
                for item in self._settings.enabled_instruments
            )
            return "\n".join(
                [
                    "Quant Monitor 运行正常",
                    f"已启用标的：{instruments or '无'}",
                    f"自动化模式：{self._settings.automation.mode}",
                    f"自动发送：{'是' if self._settings.automation.send else '否'}",
                ]
            )
        if command == "analyze":
            symbol = self._symbol(arguments)
            result = self._automation.run(
                symbol,
                send=True,
                event="agent_report",
            )
            write_portal(
                self._settings.root / "index.html",
                self._settings.root,
            )
            fallback = "（已降级为基础分析）" if result.fallback_used else ""
            return (
                f"{symbol} 分析完成{fallback}\n"
                f"模式：{result.mode}\n报告：{result.report_path}"
            )
        if command == "base":
            symbol = self._symbol(arguments)
            result = self._automation.run(
                symbol,
                mode="base",
                send=True,
                event="base_report",
            )
            write_portal(
                self._settings.root / "index.html",
                self._settings.root,
            )
            return f"{symbol} 基础分析完成\n报告：{result.report_path}"
        if command == "prepare":
            symbol = self._symbol(arguments)
            path, _ = self._monitoring.prepare(symbol)
            return f"{symbol} 数据准备完成\n数据包：{path}"
        if command == "dashboard":
            if arguments:
                raise ValueError("dashboard 命令不接受参数")
            path = write_dashboard(
                self._settings.data_dir / "dashboard" / "index.html",
                self._repository.list_latest_packets(),
            )
            portal = write_portal(
                self._settings.root / "index.html",
                self._settings.root,
            )
            return f"看板已更新\n路径：{path}\n工作台：{portal}"
        raise ValueError(f"未知命令 {command!r}\n{self.help_text()}")


def listen_remote_commands(
    settings: Settings,
    router: RemoteCommandRouter,
    source: LarkCliEventSource,
    replier: LarkCliReplier,
) -> None:
    """持续监听消息，忽略未授权来源和重复事件。"""

    processed: set[str] = set()
    order: deque[str] = deque()
    for message in source.messages():
        if message.message_id in processed:
            continue
        processed.add(message.message_id)
        order.append(message.message_id)
        if len(order) > 1000:
            processed.discard(order.popleft())
        if not settings.remote.is_allowed(message.sender_id, message.chat_id):
            continue
        if router.is_long_running(message.content):
            replier.reply(message.message_id, "命令已受理，开始执行。")
        try:
            response = router.handle(message.content)
        except Exception as error:
            replier.reply(message.message_id, f"执行失败：{error}")
            continue
        if response:
            replier.reply(message.message_id, response)
