"""基于本地文件系统的研究数据仓储。"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


class FileResearchRepository:
    """使用原子替换保存 JSON 与文本，避免中断时留下半文件。"""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        temporary.replace(path)

    def save_packet(self, symbol: str, packet: dict[str, Any]) -> Path:
        now = datetime.fromisoformat(str(packet["as_of"]))
        latest_path = self._data_dir / "latest" / f"{symbol}.json"
        snapshot_path = (
            self._data_dir
            / "snapshots"
            / now.strftime("%Y-%m-%d")
            / f"{symbol}-{now.strftime('%H%M%S')}.json"
        )
        content = json.dumps(packet, ensure_ascii=False, indent=2) + "\n"
        self._atomic_write(latest_path, content)
        self._atomic_write(snapshot_path, content)
        return latest_path

    def load_latest_packet(self, symbol: str) -> dict[str, Any]:
        path = self._data_dir / "latest" / f"{symbol}.json"
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"数据包格式错误：{path}")
        return value

    def save_prompt(self, symbol: str, prompt: str) -> Path:
        path = self._data_dir / "latest" / f"{symbol}.prompt.txt"
        self._atomic_write(path, prompt.rstrip() + "\n")
        return path

    def save_base_report(
        self, symbol: str, as_of: str, content: str
    ) -> Path:
        now = datetime.fromisoformat(as_of)
        report_path = (
            self._data_dir
            / "reports"
            / now.strftime("%Y-%m-%d")
            / f"{symbol}-base.md"
        )
        self._atomic_write(report_path, content)
        self._atomic_write(
            self._data_dir / "latest" / f"{symbol}.base.md",
            content,
        )
        return report_path

    def list_latest_packets(self) -> list[dict[str, Any]]:
        packets: list[dict[str, Any]] = []
        for path in sorted((self._data_dir / "latest").glob("*.json")):
            try:
                with path.open(encoding="utf-8") as handle:
                    value = json.load(handle)
                if isinstance(value, dict):
                    packets.append(value)
            except (OSError, ValueError):
                continue
        return packets
