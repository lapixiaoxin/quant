from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from quant_monitor.config import RemoteConfig
from quant_monitor.infrastructure.lark_events import (
    LarkCliEventSource,
    LarkCliReplier,
)


def remote_config() -> RemoteConfig:
    return RemoteConfig(
        enabled=True,
        prefix="/quant",
        allowed_sender_ids=("ou_allowed",),
        allowed_chat_ids=(),
        allowed_channel_targets=(),
        lark_cli_path="lark-cli",
    )


class FakeProcess:
    def __init__(self, output: str) -> None:
        self.stdout = io.StringIO(output)
        self.returncode = 0

    def poll(self):
        return self.returncode


class LarkEventsTest(unittest.TestCase):
    @patch(
        "quant_monitor.infrastructure.lark_events.shutil.which",
        return_value="/usr/local/bin/lark-cli",
    )
    @patch("quant_monitor.infrastructure.lark_events.subprocess.run")
    def test_dry_run_uses_bot_identity(self, run, _which) -> None:
        source = LarkCliEventSource(remote_config())

        source.check()

        arguments = run.call_args.args[0]
        self.assertIn("--dry-run", arguments)
        self.assertEqual(
            arguments[arguments.index("--as") + 1],
            "bot",
        )

    @patch(
        "quant_monitor.infrastructure.lark_events.shutil.which",
        return_value="/usr/local/bin/lark-cli",
    )
    @patch("quant_monitor.infrastructure.lark_events.subprocess.Popen")
    def test_parses_compact_text_message(self, popen, _which) -> None:
        event = {
            "type": "im.message.receive_v1",
            "message_id": "om_1",
            "sender_id": "ou_1",
            "chat_id": "oc_1",
            "message_type": "text",
            "content": "/quant status",
        }
        popen.return_value = FakeProcess(json.dumps(event) + "\n")

        messages = list(LarkCliEventSource(remote_config()).messages())

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "/quant status")
        arguments = popen.call_args.args[0]
        self.assertEqual(
            arguments[arguments.index("--as") + 1],
            "bot",
        )

    @patch(
        "quant_monitor.infrastructure.lark_events.shutil.which",
        return_value="/usr/local/bin/lark-cli",
    )
    @patch("quant_monitor.infrastructure.lark_events.subprocess.run")
    def test_reply_uses_bot_and_structured_payload(self, run, _which) -> None:
        LarkCliReplier(remote_config()).reply("om_1", "执行完成")

        arguments = run.call_args.args[0]
        self.assertEqual(
            arguments[arguments.index("--as") + 1],
            "bot",
        )
        payload = json.loads(arguments[arguments.index("--data") + 1])
        self.assertEqual(payload["msg_type"], "text")
        self.assertEqual(
            json.loads(payload["content"])["text"],
            "执行完成",
        )


if __name__ == "__main__":
    unittest.main()
