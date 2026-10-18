"""Optional cross-encoder reranker (design section 05.6) through a Cohere/Jina-style API.

POST {RERANK_BASE_URL}/rerank {"model", "query", "documents", "top_n"} →
{"results": [{"index", "relevance_score"}]}. OpenRouter, vLLM and Jina serve this shape.
Disabled when RERANK_BASE_URL or RERANK_MODEL is empty.
"""

from app.config import get_settings
from app.ria.http_retry import post_json


def rerank_model() -> str | None:
    settings = get_settings()
    if not (settings.rerank_base_url and settings.rerank_model):
        return None
    return settings.rerank_model


def rerank(query: str, documents: list[str], timeout: float = 60) -> list[float]:
    """Relevance score of each document for the query, in input order."""
    if not documents:
        return []
    settings = get_settings()
    data = post_json(
        f"{settings.rerank_base_url.rstrip('/')}/rerank",
        headers={"Authorization": f"Bearer {settings.rerank_api_key or 'EMPTY'}"},
        json={
            "model": settings.rerank_model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        },
        timeout=timeout,
    )
    scores = [0.0] * len(documents)
    for item in data["results"]:
        scores[item["index"]] = float(item["relevance_score"])
    return scores
