"""文档草稿与远端发布事实隔离，正文和来源可追溯。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from quant_monitor.infrastructure.documents import ROOT_URL, DocumentRegistry


class DocumentsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "research").mkdir()
        self.draft = self.root / "research/draft.md"
        self.draft.write_text("# 事实与假设\n", encoding="utf-8")
        self.registry = DocumentRegistry(self.root)
        self.record = dict(
            document_id="instrument-601985",
            symbol="601985",
            kind="instrument",
            title="中国核电",
            parent_id="root",
            local_path="research/draft.md",
            source_paths=[],
            data_as_of="2026-09-30",
            generated_at="2026-10-07T12:00:00+08:00",
            status="pending",
            strategy_record_ids=[],
            model="",
            experiment="",
        )

    def published(self):
        url = ROOT_URL.rsplit("/", 1)[0] + "/TestNode"
        proof = {
            "wiki_url": url,
            "local_sha256": hashlib.sha256(self.draft.read_bytes()).hexdigest(),
            "remote_document_id": "TestDocument",
            "remote_content": "# 事实与假设\n",
            "parent_node_token": ROOT_URL.rsplit("/", 1)[-1],
            "verified_at": "2026-10-07T12:30:00+08:00",
        }
        (self.root / "research/proof.json").write_text(
            json.dumps(proof), encoding="utf-8"
        )
        return {
            **self.record,
            "status": "published",
            "wiki_url": url,
            "verification_path": "research/proof.json",
        }

    def test_pending_registration_and_idempotency(self):
        self.registry.register(self.record)
        self.registry.register(self.record)
        records = self.registry.list("601985")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "pending")
        self.assertNotIn("wiki_url", records[0])
        self.assertEqual(self.registry.list("510720"), [])

    def test_published_requires_readback_and_preserves_version(self):
        self.registry.register(self.record)
        published = self.published()
        self.registry.register(published)
        self.registry.register(published)
        self.assertEqual(self.registry.list()[0]["status"], "published")
        with self.assertRaisesRegex(ValueError, "不可覆盖"):
            self.registry.register(self.record)

    def test_failed_publication_does_not_change_pending_record(self):
        self.registry.register(self.record)
        published = self.published()
        published["wiki_url"] = published["wiki_url"] + "Mismatch"
        with self.assertRaisesRegex(ValueError, "不匹配"):
            self.registry.register(published)
        self.assertEqual(self.registry.list()[0]["status"], "pending")

    def test_source_change_and_path_escape_are_rejected(self):
        self.registry.register(self.record)
        self.draft.write_text("# 被修改的结论\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "发生变更"):
            self.registry.list()
        with self.assertRaisesRegex(ValueError, "超出工作区"):
            self.registry.register({**self.record, "local_path": "../outside.md"})

    def test_temporary_or_overwritable_sources_cannot_be_registered(self):
        for source in (
            "research/scratch/draft.md",
            "data/latest/601985.json",
            "data/selections/latest/universe.json",
        ):
            with self.subTest(source=source):
                path = self.root / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "可覆盖文件"):
                    self.registry.register({**self.record, "source_paths": [source]})
                self.assertEqual(self.registry.list(), [])

    def test_child_documents_require_matching_instrument_parent(self):
        child = {
            **self.record,
            "document_id": "backtest-1",
            "kind": "backtest",
            "parent_id": self.record["document_id"],
        }
        with self.assertRaisesRegex(ValueError, "标的主页"):
            self.registry.register(child)
        self.registry.register(self.record)
        self.registry.register(child)
        with self.assertRaisesRegex(ValueError, "标的主页"):
            self.registry.register(
                {**child, "symbol": "510720", "document_id": "wrong"}
            )
