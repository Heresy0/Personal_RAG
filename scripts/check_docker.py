"""Real container MCP acceptance against an isolated test DB; no paid model calls."""
import asyncio
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from psycopg import sql

from personal_rag.config import ROOT, Settings


def payload(result):
    assert not result.isError, "MCP operation failed"
    return result.structuredContent or json.loads(result.content[0].text)


def main():
    settings = Settings.load()
    parsed = urlsplit(settings.database_url)
    if parsed.hostname != "127.0.0.1" or parsed.port != 55432 or parsed.path != "/personal_rag":
        raise SystemExit("只允许 Personal_RAG 独立本机数据库")
    name = "personal_rag_test_docker_" + uuid4().hex[:10]
    admin_url = urlunsplit(parsed._replace(path="/postgres"))
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    image = os.environ.get("PERSONAL_RAG_TEST_IMAGE", "ghcr.io/heresy0/personal_rag:0.4.0")
    environment = dict(os.environ, PERSONAL_RAG_IMAGE=image, PERSONAL_RAG_DATABASE_URL=urlunsplit(parsed._replace(
        netloc=parsed.netloc.rsplit("@", 1)[0] + "@postgres:5432", path="/" + name)))
    base = ["compose", "--project-directory", str(ROOT), "-f", str(ROOT / "compose.yaml"),
            "-f", str(ROOT / "compose.docker.yaml"), "run", "--rm", "--no-deps", "-T",
            "-e", "PERSONAL_RAG_DATABASE_URL", "-e", "PERSONAL_RAG_EMBEDDING_PROVIDER=disabled",
            "-e", "PERSONAL_RAG_EMBEDDING_DIMENSIONS=3", "-e", "PERSONAL_RAG_RERANK_URL="]
    try:
        (ROOT / "output").mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="docker-test-", dir=ROOT / "output") as temp:
            # Compose 2.31 ignores run -v for an existing mount target; merge an explicit override instead.
            overlay = Path(temp) / "compose.test.json"
            overlay.write_text(json.dumps({"services": {"mcp": {"volumes": [{"type": "bind",
                "source": str(Path(temp).resolve()), "target": "/data/vault"}, {"type":"bind",
                "source": str(Path(temp).resolve()), "target":"/data/logs"}]}}}), encoding="utf-8")
            run_index = base.index("run")
            args = base[:run_index] + ["-f", str(overlay)] + base[run_index:] + ["mcp"]
            subprocess.run(["docker", *args, "init"], env=environment, check=True, capture_output=True)

            async def manager_scenario():
                parameters = StdioServerParameters(command="docker", args=[*args,
                    "--connection", "/connections/manager.toml", "mcp"], env=environment)
                async with stdio_client(parameters) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        assert payload(await client.call_tool("memory_status", {}))["mode"] == "readwrite"
                        note = payload(await client.call_tool("capture_note", {"title": "容器验收", "body": "Python 装饰器与闭包",
                            "space": "learning", "request_id": str(uuid4())}))
                        result = payload(await client.call_tool("search_notes", {"query": "闭包"}))
                        assert result["results"][0]["note_id"] == note["id"]
                        assert payload(await client.call_tool("read_note", {"note_id": note["id"]}))["body"] == "Python 装饰器与闭包"
                        updated = payload(await client.call_tool("append_note", {"note_id": note["id"], "text": "下一步阅读源码", "expected_revision": 1}))
                        assert updated["revision"] == 2
                        audit = payload(await client.call_tool('list_write_audit', {'note_id':note['id']}))
                        assert len(audit['results']) == 4
                        assert {row['after_revision'] for row in audit['results']} == {1, 2}
                        version = payload(await client.call_tool('read_note_version', {'note_id':note['id'], 'revision':1}))
                        assert version['body'] == 'Python 装饰器与闭包'
                        assert (await client.call_tool('append_note', {'note_id':note['id'], 'text':'conflict', 'expected_revision':1})).isError
                        audit = payload(await client.call_tool('list_write_audit', {'outcome':'failure'}))
                        assert audit['results'][0]['operation'] == 'append'
                        payload(await client.call_tool("set_memory_mode", {"mode": "off"}))
                        assert (await client.call_tool("search_notes", {"query": "Python"})).isError
                        # MCP paths refer to the container; confirm original is persisted on host.
                        files = list(Path(temp).rglob("*.md"))
                        assert len(files) == 1, f"Host mount file count: {len(files)}"
                        assert "下一步阅读源码" in files[0].read_text(encoding="utf-8"), "Appended text missing from host file"

            async def reader_scenario():
                parameters = StdioServerParameters(command="docker", args=[*args,
                    "--connection", "/connections/example-readonly.toml", "mcp"], env=environment)
                async with stdio_client(parameters) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        assert not {'capture_note', 'list_write_audit', 'read_note_version'}.intersection({t.name for t in (await client.list_tools()).tools})
                        assert (await client.call_tool("search_notes", {"query": "Python"})).isError
                        assert (await client.call_tool("set_memory_mode", {"mode": "readwrite"})).isError
                        payload(await client.call_tool("set_memory_mode", {"mode": "read"}))
                        result = payload(await client.call_tool("search_notes", {"query": "Python"}))
                        assert result["results"] == [], "Private learning space leaked to reader"

            asyncio.run(manager_scenario())
            asyncio.run(reader_scenario())
        report = {"passed": True, "image": image, "transport": "compose run / stdio",
                  "checks": ["db initialization", "MCP handshake", "capture", "search", "read", "append",
                             "host volume persistence", "off mode", "readonly tools", "mode ceiling", "space isolation",
                             "write audit", "historical version", "failed write audit"],
                  "external_model_calls": 0}
        (ROOT / "output/docker-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


if __name__ == "__main__":
    main()
