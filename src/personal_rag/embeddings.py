import math

import httpx

from .config import Settings


class Embeddings:
    """Explicit opt-in OpenAI-compatible embeddings. No implicit provider fallback."""
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.embedding_provider not in {"disabled", "openai-compatible"}:
            raise ValueError("不支持的 embedding provider")
        self.enabled = settings.embedding_provider != "disabled"
        self.key = f"{settings.embedding_url}|{settings.embedding_model}|{settings.dimensions}"
        if self.enabled and not all([settings.embedding_url, settings.embedding_model, settings.embedding_api_key]):
            raise ValueError("启用向量生成前须配置 URL、模型和 API key")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.enabled:
            return []
        results = []
        for offset in range(0, len(texts), 16):
            batch = texts[offset:offset + 16]
            response = httpx.post(self.settings.embedding_url, timeout=45,
                headers={"Authorization": f"Bearer {self.settings.embedding_api_key}"},
                json={"model": self.settings.embedding_model, "input": batch,
                      "dimensions": self.settings.dimensions})
            response.raise_for_status()
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            if [row["index"] for row in rows] != list(range(len(batch))):
                raise ValueError("嵌入响应索引不完整")
            for row in rows:
                vector = row["embedding"]
                if (len(vector) != self.settings.dimensions or not all(math.isfinite(x) for x in vector)
                        or not any(vector)):
                    raise ValueError("嵌入维度、数值或长度无效")
                results.append(vector)
        return results
