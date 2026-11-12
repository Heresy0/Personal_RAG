"""User-authorized, narrow read of enterprise model settings; writes only this project."""
from dotenv import dotenv_values, set_key

from personal_rag.config import ROOT

source = dotenv_values("D:/code/Enterprise_knowladge/.env")
required = ["DASHSCOPE_BASE_URL", "DASHSCOPE_API_KEY", "DASHSCOPE_EMBEDDING_MODEL",
            "DASHSCOPE_RERANK_MODEL", "DASHSCOPE_RERANK_URL"]
if any(not source.get(key) for key in required):
    raise SystemExit("原项目模型配置不完整，未导入")
base = source["DASHSCOPE_BASE_URL"].rstrip("/")
values = {
    "PERSONAL_RAG_EMBEDDING_PROVIDER": "openai-compatible",
    "PERSONAL_RAG_EMBEDDING_URL": base + "/embeddings",
    "PERSONAL_RAG_EMBEDDING_MODEL": source["DASHSCOPE_EMBEDDING_MODEL"],
    "PERSONAL_RAG_EMBEDDING_DIMENSIONS": "1024",
    "PERSONAL_RAG_EMBEDDING_API_KEY": source["DASHSCOPE_API_KEY"],
    "PERSONAL_RAG_RERANK_URL": source["DASHSCOPE_RERANK_URL"],
    "PERSONAL_RAG_RERANK_MODEL": source["DASHSCOPE_RERANK_MODEL"],
    "PERSONAL_RAG_RERANK_API_KEY": source["DASHSCOPE_API_KEY"],
}
for key, value in values.items():
    set_key(ROOT / ".env", key, value)
print("Imported embedding and rerank configuration. No primary generation model configured.")
