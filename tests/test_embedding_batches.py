import httpx
import pytest

from personal_rag.config import Settings
from personal_rag.embeddings import Embeddings, EmbeddingRequestError


def settings(tmp_path):
    return Settings('unused', tmp_path, dimensions=3, embedding_provider='openai-compatible',
        embedding_url='https://fixture.invalid/embeddings', embedding_model='text-embedding-v4',
        embedding_api_key='PRIVATE_KEY')


def test_provider_ten_input_limit_and_order_across_batches(tmp_path, monkeypatch):
    batches = []
    def post(url, *, json, **kwargs):
        batch = json['input']
        batches.append(len(batch))
        if len(batch) > 10:
            return httpx.Response(400, json={'error':'batch too large'})
        return httpx.Response(200, json={'data':[
            {'index':i, 'embedding':[float(text), 1., 0.]} for i,text in reversed(list(enumerate(batch)))]})
    monkeypatch.setattr('personal_rag.embeddings.httpx.post', post)
    vectors = Embeddings(settings(tmp_path)).embed([str(i) for i in range(23)])
    assert batches == [10,10,3]
    assert [row[0] for row in vectors] == list(range(23))


def test_http_error_safe_message_excludes_provider_body(tmp_path, monkeypatch):
    monkeypatch.setattr('personal_rag.embeddings.httpx.post', lambda *a, **kw:
        httpx.Response(400, json={'error':'PRIVATE_KEY PRIVATE_NOTE'}))
    with pytest.raises(EmbeddingRequestError) as caught:
        Embeddings(settings(tmp_path)).embed(['PRIVATE_NOTE'])
    assert 'HTTP 400' in str(caught.value) and 'PRIVATE' not in str(caught.value)
