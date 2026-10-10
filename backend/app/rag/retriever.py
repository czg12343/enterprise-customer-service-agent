from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DocumentChunk, KnowledgeBase, KnowledgeDocument, User
from app.services.knowledge_access import visible_bases

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_-]+|[\u4e00-\u9fff]")
HASH_DIMENSIONS = 384


def tokenize(text: str) -> list[str]:
    """Tokenize Chinese by character and keep English words/numbers intact."""
    return TOKEN_PATTERN.findall(text.lower())


def _bm25(query: list[str], documents: list[list[str]]) -> list[float]:
    if not documents:
        return []
    avgdl = sum(len(document) for document in documents) / len(documents) or 1
    doc_frequency = Counter(
        token for token in set(query) for document in documents if token in set(document)
    )
    scores: list[float] = []
    for document in documents:
        frequencies = Counter(document)
        score = 0.0
        for token in query:
            df = doc_frequency[token]
            if not df:
                continue
            idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
            tf = frequencies[token]
            score += idf * (tf * 2.2) / (
                tf + 1.2 * (0.25 + 0.75 * len(document) / avgdl)
            )
        scores.append(score)
    return scores


def _hash_vector(tokens: list[str], dimensions: int = HASH_DIMENSIONS) -> dict[int, float]:
    """Build a deterministic, dependency-free feature vector.

    This is deliberately described as a hashed lexical vector, not as an Embedding model.
    It adds a second retrieval signal without network access or model downloads.
    """
    vector: Counter[int] = Counter()
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    return dict(vector)


def _cosine(left: dict[int, float], right: dict[int, float]) -> float:
    if not left or not right:
        return 0.0
    common = left.keys() & right.keys()
    dot = sum(left[index] * right[index] for index in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def reciprocal_rank_fusion(rankings: list[list[str]], constant: int = 60) -> dict[str, float]:
    fused: Counter[str] = Counter()
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, 1):
            fused[item_id] += 1 / (constant + rank)
    return dict(fused)


def hybrid_search(db: Session, query: str, limit: int = 5, *, user: User | None = None, base_id: str | None = None) -> list[dict]:
    rows = list(
        db.execute(
            select(DocumentChunk, KnowledgeDocument.filename)
            .join(KnowledgeDocument, KnowledgeDocument.id == DocumentChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == DocumentChunk.knowledge_base_id)
            .where(visible_bases(user), KnowledgeDocument.status == "ready")
            .where(DocumentChunk.knowledge_base_id == base_id if base_id else True)
            .order_by(DocumentChunk.id)
            .limit(2000)
        ).all()
    )
    if not rows:
        return []

    query_tokens = tokenize(query)
    document_tokens = [tokenize(chunk.content) for chunk, _ in rows]
    bm25_scores = _bm25(query_tokens, document_tokens)
    lexical_scores = [
        _cosine(_hash_vector(query_tokens), _hash_vector(tokens)) for tokens in document_tokens
    ]
    candidate_limit = min(settings.rag_candidate_limit, len(rows))
    bm25_ranking = [
        rows[index][0].id
        for index in sorted(range(len(rows)), key=bm25_scores.__getitem__, reverse=True)
        if bm25_scores[index] > 0
    ][:candidate_limit]
    vector_ranking = [
        rows[index][0].id
        for index in sorted(range(len(rows)), key=lexical_scores.__getitem__, reverse=True)
        if lexical_scores[index] > 0
    ][:candidate_limit]
    fused = reciprocal_rank_fusion([bm25_ranking, vector_ranking])
    row_by_id = {chunk.id: (index, chunk, filename) for index, (chunk, filename) in enumerate(rows)}
    ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:limit]

    results: list[dict] = []
    for chunk_id, rrf_score in ranked:
        index, chunk, filename = row_by_id[chunk_id]
        results.append(
            {
                "document": filename,
                "document_id": chunk.document_id,
                "chunk_id": chunk.id,
                "page": chunk.page_number,
                "section": chunk.section,
                "snippet": chunk.content[:360],
                "score": round(float(rrf_score), 6),
                "content": chunk.content,
                "retrieval": {
                    "bm25_score": round(float(bm25_scores[index]), 4),
                    "hashed_vector_score": round(float(lexical_scores[index]), 4),
                    "rrf_score": round(float(rrf_score), 6),
                    "strategy": "bm25+hashed-vector+rrf",
                },
            }
        )
    return results
