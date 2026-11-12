from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from .config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings

    def initialize(self):
        dimension = int(self.settings.dimensions)
        if not 1 <= dimension <= 2000:
            raise ValueError("向量维度无效")
        with psycopg.connect(self.settings.database_url) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(72021001)")
            conn.execute("CREATE TABLE IF NOT EXISTS rag_meta (key text PRIMARY KEY, value text NOT NULL)")
            existing = conn.execute("SELECT value FROM rag_meta WHERE key='dimensions'").fetchone()
            if existing and int(existing[0]) != dimension:
                raise ValueError("数据库向量维度与配置不一致；请使用新数据库迁移")
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            conn.execute(schema.replace("__DIMENSIONS__", str(dimension)))
            conn.execute("INSERT INTO rag_meta(key,value) VALUES ('dimensions',%s) ON CONFLICT DO NOTHING", (str(dimension),))

    def connect(self):
        conn = psycopg.connect(self.settings.database_url, row_factory=dict_row, connect_timeout=5)
        try:
            register_vector(conn)
            conn.execute("SET statement_timeout = '15s'")
            conn.commit()
            return conn
        except Exception:
            conn.close()
            raise
