from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(os.environ.get("PERSONAL_RAG_HOME", Path(__file__).resolve().parents[2])).resolve()
MODES = {"off": 0, "read": 1, "readwrite": 2}
SPACE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate_space(value: str) -> str:
    if not SPACE.fullmatch(value):
        raise ValueError("资料空间须为小写英文、数字、下划线或连字符，最多64字符")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    vault: Path
    dimensions: int = 1024
    embedding_provider: str = "disabled"
    embedding_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = field(default="", repr=False)
    rerank_url: str = ""
    rerank_model: str = ""
    rerank_api_key: str = field(default="", repr=False)
    audit_dir: Path | None = None

    @classmethod
    def load(cls):
        load_dotenv(ROOT / ".env", override=False)
        prefix = "PERSONAL_RAG_"
        url = os.environ.get(prefix + "DATABASE_URL", "")
        if not url:
            raise ValueError("请先运行 scripts/setup.ps1 或配置 PERSONAL_RAG_DATABASE_URL")
        vault = Path(os.environ.get(prefix + "VAULT", "knowledge_workspace/vault"))
        if not vault.is_absolute():
            vault = ROOT / vault
        dimensions = int(os.environ.get(prefix + "EMBEDDING_DIMENSIONS", "1024"))
        if not 1 <= dimensions <= 2000:
            raise ValueError("向量维度须为1到2000")
        names = ["embedding_provider", "embedding_url", "embedding_model", "embedding_api_key",
                 "rerank_url", "rerank_model", "rerank_api_key"]
        values = {key: os.environ.get(prefix + key.upper(), "disabled" if key == "embedding_provider" else "")
                  for key in names}
        audit_dir = Path(os.environ.get(prefix + "AUDIT_DIR", str(vault.parent / 'logs')))
        if not audit_dir.is_absolute():
            audit_dir = ROOT / audit_dir
        return cls(url, vault.resolve(), dimensions, **values, audit_dir=audit_dir.resolve())


@dataclass(frozen=True)
class Policy:
    name: str
    spaces: tuple[str, ...]
    maximum_mode: str = "read"
    initial_mode: str = "off"
    admin: bool = False

    def __post_init__(self):
        if self.maximum_mode not in MODES or self.initial_mode not in MODES:
            raise ValueError("未知记忆模式")
        if MODES[self.initial_mode] > MODES[self.maximum_mode]:
            raise ValueError("初始模式超过连接权限")
        if not self.spaces or ("*" in self.spaces and not self.admin):
            raise ValueError("只有管理连接可以使用全部空间")
        for space in self.spaces:
            if space != "*":
                validate_space(space)

    @classmethod
    def load(cls, path: Path):
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        return cls(name=data["name"], spaces=tuple(data["spaces"]),
                   maximum_mode=data.get("maximum_mode", "read"),
                   initial_mode=data.get("initial_mode", "off"), admin=data.get("admin", False))

    def permits(self, space: str):
        return space in self.spaces or (self.admin and "*" in self.spaces)
