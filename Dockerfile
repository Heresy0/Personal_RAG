FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PERSONAL_RAG_HOME=/app \
    PERSONAL_RAG_VAULT=/data/vault

WORKDIR /app
COPY requirements.lock.txt pyproject.toml ./
RUN python -m pip install --no-cache-dir -r requirements.lock.txt
COPY src/ ./src/
RUN python -m pip install --no-cache-dir --no-deps . \
    && useradd --uid 1000 --create-home rag \
    && mkdir -p /data/vault /connections \
    && chown -R rag:rag /data /app

USER rag
ENTRYPOINT ["personal-rag"]
CMD ["--connection", "/connections/example-readonly.toml", "mcp"]
