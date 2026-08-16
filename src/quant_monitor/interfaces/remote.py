"""飞书白名单命令路由。"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from ..application.analysis import AnalysisService
from ..application.automation import AutomationService
from ..application.monitoring import MonitoringService
from ..config import Settings
from ..domain.control_plane import (
    AnalysisCycle,
    AnalysisTrigger,
)
from ..infrastructure.lark_events import LarkCliEventSource, LarkCliReplier
from ..infrastructure.storage import FileResearchRepository
from ..infrastructure.strategy_catalog import StrategyCatalog
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
        analysis: AnalysisService | None = None,
        strategy_catalog: StrategyCatalog | None = None,
        site_refresher: Callable[[], None] | None = None,
    ) -> None:
        self._settings = settings
        self._monitoring = monitoring
        self._automation = automation
        self._repository = repository
        self._analysis = analysis
        self._strategy_catalog = strategy_catalog
        self._site_refresher = site_refresher

    def _refresh_site(self) -> None:
        if self._site_refresher is not None:
            self._site_refresher()
            return
        write_portal(
            self._settings.root / "index.html",
            self._settings.root,
        )

    def help_text(self) -> str:
        prefix = self._settings.remote.prefix
        return "\n".join(
            [
                "Quant Monitor 可用命令：",
                f"{prefix} status  # 查看标的、策略和自动化状态",
                f"{prefix} strategies [标的代码]  # 查看生效策略",
                f"{prefix} analyze [代码|all] [daily,monthly,yearly,moving_average]",
                f"{prefix} base [标的代码]",
                f"{prefix} prepare [标的代码]",
                f"{prefix} dashboard",
                f"{prefix} help",
                "",
                "示例：",
                f"{prefix} strategies <标的代码>",
                f"{prefix} analyze <标的代码> daily,moving_average",
                f"{prefix} analyze all daily",
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
            strategies = self._active_strategy_text()
            return "\n".join(
                [
                    "Quant Monitor 运行正常",
                    f"已启用标的：{instruments or '无'}",
                    f"生效策略：{strategies}",
                    f"自动化模式：{self._settings.automation.mode}",
                    f"自动发送：{'是' if self._settings.automation.send else '否'}",
                    f"帮助：{self._settings.remote.prefix} help",
                ]
            )
        if command == "strategies":
            symbol = self._symbol(arguments)
            return self._strategy_text(symbol)
        if command == "analyze":
            if self._analysis is not None:
                return self._run_analysis(arguments)
            symbol = self._symbol(arguments[:1])
            result = self._automation.run(
                symbol,
                send=True,
                event="agent_report",
            )
            self._refresh_site()
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
            self._refresh_site()
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
            self._refresh_site()
            portal = self._settings.root / "index.html"
            return f"看板已更新\n路径：{path}\n工作台：{portal}"
        raise ValueError(f"未知命令 {command!r}\n{self.help_text()}")

    def _active_strategy_text(self) -> str:
        if self._strategy_catalog is None:
            return "未加载策略目录"
        values = [
            f"{item.symbol}={','.join(item.strategy_profile_ids)}"
            for item in self._settings.enabled_instruments
        ]
        return "；".join(values) or "无"

    def _strategy_text(self, symbol: str) -> str:
        instrument = self._settings.instrument_for(symbol)
        if self._strategy_catalog is None:
            return (
                f"{symbol} 当前策略画像："
                f"{'、'.join(instrument.strategy_profile_ids)}"
            )
        records = self._strategy_catalog.active_for(
            symbol,
            instrument.strategy_profile_ids,
        )
        lines = [f"{symbol} 当前生效策略："]
        for item in records:
            lines.extend(
                [
                    f"- {item.name} {item.version}",
                    f"  状态：{item.lifecycle.value}",
                    f"  期限：{item.horizon.value}",
                    f"  验证：{item.validation_state.value}",
                    f"  启用：{item.enabled_at}",
                ]
            )
        return "\n".join(lines)

    def _run_analysis(self, arguments: list[str]) -> str:
        if len(arguments) > 2:
            raise ValueError(
                "analyze 用法：analyze [代码|all] "
                "[daily,monthly,yearly,moving_average]"
            )
        target = arguments[0] if arguments else ""
        if target.lower() == "all":
            symbols = tuple(
                item.symbol for item in self._settings.enabled_instruments
            )
        else:
            symbols = (self._symbol([target] if target else []),)
        cycle_values = (
            arguments[1].split(",")
            if len(arguments) == 2
            else ["daily", "moving_average"]
        )
        request = self._analysis.create_request(
            symbols=symbols,
            cycles=tuple(
                AnalysisCycle.parse(item) for item in cycle_values
            ),
            trigger=AnalysisTrigger.REMOTE,
            mode=self._settings.automation.mode,
            send=True,
        )
        execution = self._analysis.run(request)
        self._refresh_site()
        if execution.errors and not execution.results:
            raise RuntimeError("；".join(execution.errors))
        reports = "\n".join(
            f"- {item.symbol}：{item.report_path}"
            for item in execution.results
        )
        error_text = (
            "\n部分失败：" + "；".join(execution.errors)
            if execution.errors
            else ""
        )
        return (
            f"分析完成：{request.request_id}\n"
            f"周期：{','.join(item.value for item in request.cycles)}\n"
            f"{reports}{error_text}"
        )


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
