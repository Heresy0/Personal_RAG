import asyncio
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from personal_rag.config import Policy, Settings, validate_space
from personal_rag.connections import codex_config
from personal_rag.embeddings import Embeddings
from personal_rag.extracted.keyword_tokenizer import tokenize_chinese
from personal_rag.mcp_server import create_server
from personal_rag.parsing import decode_note, encode_note, parents_for, parse
from personal_rag.retrieval import fuse, keyword_rank
from personal_rag.service import MemoryService


@pytest.fixture
def settings(tmp_path):
    return Settings("postgresql://unused/unused", tmp_path / "vault", dimensions=3)


@pytest.mark.parametrize("space", ["../life", "*", "life/work", "生活", "x" * 65, ""])
def test_invalid_space(space):
    with pytest.raises(ValueError):
        validate_space(space)


def test_policy_cannot_start_above_cap():
    with pytest.raises(ValueError):
        Policy("test", ("general",), "read", "readwrite")
    with pytest.raises(ValueError):
        Policy("test", ("*",))


def test_off_blocks_before_database_access(settings):
    service = MemoryService(settings, Policy("test", ("general",)))
    with pytest.raises(PermissionError):
        service.search("秘密")
    with pytest.raises(PermissionError):
        service.read(str(uuid4()))
    with pytest.raises(PermissionError):
        service.set_mode("readwrite")
    service.set_mode("read")
    with pytest.raises(PermissionError):
        service.capture("a", "b", "general")
    with pytest.raises(PermissionError):
        service.search("a", space="life")


def test_modes_are_connection_local(settings):
    a = MemoryService(settings, Policy("a", ("general",)))
    b = MemoryService(settings, Policy("b", ("general",)))
    a.set_mode("read")
    assert a.mode == "read" and b.mode == "off"


def test_reject_path_escape(settings):
    service = MemoryService(settings, Policy("test", ("general",)))
    with pytest.raises(PermissionError):
        service._path("../secret.txt")


def test_markdown_structures_and_parent_text(tmp_path):
    path = tmp_path / "test.md"
    body = '# 学习\n\n金额 550 元，年份 2026。\n\n```python\n# not a heading\nprint("hello")\n```\n\n| 名称 | 值 |\n| --- | --- |\n| key | Bearer access_token |'
    chunks = parse(path, body=body, title="笔记")
    assert {"code", "table"} <= {c.metadata["chunk_type"] for c in chunks}
    parents = parents_for(chunks)
    text = "\n".join(p["content"] for p in parents)
    assert "550" in text and "2026" in text and "Bearer access_token" in text
    assert sorted(i for p in parents for i in p["indices"]) == list(range(len(chunks)))


def test_note_metadata_roundtrip():
    meta = {"id": str(uuid4()), "space": "learning", "title": "学习"}
    body = "原文\n<!-- 普通注释 -->"
    assert decode_note(encode_note(meta, body)) == (meta, body)
    assert decode_note(encode_note(meta, body).replace("\n", "\r\n")) == (meta, body.replace("\n", "\r\n"))


def test_chinese_keywords_preserve_identifiers():
    tokens = tokenize_chinese("接口返回 AUTH_401，预算 550 元")
    assert "auth_401" in tokens and "550" in tokens


def test_keyword_no_unrelated_results():
    rows = [{"id": "a", "content": "学习 Python 装饰器"}, {"id": "b", "content": "餐厅晚餐"}]
    assert keyword_rank("装饰器", rows)[0]["id"] == "a"
    assert keyword_rank("不存在的XYZ", rows) == []


def test_fusion_deduplicates_and_keeps_both_channels():
    rows = fuse([{"id": "a"}, {"id": "b"}], [{"id": "b"}, {"id": "c"}])
    assert rows[0]["id"] == "b"
    assert {r["id"] for r in rows} == {"a", "b", "c"}


def test_embeddings_are_opt_in(settings):
    assert Embeddings(settings).embed(["text"]) == []
    with pytest.raises(ValueError):
        Embeddings(replace(settings, embedding_provider="openai-compatible"))


def test_readonly_mcp_does_not_expose_write_tools(settings):
    server = create_server(MemoryService(settings, Policy("test", ("general",))))
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"search_notes", "read_note", "set_memory_mode"} <= names
    assert not names.intersection({"capture_note", "append_note", "archive_note", "sync_notes"})


def test_manager_tools(settings):
    server = create_server(MemoryService(settings, Policy("manager", ("*",), "readwrite", "readwrite", True)))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"capture_note", "append_note", "archive_note", "sync_notes"} <= names


def test_codex_snippet_is_valid_toml(tmp_path):
    import tomllib
    config = tomllib.loads(codex_config(tmp_path / "connection.toml"))
    server = config["mcp_servers"]["personal_memory"]
    assert Path(server["command"]).is_absolute()
    assert Path(server["args"][0]).is_absolute()
