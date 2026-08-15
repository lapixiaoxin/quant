"""通知通道适配器与装配工厂。"""

from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..application.ports import NotificationChannel
from ..config import NotificationChannelConfig, Settings


class NotificationError(RuntimeError):
    """通知通道调用失败。"""


def _post_json(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
) -> dict:
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.HTTPError) as error:
        raise NotificationError(f"调用通知接口失败：{error}") from error


class FeishuChannel:
    """飞书自建应用或 Webhook 通知通道。"""

    def __init__(self, config: NotificationChannelConfig) -> None:
        self.channel_id = config.channel_id
        self._enabled = config.enabled
        self._options = config.options

    def _option(self, name: str, default: Any = None) -> Any:
        return self._options.get(name, default)

    def _environment_value(self, option: str, default_env: str) -> str | None:
        env_name = str(self._option(option, default_env))
        return os.environ.get(env_name)

    def _app_secret(self) -> str | None:
        secret = self._environment_value("app_secret_env", "FEISHU_APP_SECRET")
        if secret:
            return secret
        service = self._option("keychain_service")
        if not service or shutil.which("security") is None:
            return None
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                getpass.getuser(),
                "-s",
                str(service),
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _send_webhook(self, title: str, markdown: str) -> None:
        webhook = self._environment_value(
            "webhook_env",
            "FEISHU_WEBHOOK_URL",
        )
        if not webhook:
            raise NotificationError(
                f"通道 {self.channel_id} 未设置飞书 Webhook 环境变量"
            )
        result = _post_json(
            webhook,
            {
                "msg_type": "interactive",
                "card": {
                    "config": {"wide_screen_mode": True},
                    "header": {
                        "template": "blue",
                        "title": {"tag": "plain_text", "content": title},
                    },
                    "elements": [{"tag": "markdown", "content": markdown}],
                },
            },
        )
        if result.get("code", result.get("StatusCode", 0)) != 0:
            raise NotificationError(f"飞书拒绝消息：{result}")

    def _send_app(self, title: str, markdown: str) -> None:
        app_id = str(self._option("app_id", "")).strip()
        app_secret = self._app_secret()
        receive_id = self._environment_value(
            "receive_id_env",
            "FEISHU_RECEIVE_ID",
        ) or str(self._option("receive_id", "")).strip()
        receive_id_type = str(self._option("receive_id_type", "chat_id"))
        if not app_id:
            raise NotificationError(f"通道 {self.channel_id} 未配置 app_id")
        if not app_secret:
            raise NotificationError(f"通道 {self.channel_id} 未设置 App Secret")
        if not receive_id:
            raise NotificationError(f"通道 {self.channel_id} 未设置接收目标")

        token_result = _post_json(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": app_id, "app_secret": app_secret},
        )
        token = token_result.get("tenant_access_token")
        if token_result.get("code") != 0 or not token:
            message = token_result.get("msg", "未知错误")
            raise NotificationError(f"获取飞书访问令牌失败：{message}")

        content = {
            "zh_cn": {
                "title": title,
                "content": [[{"tag": "md", "text": markdown}]],
            }
        }
        query = urllib.parse.urlencode({"receive_id_type": receive_id_type})
        result = _post_json(
            f"https://open.feishu.cn/open-apis/im/v1/messages?{query}",
            {
                "receive_id": receive_id,
                "msg_type": "post",
                "content": json.dumps(content, ensure_ascii=False),
            },
            {"Authorization": f"Bearer {token}"},
        )
        if result.get("code") != 0:
            raise NotificationError(f"飞书拒绝消息：{result}")

    def send(self, title: str, markdown: str) -> None:
        if not self._enabled:
            raise NotificationError(f"通知通道 {self.channel_id} 未启用")
        mode = str(self._option("mode", "app"))
        if mode == "app":
            self._send_app(title, markdown)
            return
        if mode == "webhook":
            self._send_webhook(title, markdown)
            return
        raise NotificationError(
            f"通道 {self.channel_id} 不支持飞书模式 {mode!r}"
        )


def build_notification_channels(
    settings: Settings,
) -> dict[str, NotificationChannel]:
    """按通道类型装配适配器；新增通道只扩展此组合根。"""

    channels: dict[str, NotificationChannel] = {}
    for channel_id, config in settings.notification_channels.items():
        if config.channel_type == "feishu":
            channels[channel_id] = FeishuChannel(config)
            continue
        raise ValueError(
            f"通知通道 {channel_id} 使用了未注册类型 {config.channel_type!r}"
        )
    return channels
