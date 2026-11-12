"""Weighted RRF adapted from enterprise hybrid_retriever.py; no global corpus cache."""
import logging

import httpx
from rank_bm25 import BM25Okapi

from .extracted.keyword_tokenizer import tokenize_chinese


def keyword_rank(query, rows, limit=30):
    tokens = tokenize_chinese(query)
    if not rows or not tokens:
        return []
    corpus = [tokenize_chinese(row["content"]) or ["__empty__"] for row in rows]
    scores = BM25Okapi(corpus).get_scores(tokens)
    query_set = set(tokens)
    hits = [(row, float(score)) for row, words, score in zip(rows, corpus, scores)
            if query_set.intersection(words)]
    return [dict(row, keyword_score=score) for row, score in
            sorted(hits, key=lambda pair: (-pair[1], str(pair[0]["id"])))[:limit]]


def fuse(vector, keyword, limit=30):
    scores, documents = {}, {}
    for rows, weight in ((vector, 0.6), (keyword, 0.4)):
        seen = set()
        for rank, row in enumerate(rows, 1):
            key = str(row["id"])
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0) + weight / (60 + rank)
            documents.setdefault(key, row)
    return [dict(documents[key], rrf_score=scores[key])
            for key in sorted(scores, key=lambda key: (-scores[key], key))[:limit]]


def rerank(query, rows, settings):
    if not settings.rerank_url or not rows:
        return rows, "disabled"
    try:
        response = httpx.post(settings.rerank_url, timeout=15,
            headers={"Authorization": f"Bearer {settings.rerank_api_key}"},
            json={"model": settings.rerank_model, "query": query,
                  "documents": [row["content"] for row in rows], "top_n": len(rows)})
        response.raise_for_status()
        results = response.json()["results"]
        indices = [r["index"] for r in results]
        if sorted(indices) != list(range(len(rows))):
            raise ValueError("Invalid rerank indices")
        return [dict(rows[r["index"]], rerank_score=r["relevance_score"]) for r in results], "success"
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logging.getLogger(__name__).warning("重排不可用，保留 RRF 排序")
        return rows, "fallback"
