from __future__ import annotations

import pytest

from app.core.database import SessionLocal
from app.rag.retriever import _cosine, _hash_vector, hybrid_search, reciprocal_rank_fusion, tokenize


def test_hashed_vector_is_deterministic_and_dependency_free():
    first = _hash_vector(tokenize("七天退货 policy"))
    second = _hash_vector(tokenize("七天退货 policy"))

    assert first == second
    assert _cosine(first, second) == pytest.approx(1.0)


def test_rrf_combines_bm25_and_hashed_vector_rankings():
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], constant=60)

    assert fused["b"] > fused["a"]
    assert fused["b"] > fused["c"]


def test_hybrid_search_exposes_honest_retrieval_trace(client):
    with SessionLocal() as db:
        results = hybrid_search(db, "保修政策", limit=3)

    assert results
    assert results[0]["retrieval"]["strategy"] == "bm25+hashed-vector+rrf"
    assert "bm25_score" in results[0]["retrieval"]
    assert "hashed_vector_score" in results[0]["retrieval"]
