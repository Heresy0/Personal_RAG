"""Run unit + isolated PG + real MCP tests; credentials never enter command arguments."""
import os
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

from personal_rag.config import ROOT, Settings

settings = Settings.load()
parsed = urlsplit(settings.database_url)
if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55432 or parsed.path != "/personal_rag":
    raise SystemExit("检查只允许本项目的独立本地数据库")
env = dict(os.environ, PERSONAL_RAG_TEST_DATABASE_URL=urlunsplit(parsed._replace(path="/personal_rag_test")),
           PYTHONIOENCODING="utf-8")
(ROOT / "output").mkdir(exist_ok=True)
result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--junitxml=output/tests.xml"],
                        cwd=ROOT, env=env)
raise SystemExit(result.returncode)
