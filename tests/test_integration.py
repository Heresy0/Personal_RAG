import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from personal_rag.config import Policy, ROOT
from personal_rag.db import Database
from personal_rag.parsing import decode_note, encode_note
from personal_rag.service import MemoryService

pytestmark = pytest.mark.integration


def test_record_search_read_append_and_history(manager):
    note = manager.capture("Python学习", "今天学习 Python 装饰器。", "learning", event_date="2026-11-12")
    assert manager.read(note["id"])["body"] == "今天学习 Python 装饰器。"
    result = manager.search("装饰器")
    assert result["semantic_search"] and result["compatible_vector_chunks"] > 0
    assert result["results"][0]["note_id"] == note["id"]
    updated = manager.append(note["id"], "明天继续理解闭包。", note["revision"])
    assert updated["revision"] == 2
    with manager.db.connect() as conn:
        history = conn.execute("SELECT revision,body FROM note_versions WHERE note_id=%s ORDER BY revision", [note["id"]]).fetchall()
    assert len(history) == 2 and "闭包" not in history[0]["body"]
    with pytest.raises(ValueError):
        manager.append(note["id"], "过时的写入", 1)


def test_retries_are_idempotent(manager):
    request = str(uuid4())
    one = manager.capture("记录", "相同正文", "general", request_id=request)
    two = manager.capture("记录", "相同正文", "general", request_id=request)
    assert one["id"] == two["id"]
    with pytest.raises(ValueError):
        manager.capture("记录", "不同正文", "general", request_id=request)


def test_verbatim_save_keeps_whitespace_newlines_and_sync(manager):
    body = "  原样保存\r\n\r\n```python\r\n    print('hello')\r\n```\r\n  "
    note = manager.capture("原样", body, "inbox")
    assert manager.read(note["id"])["body"] == body
    data = Path(note["path"]).read_bytes()
    assert data.split(b'\n', 1)[1] == body.encode('utf-8')
    # A filename change forces sync, preserving the exact body in the DB too.
    path = Path(note["path"])
    path.rename(path.with_name('renamed.md'))
    assert manager.sync()["indexed"] == 1
    assert manager.read(note["id"])["body"] == body


def test_scope_applies_before_both_search_channels(manager, db_settings):
    public = manager.capture("学习", "Python 装饰器", "general")
    secret = manager.capture("私人", "Python 装饰器秘密", "life")
    reader = MemoryService(db_settings, Policy("reader", ("general",), "read", "read"), embeddings=manager.embeddings)
    ids = {row["note_id"] for row in reader.search("Python")["results"]}
    assert public["id"] in ids and secret["id"] not in ids
    with pytest.raises(LookupError):
        reader.read(secret["id"])
    with pytest.raises(PermissionError):
        reader.capture("test", "test", "general")


def test_sync_edit_rename_delete_and_no_change(manager):
    note = manager.capture("学习", "原来理解 Python", "learning")
    assert manager.sync()["unchanged"] == 1
    path = Path(note["path"])
    metadata, _ = decode_note(path.read_text(encoding="utf-8"))
    path.write_text(encode_note(metadata, "修正后理解 Python 装饰器"), encoding="utf-8")
    assert manager.search("Python")["stale_results_skipped"] > 0
    with pytest.raises(ValueError):
        manager.read(note["id"])
    assert manager.sync()["indexed"] == 1
    assert "修正后" in manager.read(note["id"])["body"]
    renamed = path.with_name("renamed.md")
    path.rename(renamed)
    assert manager.sync(prune=True)["indexed"] == 1
    assert Path(manager.read(note["id"])["path"]) == renamed
    renamed.unlink()
    assert manager.sync(prune=True)["removed"] == 1
    assert manager.search("Python")["results"] == []


def test_plain_markdown_rename_preserves_identity(manager):
    path = manager.settings.vault / "learning/plain.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Python\n\n学习闭包", encoding="utf-8")
    assert manager.sync()["indexed"] == 1
    identifier = manager.search("Python")["results"][0]["note_id"]
    path.rename(path.with_name("new.md"))
    assert manager.sync(prune=True)["indexed"] == 1
    assert manager.search("Python")["results"][0]["note_id"] == identifier


def test_archive_removes_evidence_and_keeps_original(manager):
    note = manager.capture("生活", "今天吃了晚餐", "life")
    archived = manager.archive(note["id"], 1)
    assert Path(archived["recoverable_file"]).exists()
    assert manager.search("晚餐")["results"] == []
    assert manager.sync()["indexed"] == 0


def test_model_change_requires_reindex(manager):
    manager.capture("Python", "Python学习", "learning")
    manager.embeddings.key = "fixture-v2:3"
    assert manager.search("Python")["compatible_vector_chunks"] == 0
    assert manager.sync()["indexed"] == 1
    assert manager.search("Python")["compatible_vector_chunks"] > 0


def test_failed_embeddings_do_not_change_file_or_database(manager):
    note = manager.capture("Python", "原始 Python", "learning")
    before = Path(note["path"]).read_bytes()
    def fail(texts):
        raise RuntimeError("fixture failure")
    manager.embeddings.embed = fail
    with pytest.raises(RuntimeError):
        manager.append(note["id"], "新内容", 1)
    assert Path(note["path"]).read_bytes() == before
    assert manager.read(note["id"])["revision"] == 1


def test_timeline_pagination_and_summary_sources(manager):
    source = manager.capture("学习", "今天学习Python", "learning", event_date="2026-11-01")
    summary = manager.capture("复盘", "学习了Python", "learning", event_date="2026-11-02", source_type="summary", source_ids=[source["id"]])
    first = manager.timeline("2026-11-01", "2026-11-03", limit=1)
    assert first["next_offset"] == 1
    second = manager.timeline("2026-11-01", "2026-11-03", limit=1, offset=1)
    assert second["results"][0]["id"] == summary["id"]
    assert second["results"][0]["source_ids"] == [source["id"]]


def test_vector_dimension_mismatch_is_rejected(db_settings):
    with pytest.raises(ValueError):
        Database(replace(db_settings, dimensions=4)).initialize()


def test_duplicate_note_id_is_not_allowed(manager):
    note = manager.capture("原文", "Python", "learning")
    original = Path(note["path"])
    original.with_name("duplicate.md").write_bytes(original.read_bytes())
    assert len(manager.sync()["errors"]) == 1
    assert manager.read(note["id"])["revision"] == 1


def test_mcp_stdio_real_protocol(db_settings, tmp_path):
    policy = tmp_path / "reader.toml"
    policy.write_text('name="reader"\nspaces=["general"]\nmaximum_mode="read"\ninitial_mode="off"', encoding="utf-8")
    env = dict(os.environ, PERSONAL_RAG_DATABASE_URL=db_settings.database_url,
               PERSONAL_RAG_VAULT=str(db_settings.vault), PERSONAL_RAG_EMBEDDING_DIMENSIONS="3",
               PERSONAL_RAG_EMBEDDING_PROVIDER="disabled", PYTHONIOENCODING="utf-8")
    async def scenario():
        parameters = StdioServerParameters(command=sys.executable,
            args=[str(ROOT / "scripts/run_mcp.py"), "--connection", str(policy)], env=env)
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert "capture_note" not in {t.name for t in tools.tools}
                assert not (await client.call_tool("memory_status", {})).isError
                assert (await client.call_tool("search_notes", {"query": "Python"})).isError
                assert (await client.call_tool("set_memory_mode", {"mode": "readwrite"})).isError
                assert not (await client.call_tool("set_memory_mode", {"mode": "read"})).isError
                assert not (await client.call_tool("search_notes", {"query": "Python"})).isError
                assert not (await client.call_tool("set_memory_mode", {"mode": "off"})).isError
                assert (await client.call_tool("get_timeline", {"start": "2026-01-01", "end": "2026-12-31"})).isError
    asyncio.run(scenario())


def test_mcp_manager_write_read_and_archive(db_settings, tmp_path):
    policy = tmp_path / "manager.toml"
    policy.write_text('name="manager"\nspaces=["*"]\nmaximum_mode="readwrite"\ninitial_mode="readwrite"\nadmin=true', encoding="utf-8")
    env = dict(os.environ, PERSONAL_RAG_DATABASE_URL=db_settings.database_url,
               PERSONAL_RAG_VAULT=str(db_settings.vault), PERSONAL_RAG_EMBEDDING_DIMENSIONS="3",
               PERSONAL_RAG_EMBEDDING_PROVIDER="disabled", PERSONAL_RAG_RERANK_URL="", PYTHONIOENCODING="utf-8")
    def payload(result):
        assert not result.isError
        return result.structuredContent or json.loads(result.content[0].text)
    async def scenario():
        parameters = StdioServerParameters(command=sys.executable,
            args=[str(ROOT / "scripts/run_mcp.py"), "--connection", str(policy)], env=env)
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                note = payload(await client.call_tool("capture_note", {"title": "MCP记录", "body": "Python学习",
                    "space": "learning", "request_id": str(uuid4())}))
                assert payload(await client.call_tool("read_note", {"note_id": note["id"]}))["body"] == "Python学习"
                updated = payload(await client.call_tool("append_note", {"note_id": note["id"], "text": "理解闭包", "expected_revision": 1}))
                assert updated["revision"] == 2
                assert payload(await client.call_tool("search_notes", {"query": "闭包"}))["results"]
                assert payload(await client.call_tool("archive_note", {"note_id": note["id"], "expected_revision": 2}))["archived"] == note["id"]
    asyncio.run(scenario())


def test_database_index_failure_preserves_existing_note(manager, monkeypatch):
    note = manager.capture("事务验证", "原始Python", "learning")
    original = Path(note["path"]).read_bytes()
    def fail(*args):
        raise RuntimeError("index fixture failure")
    monkeypatch.setattr(manager, "_index", fail)
    with pytest.raises(RuntimeError):
        manager.append(note["id"], "不应保存的新内容", 1)
    assert Path(note["path"]).read_bytes() == original
    assert manager.read(note["id"])["revision"] == 1
    assert manager.search("Python")["results"]
