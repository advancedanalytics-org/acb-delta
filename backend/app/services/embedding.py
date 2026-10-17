"""LangChain Embeddings adapter for embedding API with offline fallback.

Supports OpenAI-compatible endpoints (TEI, vLLM, GreenNode MaaS) and deterministic offline fallback.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


class LangChainEmbeddingService(Embeddings):
    """LangChain Embeddings implementation supporting remote embedding API and offline fallback."""

    def __init__(
        self,
        base_url: str = "",
        model: str = "",
        api_key: str = "",
        dim: int = 1024,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.model = model or "BAAI/bge-m3"
        self.api_key = api_key or "EMPTY"
        self.dim = dim

        self._remote_model: OpenAIEmbeddings | None = None
        if self.base_url:
            try:
                self._remote_model = OpenAIEmbeddings(
                    model=self.model,
                    openai_api_base=self.base_url,
                    openai_api_key=self.api_key,
                    check_embedding_ctx_length=False,
                )
            except Exception as exc:
                logger.warning("Could not initialize OpenAIEmbeddings: %s", exc)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document chunk texts using LangChain."""
        if not texts:
            return []

        if self._remote_model:
            try:
                return self._remote_model.embed_documents(texts)
            except Exception as exc:
                logger.warning(
                    "Remote embedding API call failed (%s); using offline generator: %s",
                    self.base_url,
                    exc,
                )

        return [self._generate_offline_embedding(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        """Embed a query text using LangChain."""
        if self._remote_model:
            try:
                return self._remote_model.embed_query(text)
            except Exception as exc:
                logger.warning(
                    "Remote query embedding API call failed (%s); using offline generator: %s",
                    self.base_url,
                    exc,
                )

        return self._generate_offline_embedding(text)

    def _generate_offline_embedding(self, text: str) -> list[float]:
        """Deterministic, unit-normalized vector generator for offline/local dev."""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], byteorder="big")
        rng = random.Random(seed)

        vec = [rng.gauss(0.0, 1.0) for _ in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec
