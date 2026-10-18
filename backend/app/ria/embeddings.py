"""Optional dense embeddings through an OpenAI-compatible /embeddings endpoint.

Disabled when EMBEDDING_BASE_URL is empty: retrieval then runs sparse-only and says so in the
job result. Vectors are tagged with the model id so different vector spaces never mix.
"""

import httpx

from app.config import get_settings


def embedding_version() -> str | None:
    settings = get_settings()
    if not (settings.embedding_base_url and settings.embedding_model):
        return None
    return settings.embedding_model


def embed(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.embedding_api_key or 'EMPTY'}"}
    url = f"{settings.embedding_base_url.rstrip('/')}/embeddings"
    vectors: list[list[float]] = []
    with httpx.Client(timeout=60) as client:
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = client.post(
                url, headers=headers, json={"model": settings.embedding_model, "input": batch}
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            vectors.extend(d["embedding"] for d in data)
    for v in vectors:
        if len(v) != settings.embedding_dim:
            raise ValueError(f"embedding dim {len(v)} != EMBEDDING_DIM {settings.embedding_dim}")
    return vectors


def to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
