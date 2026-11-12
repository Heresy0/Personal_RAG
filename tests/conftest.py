import os
from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from personal_rag.config import Policy, Settings
from personal_rag.db import Database
from personal_rag.service import MemoryService


@pytest.fixture(scope="session")
def test_database():
    url = os.environ.get("PERSONAL_RAG_TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 PERSONAL_RAG_TEST_DATABASE_URL 指向独立 personal_rag_test 数据库前缀")
    parsed = urlsplit(url)
    if (parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432
            or not parsed.path.lstrip("/").startswith("personal_rag_test")):
        pytest.fail("拒绝使用非 Personal_RAG 隔离测试地址")
    name = "personal_rag_test_" + uuid4().hex[:12]
    admin_url = urlunsplit(parsed._replace(path="/postgres"))
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    actual = urlunsplit(parsed._replace(path="/" + name))
    settings = Settings(actual, __import__('pathlib').Path('.'), dimensions=3)
    Database(settings).initialize()
    try:
        yield actual
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def db_settings(test_database, tmp_path):
    settings = Settings(test_database, tmp_path / "vault", dimensions=3)
    with Database(settings).connect() as conn:
        conn.execute("TRUNCATE notes CASCADE")
    return settings


class DeterministicEmbeddings:
    """Protocol/integration fixture, not a real semantic model."""
    enabled = True
    key = "fixture-v1:3"

    def embed(self, texts):
        return [[1., 0., 0.] if "Python" in text or "装饰器" in text else [0., 1., 0.] for text in texts]


@pytest.fixture
def manager(db_settings):
    return MemoryService(db_settings, Policy("manager", ("*",), "readwrite", "readwrite", True),
                         embeddings=DeterministicEmbeddings())
