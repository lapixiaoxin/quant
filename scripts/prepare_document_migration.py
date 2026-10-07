"""一次性整理旧研究正文；只准备迁移稿，不调用飞书、不删除原始证据。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from quant_monitor.infrastructure.documents import DocumentRegistry

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now().astimezone().isoformat()


class MarkdownDraft(HTMLParser):
    """转换正文、表格、来源链接和图片引用；复杂布局以原文为准。"""

    def __init__(self, source: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.parts: list[str] = []
        self.skip = 0
        self.links: list[str] = []
        self.assets: set[str] = set()
        self.cells: list[str] = []
        self.cell: list[str] | None = None
        self.header = False

    def append(self, value: str) -> None:
        (self.cell if self.cell is not None else self.parts).append(value)

    def resource(self, href: str) -> str:
        if not href or urlparse(href).scheme or href.startswith("#"):
            return href
        target = (self.source.parent / href.split("#")[0].split("?")[0]).resolve()
        if target.is_relative_to(ROOT) and target.is_file():
            relative = str(target.relative_to(ROOT))
            if target.suffix in {".svg", ".png", ".csv", ".json"}:
                self.assets.add(relative)
            return relative
        return href

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "header", "nav", "head", "footer"}:
            self.skip += 1
        if self.skip:
            return
        attributes = dict(attrs)
        if tag in {"p", "div", "section", "details", "summary", "br", "ul", "ol"}:
            self.append("\n\n")
        elif re.fullmatch(r"h[1-6]", tag):
            self.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.append("\n- ")
        elif tag in {"strong", "b"}:
            self.append("**")
        elif tag == "a":
            self.links.append(self.resource(attributes.get("href") or ""))
            self.append("[")
        elif tag == "img":
            self.append(
                f"\n![{attributes.get('alt') or '历史图表'}]"
                f"({self.resource(attributes.get('src') or '')})\n",
            )
        elif tag == "tr":
            self.cells = []
            self.header = False
        elif tag in {"th", "td"}:
            self.cell = []
            self.header = self.header or tag == "th"

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "header", "nav", "head", "footer"}:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag in {"th", "td"} and self.cell is not None:
            self.cells.append(" ".join("".join(self.cell).split()).replace("|", "\\|"))
            self.cell = None
        elif tag == "tr" and self.cells:
            self.append("\n| " + " | ".join(self.cells) + " |")
            if self.header:
                self.append("\n| " + " | ".join("---" for _ in self.cells) + " |")
        elif tag == "a" and self.links:
            self.append(f"]({self.links.pop()})")
        elif tag in {"strong", "b"}:
            self.append("**")
        elif tag in {"p", "div", "table", "section"} or re.fullmatch(r"h[1-6]", tag):
            self.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.append(re.sub(r"\s+", " ", data))


def metadata(document_id: str, symbol: str, kind: str, path: Path) -> dict:
    return {
        "document_id": document_id,
        "symbol": symbol,
        "kind": kind,
        "title": path.stem,
        "parent_id": f"instrument-{symbol}" if symbol else "root",
        "local_path": str(path.relative_to(ROOT)),
        "source_paths": [],
        "data_as_of": "历史研究；具体数据时间见正文",
        "generated_at": STAMP,
        "status": "pending",
        "strategy_record_ids": [],
        "model": "",
        "experiment": "",
    }


def main() -> None:
    registry = DocumentRegistry(ROOT)
    if registry.path.exists():
        raise SystemExit("文档索引已存在；迁移脚本只运行一次，后续请逐份维护文档版本")
    directory = ROOT / "research/migration"
    directory.mkdir(parents=True, exist_ok=True)
    for symbol, name in (("601985", "中国核电"), ("510720", "红利国企ETF国泰")):
        path = directory / f"instrument-{symbol}.md"
        path.write_text(
            f"# {name}（{symbol}）\n\n研究主页，待创建于指定飞书根目录下。\n\n"
            "策略、回测与研究记录按独立文档版本维护；历史结论不代表当前建议。\n",
            encoding="utf-8",
        )
        record = metadata(f"instrument-{symbol}", symbol, "instrument", path)
        record["title"] = f"{symbol} {name}"
        record["parent_id"] = "root"
        registry.register(record)
    sources = sorted(
        list(ROOT.glob("data/backtests/**/*.html"))
        + list(ROOT.glob("data/reports/**/*.html"))
        + list(ROOT.glob("research/private/**/*.html"))
        + list(ROOT.glob("research/methods/*.html"))
        + list(ROOT.glob("research/library/*.html"))
        + list(ROOT.glob("research/selections/*/*.html")),
    )
    for source in sources:
        if source.name == "index.html":
            continue
        relative = str(source.relative_to(ROOT))
        parser = MarkdownDraft(source)
        parser.feed(source.read_text(encoding="utf-8"))
        document_id = re.sub(r"[^A-Za-z0-9_-]", "-", relative.removesuffix(".html"))
        target = directory / f"{document_id}.md"
        body = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "".join(parser.parts)).strip()
        markdown_source = source.with_suffix(".md")
        if markdown_source.exists():
            body = markdown_source.read_text(encoding="utf-8")
            parser.assets.add(str(markdown_source.relative_to(ROOT)))
        if len(body.strip()) < 100:
            raise ValueError(f"迁移正文过短或仅有加载壳，请检查原始正文：{relative}")
        body = "\n".join(line.rstrip() for line in body.splitlines())
        target.write_text(
            f"> 迁移草稿，尚未发布。原文：`{relative}`。\n"
            "> 原始 HTML 与图表保留供核验；历史结论与数据时间以正文为准。\n\n"
            + body
            + "\n",
            encoding="utf-8",
        )
        symbol = (
            "601985"
            if "601985" in relative
            else (
                "510720" if "510720" in relative or "dividend-yield" in relative else ""
            )
        )
        kind = (
            "backtest"
            if "backtest" in relative
            else (
                "selection"
                if "selections" in relative
                else ("strategy" if "dividend-yield" in relative else "research")
            )
        )
        record = metadata(document_id, symbol, kind, target)
        heading = re.search(r"<h1[^>]*>(.*?)</h1>", source.read_text(), re.S)
        if heading:
            record["title"] = unescape(re.sub(r"<[^>]+>", "", heading[1])).strip()
        elif markdown_source.exists():
            record["title"] = body.splitlines()[0].lstrip("# ").strip()
        record["source_paths"] = sorted({relative, *parser.assets})
        context = relative + " " + body
        if symbol == "601985" and any(term in context for term in ("swing", "capital")):
            study = (
                "swing"
                if "swing" in relative
                else "capital"
                if "capital" in context
                else "swing"
            )
            spec_path = f"research/strategies/601985-{study}-study.json"
            spec = json.loads((ROOT / spec_path).read_text())
            record["strategy_record_ids"] = [spec["study_id"]]
            record["model"] = f"{spec['model_id']}@{spec['model_version']}"
            record["experiment"] = spec_path
            record["data_as_of"] = spec["end"]
            record["source_paths"].extend([spec_path, spec["method_path"]])
        elif symbol == "510720":
            record["strategy_record_ids"] = ["dividend-yield-dynamic-v1"]
            record["model"] = "dividend_yield_percentile_allocation@1.0.0"
        json_source = source.with_suffix(".json")
        if json_source.exists():
            record["source_paths"].append(str(json_source.relative_to(ROOT)))
            record["experiment"] = str(json_source.relative_to(ROOT))
        registry.register(record)
    print(json.dumps({"migration_drafts": len(registry.list())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
