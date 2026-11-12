"""Generic parsing extracted from enterprise code; no enterprise runtime imports."""
from __future__ import annotations

import json
import re
from pathlib import Path

from pypdf import PdfReader

from .extracted.document_splitter import ContentUnit, split_content_units, split_docx
from .extracted.text_splitter import collect_markdown_units, split_txt

HEADER = "<!-- personal-rag "


def decode_note(text: str):
    text = text.replace("\r\n", "\n")
    if text.startswith(HEADER):
        first, _, body = text.partition("\n")
        if not first.endswith(" -->"):
            raise ValueError("笔记元数据头损坏")
        return json.loads(first[len(HEADER):-4]), body
    return {}, text


def encode_note(metadata: dict, body: str):
    return HEADER + json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + " -->\n" + body


def parse(path: Path, body: str | None = None, title: str | None = None):
    if path.suffix.lower() == ".md":
        if body is None:
            _, body = decode_note(path.read_text(encoding="utf-8-sig"))
        return split_content_units(collect_markdown_units(body), path=path, document_name=title or path.stem)
    if path.suffix.lower() == ".txt":
        return split_txt(path, document_name=title)
    if path.suffix.lower() == ".docx":
        return split_docx(path, document_name=title)
    if path.suffix.lower() == ".pdf":
        chunks = []
        for number, page in enumerate(PdfReader(path).pages, 1):
            text = page.extract_text() or ""
            if not text.strip():
                raise ValueError(f"PDF 第{number}页没有可提取文字；扫描件 OCR 尚未启用")
            chunks.extend(split_content_units([ContentUnit("paragraph", text, (f"第{number}页",),
                {"page": number, "parser": "pypdf"})], path=path, document_name=title or path.stem))
        return chunks
    raise ValueError("支持 MD、TXT、DOCX 和文本 PDF")


def body_text(text):
    return re.sub(r"^文档[:：][^\n]*\n章节[:：][^\n]*\n\s*\n", "", text, count=1)


def parents_for(chunks, max_characters=1500):
    """Adapted enterprise extractive parents: same-section grouping, no summaries."""
    groups = []
    for index, chunk in enumerate(chunks):
        section = chunk.metadata.get("section_path", "")
        text = body_text(chunk.page_content)
        if (groups and groups[-1]["section"] == section
                and len(groups[-1]["content"]) + len(text) + 2 <= max_characters):
            groups[-1]["content"] += "\n\n" + text
            groups[-1]["indices"].append(index)
        else:
            groups.append({"section": section, "content": text, "indices": [index]})
    return groups
