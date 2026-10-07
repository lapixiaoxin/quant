"""飞书研究文档的本地审计索引；不执行远程发布。"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .storage import FileResearchRepository

ROOT_URL = "https://icnxcxzl7hll.feishu.cn/wiki/Nr1Aw5d6Li5cnjkyAuAcZ4x8nag"


class DocumentRegistry:
    """串行登记不可变正文指纹；远端成功与本地准备分开记录。"""

    root_url = ROOT_URL

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = self.root / "research/documents.json"

    def _file(self, value: str) -> Path:
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("文档引用不能超出工作区")
        relative = path.relative_to(self.root)
        if (
            relative.parts[:2] == ("research", "scratch")
            or "latest" in relative.parts
        ):
            raise ValueError("文档引用不能使用 scratch 临时稿或 latest 可覆盖文件")
        if (
            not relative.parts
            or relative.parts[0] not in {"research", "data"}
            or (
                path.suffix.lower()
                not in {".md", ".json", ".csv", ".svg", ".png"}
            )
        ):
            raise ValueError("文档引用只允许 research/data 中的研究文件")
        if not path.is_file():
            raise ValueError(f"文档引用不存在：{relative}")
        return path

    def list(self, symbol: str | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or value.get("root_url") != ROOT_URL:
            raise ValueError("文档索引版本或根目录不匹配")
        records = value["documents"]
        if not isinstance(records, list):
            raise ValueError("documents 必须是数组")
        for record in records:
            for source, digest in record["source_sha256"].items():
                if (
                    hashlib.sha256(self._file(source).read_bytes()).hexdigest()
                    != digest
                ):
                    raise ValueError(
                        f"已登记正文或来源发生变更：{source}；请新建报告版本"
                    )
        return [item for item in records if not symbol or item["symbol"] == symbol]

    def register(self, metadata: dict[str, Any]) -> None:
        """登记草稿或带远端回读凭据的报告；失败不改写原索引。"""
        record = dict(metadata)
        required = {
            "document_id",
            "symbol",
            "kind",
            "title",
            "parent_id",
            "local_path",
            "source_paths",
            "data_as_of",
            "generated_at",
            "status",
            "strategy_record_ids",
            "model",
            "experiment",
        }
        if not required <= record.keys():
            raise ValueError(
                "文档元数据缺少字段：" + "、".join(sorted(required - record.keys()))
            )
        if not re.fullmatch(r"[A-Za-z0-9_-]+", record["document_id"]):
            raise ValueError("document_id 格式无效")
        if record["symbol"] and not re.fullmatch(r"\d{6}", record["symbol"]):
            raise ValueError("文档标的代码格式无效")
        if record["kind"] not in {
            "instrument",
            "research",
            "strategy",
            "backtest",
            "selection",
            "method",
        } or record["status"] not in {"pending", "published"}:
            raise ValueError("文档类别或发布状态无效")
        if not record["title"] or not record["data_as_of"]:
            raise ValueError("文档必须标注标题与数据时间")
        if datetime.fromisoformat(record["generated_at"]).tzinfo is None:
            raise ValueError("generated_at 必须包含时区")
        for key in ("source_paths", "strategy_record_ids"):
            if not isinstance(record[key], list):
                raise ValueError(f"{key} 必须是数组")
        sources = [record["local_path"], *record["source_paths"]]
        if record["status"] == "published":
            parsed = urlparse(record.get("wiki_url", ""))
            if (
                parsed.scheme != "https"
                or parsed.hostname != urlparse(ROOT_URL).hostname
            ):
                raise ValueError("已发布文档必须使用目标飞书空间链接")
            if not re.fullmatch(r"/wiki/[A-Za-z0-9]+", parsed.path):
                raise ValueError("已发布文档必须提供 Wiki 节点链接")
            proof_path = self._file(record.get("verification_path", ""))
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            digest = hashlib.sha256(
                self._file(record["local_path"]).read_bytes()
            ).hexdigest()
            if (
                proof.get("wiki_url") != record["wiki_url"]
                or proof.get("local_sha256") != digest
                or not proof.get("remote_document_id")
                or not proof.get("remote_content")
                or not proof.get("parent_node_token")
                or datetime.fromisoformat(proof["verified_at"]).tzinfo is None
            ):
                raise ValueError("远端回读凭据与正文或节点不匹配")
            sources.append(record["verification_path"])
        elif record.get("wiki_url"):
            raise ValueError("pending 文档不能宣称已有发布链接")
        record["source_sha256"] = {
            str(self._file(source).relative_to(self.root)): hashlib.sha256(
                self._file(source).read_bytes()
            ).hexdigest()
            for source in sources
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            records = self.list()
            existing = next(
                (
                    item
                    for item in records
                    if item["document_id"] == record["document_id"]
                ),
                None,
            )
            parent = next(
                (
                    item
                    for item in records
                    if item["document_id"] == record["parent_id"]
                ),
                None,
            )
            if record["symbol"] and record["kind"] != "instrument":
                if (
                    not parent
                    or parent["kind"] != "instrument"
                    or (parent["symbol"] != record["symbol"])
                ):
                    raise ValueError("标的研究、策略和回测必须挂在对应标的主页下")
            elif record["parent_id"] != "root":
                raise ValueError("标的主页和跨标的文档必须挂在研究根节点下")
            if record["status"] == "published":
                if parent and parent["status"] != "published":
                    raise ValueError("请先登记已发布的标的主页")
                parent_url = parent["wiki_url"] if parent else ROOT_URL
                if (
                    proof["parent_node_token"]
                    != urlparse(parent_url).path.split("/")[-1]
                ):
                    raise ValueError("远端父节点与本地文档层级不一致")
            if existing:
                if any(existing[key] != record[key] for key in required - {"status"}):
                    raise ValueError(
                        "不能覆盖报告版本；正文或元数据变更请新建 document_id"
                    )
                if existing["status"] == "published" and existing != record:
                    raise ValueError("已发布记录不可覆盖")
                records.remove(existing)
            records.append(record)
            FileResearchRepository._atomic_write(
                self.path,
                json.dumps(
                    {
                        "schema_version": 1,
                        "root_url": ROOT_URL,
                        "documents": records,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )
