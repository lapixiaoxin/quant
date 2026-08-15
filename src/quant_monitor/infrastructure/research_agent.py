"""TraeCode CLI 非交互研究适配器。"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from ..config import AutomationConfig


class TraeCliResearchRunner:
    """通过项目斜杠命令运行完整研究，不授予代码编辑工具。"""

    def __init__(self, root: Path, config: AutomationConfig) -> None:
        self._root = root
        self._config = config

    def _executable(self) -> str | None:
        configured = Path(self._config.traecli_path).expanduser()
        if configured.is_absolute():
            return str(configured) if configured.is_file() else None
        return shutil.which(self._config.traecli_path)

    def is_available(self) -> bool:
        return self._executable() is not None

    def run(self, symbol: str, *, send: bool) -> Path:
        executable = self._executable()
        if not executable:
            raise RuntimeError("未找到 TraeCode CLI")
        reports_dir = self._root / "data" / "reports"
        started_at = time.time()
        command = f"/instrument-daily {symbol}"
        if send:
            command += " push"
        subprocess.run(
            [
                executable,
                "--allowed-tool",
                ",".join(self._config.allowed_tools),
                "--query-timeout",
                f"{self._config.query_timeout_seconds}s",
                "-p",
                command,
            ],
            cwd=self._root,
            check=True,
            timeout=self._config.query_timeout_seconds + 30,
        )
        candidates = sorted(
            reports_dir.glob(f"*/{symbol}-research.md"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not candidates or candidates[0].stat().st_mtime < started_at:
            raise RuntimeError(
                f"TraeCode CLI 已退出，但未生成 {symbol}-research.md"
            )
        return candidates[0]
