"""Create local credentials without printing secrets; never reads enterprise config."""
import secrets
from pathlib import Path

from personal_rag.config import ROOT
from personal_rag.connections import codex_config

env = ROOT / ".env"
if not env.exists():
    password = secrets.token_hex(24)
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    with env.open("x", encoding="utf-8") as stream:
        stream.write(template.replace("REPLACE_ME", password) + f"\nPERSONAL_RAG_DB_PASSWORD={password}\n")
config = ROOT / "knowledge_workspace/.codex/config.toml"
config.parent.mkdir(parents=True, exist_ok=True)
if not config.exists():
    config.write_text(codex_config(ROOT / "config/connections/manager.toml"), encoding="utf-8")
print("Local configuration prepared; credentials were not printed.")
