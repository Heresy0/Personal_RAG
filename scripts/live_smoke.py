"""Small, explicit real-provider acceptance; uses isolated DB, never writes user notes."""
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from personal_rag.config import Policy, ROOT, Settings
from personal_rag.db import Database
from personal_rag.service import MemoryService


def main():
    settings = Settings.load()
    parsed = urlsplit(settings.database_url)
    if parsed.hostname != "127.0.0.1" or parsed.port != 55432 or parsed.path != "/personal_rag":
        raise SystemExit("只允许本项目独立地址")
    name = "personal_rag_test_live_" + uuid4().hex[:10]
    admin_url = urlunsplit(parsed._replace(path="/postgres"))
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    report = {"embedding_model": settings.embedding_model, "rerank_model": settings.rerank_model,
              "primary_generation_model": None, "scope": "isolated synthetic acceptance, not accuracy evaluation"}
    try:
        with TemporaryDirectory(prefix="personal-rag-live-") as temp:
            isolated = replace(settings, database_url=urlunsplit(parsed._replace(path="/" + name)), vault=Path(temp))
            Database(isolated).initialize()
            service = MemoryService(isolated, Policy("acceptance", ("*",), "readwrite", "readwrite", True))
            note = service.capture("学习记录", "今天学习 Python 装饰器，下一步理解闭包。", "learning", event_date="2026-11-12")
            result = service.search("之前学过哪些 Python 相关知识？")
            assert result["compatible_vector_chunks"] > 0
            assert result["rerank"] == "success"
            assert result["results"] and result["results"][0]["note_id"] == note["id"]
            assert service.read(note["id"])["source_type"] == "original"
            report.update(passed=True, indexed_chunks=result["indexed_chunks"],
                          compatible_vector_chunks=result["compatible_vector_chunks"], rerank=result["rerank"],
                          results=len(result["results"]), note_read=True,
                          requested_embedding_batches=2, requested_rerank_calls=1,
                          cost="unknown; provider billing applies")
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
    (ROOT / "output/live-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
