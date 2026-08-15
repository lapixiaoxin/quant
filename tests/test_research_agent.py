from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_monitor.config import AutomationConfig
from quant_monitor.infrastructure.research_agent import TraeCliResearchRunner


def automation_config(path: str = "traecli") -> AutomationConfig:
    return AutomationConfig(
        enabled=True,
        mode="traecli",
        send=False,
        fallback_to_base=True,
        traecli_path=path,
        query_timeout_seconds=60,
        allowed_tools=("Read",),
    )


class TraeCliResearchRunnerTest(unittest.TestCase):
    def test_finds_official_user_install_outside_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            executable = home / ".local" / "bin" / "traecli"
            executable.parent.mkdir(parents=True)
            executable.touch()
            executable.chmod(0o755)

            with (
                patch(
                    "quant_monitor.infrastructure.research_agent.shutil.which",
                    return_value=None,
                ),
                patch(
                    "quant_monitor.infrastructure.research_agent.Path.home",
                    return_value=home,
                ),
            ):
                runner = TraeCliResearchRunner(home, automation_config())

                self.assertTrue(runner.is_available())

    def test_accepts_explicit_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "tools" / "traecli"
            executable.parent.mkdir()
            executable.touch()
            executable.chmod(0o755)
            runner = TraeCliResearchRunner(
                root,
                automation_config(str(executable)),
            )

            self.assertTrue(runner.is_available())


if __name__ == "__main__":
    unittest.main()
