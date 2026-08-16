"""基于 lark-cli WebSocket 长连接的飞书消息入口。"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

from ..config import RemoteConfig


@dataclass(frozen=True)
class RemoteMessage:
    """压缩后的飞书文本消息事件。"""

    message_id: str
    sender_id: str
    chat_id: str
    content: str


def _normalize_command_content(
    event: dict[str, object],
    content: str,
    prefix: str,
) -> str:
    """移除群聊中由飞书渲染在命令前的机器人提及。"""

    normalized = content.strip()
    mentions = event.get("mentions", [])
    if isinstance(mentions, list):
        for mention in mentions:
            if not isinstance(mention, dict):
                continue
            name = str(mention.get("name", "")).strip()
            marker = f"@{name}" if name else ""
            if marker and normalized.startswith(marker):
                normalized = normalized[len(marker) :].lstrip()
    if normalized.startswith(prefix):
        return normalized
    parts = normalized.split(maxsplit=1)
    if (
        len(parts) == 2
        and parts[0].startswith("@")
        and parts[1].startswith(prefix)
    ):
        return parts[1]
    return normalized


class LarkCliEventSource:
    """启动只读事件订阅并逐条输出文本消息。"""

    def __init__(self, config: RemoteConfig) -> None:
        self._config = config
        self._process: subprocess.Popen[str] | None = None

    def _executable(self) -> str | None:
        return shutil.which(self._config.lark_cli_path)

    def is_available(self) -> bool:
        return self._executable() is not None

    def check(self) -> None:
        executable = self._executable()
        if not executable:
            raise RuntimeError("未找到 lark-cli")
        subprocess.run(
            [
                executable,
                "event",
                "+subscribe",
                "--event-types",
                "im.message.receive_v1",
                "--as",
                "bot",
                "--compact",
                "--quiet",
                "--dry-run",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def messages(self) -> Iterator[RemoteMessage]:
        executable = self._executable()
        if not executable:
            raise RuntimeError("未找到 lark-cli")
        self._process = subprocess.Popen(
            [
                executable,
                "event",
                "+subscribe",
                "--event-types",
                "im.message.receive_v1",
                "--as",
                "bot",
                "--compact",
                "--quiet",
            ],
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
        )
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    event.get("type") != "im.message.receive_v1"
                    or event.get("message_type") != "text"
                ):
                    continue
                message_id = str(event.get("message_id", "")).strip()
                sender_id = str(event.get("sender_id", "")).strip()
                chat_id = str(event.get("chat_id", "")).strip()
                content = _normalize_command_content(
                    event,
                    str(event.get("content", "")),
                    self._config.prefix,
                )
                if message_id and sender_id and chat_id and content:
                    yield RemoteMessage(
                        message_id=message_id,
                        sender_id=sender_id,
                        chat_id=chat_id,
                        content=content,
                    )
        finally:
            self.close()
        if self._process and self._process.returncode not in (0, None):
            raise RuntimeError(
                f"lark-cli 事件订阅异常退出：{self._process.returncode}"
            )

    def close(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)


class LarkCliReplier:
    """回复原始飞书消息，不改变标的通知策略。"""

    def __init__(self, config: RemoteConfig) -> None:
        self._config = config

    def _executable(self) -> str:
        executable = shutil.which(self._config.lark_cli_path)
        if not executable:
            raise RuntimeError("未找到 lark-cli")
        return executable

    def reply(self, message_id: str, text: str) -> None:
        payload = {
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        subprocess.run(
            [
                self._executable(),
                "api",
                "POST",
                f"/open-apis/im/v1/messages/{message_id}/reply",
                "--data",
                json.dumps(payload, ensure_ascii=False),
                "--as",
                "bot",
                "--format",
                "data",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
