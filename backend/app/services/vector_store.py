"""Vector store using LangChain PGVector and PostgreSQL + pgvector."""

from __future__ import annotations

import logging
import math
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session

from app.models.document import Base, DocumentChunkModel, DocumentModel

logger = logging.getLogger(__name__)


def init_db(engine: Engine) -> None:
    """Create database tables and ensure vector extension is available."""
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
        Base.metadata.create_all(engine)
    except Exception as exc:
        logger.warning("Could not initialize database tables: %s", exc)


class LangChainPGVectorStore:
    """LangChain PGVector wrapper for document chunk ingestion and similarity search."""

    def __init__(
        self,
        session: Session,
        embeddings: Embeddings,
        connection_url: str,
        collection_name: str = "document_chunks",
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.connection_url = connection_url
        self.collection_name = collection_name
        self._pgvector: PGVector | None = None

    def _get_pgvector(self) -> PGVector | None:
        """Lazily initialize LangChain PGVector vectorstore."""
        if self._pgvector is None:
            try:
                self._pgvector = PGVector(
                    embeddings=self.embeddings,
                    collection_name=self.collection_name,
                    connection=self.connection_url,
                    embedding_length=getattr(self.embeddings, "dim", 1024),
                    use_jsonb=True,
                    create_extension=False,
                )
            except Exception as exc:
                logger.warning("Could not connect to LangChain PGVector: %s", exc)
        return self._pgvector

    def save_document(
        self,
        doc_id: str,
        code: str | None = None,
        title: str | None = None,
        doc_type: str = "internal",
        issuer: str | None = None,
        effective_date: str | None = None,
        page_count: int = 0,
        pdf_url: str | None = None,
    ) -> DocumentModel:
        """Upsert document record."""
        doc = self.session.get(DocumentModel, doc_id)
        if not doc:
            doc = DocumentModel(id=doc_id)
            self.session.add(doc)

        doc.code = code
        doc.title = title
        doc.doc_type = doc_type
        doc.issuer = issuer
        doc.effective_date = effective_date
        doc.page_count = page_count
        doc.pdf_url = pdf_url

        self.session.commit()
        self.session.refresh(doc)
        return doc

    def save_chunks_with_langchain(
        self,
        doc_id: str,
        chunks_data: list[dict[str, Any]],
    ) -> list[DocumentChunkModel]:
        """Ingest chunks using LangChain Document abstractions into pgvector."""
        # Clean previous chunks for this document
        self.session.execute(delete(DocumentChunkModel).where(DocumentChunkModel.doc_id == doc_id))

        # 1. Prepare LangChain Document objects
        langchain_docs: list[Document] = []
        doc_ids: list[str] = []
        for c in chunks_data:
            meta = {
                "doc_id": doc_id,
                "doc_code": c.get("code"),
                "doc_title": c.get("title"),
                "doc_type": c.get("doc_type", "internal"),
                "issuer": c.get("issuer"),
                "effective_date": c.get("effective_date"),
                "article_path": c.get("article_path"),
                "page": c["page"],
                "bbox": c["bbox"],
                **(c.get("metadata") or c.get("chunk_metadata") or {}),
            }
            langchain_docs.append(
                Document(
                    page_content=c["text"],
                    metadata=meta,
                    id=c["chunk_id"],
                )
            )
            doc_ids.append(c["chunk_id"])

        # 2. Ingest into LangChain PGVector if available
        pgv = self._get_pgvector()
        if pgv:
            try:
                pgv.add_documents(documents=langchain_docs, ids=doc_ids)
            except Exception as exc:
                logger.warning("LangChain PGVector add_documents failed: %s", exc)

        # 3. Synchronize with DocumentChunkModel table for queries
        models: list[DocumentChunkModel] = []
        for c in chunks_data:
            chunk = DocumentChunkModel(
                id=c["chunk_id"],
                doc_id=doc_id,
                doc_type=c.get("doc_type", "internal"),
                issuer=c.get("issuer"),
                effective_date=c.get("effective_date"),
                article_path=c.get("article_path"),
                page=c["page"],
                bbox=c["bbox"],
                text=c["text"],
                embedding=c.get("embedding"),
                chunk_metadata=c.get("chunk_metadata") or c.get("metadata"),
            )
            models.append(chunk)

        self.session.add_all(models)
        self.session.commit()
        return models

    def get_document(self, doc_id: str) -> DocumentModel | None:
        """Fetch a document by ID."""
        return self.session.get(DocumentModel, doc_id)

    def list_documents(self, doc_type: str | None = None) -> list[DocumentModel]:
        """List documents, optionally filtered by doc_type."""
        stmt = select(DocumentModel)
        if doc_type:
            stmt = stmt.where(DocumentModel.doc_type == doc_type)
        stmt = stmt.order_by(DocumentModel.created_at.desc())
        return list(self.session.execute(stmt).scalars().all())

    def get_chunks(self, doc_id: str) -> list[DocumentChunkModel]:
        """Fetch all chunks for a document."""
        stmt = (
            select(DocumentChunkModel)
            .where(DocumentChunkModel.doc_id == doc_id)
            .order_by(DocumentChunkModel.page, DocumentChunkModel.id)
        )
        return list(self.session.execute(stmt).scalars().all())

    def similarity_search_langchain(
        self,
        query: str,
        top_k: int = 5,
        doc_type: str | None = None,
        doc_id: str | None = None,
    ) -> list[tuple[DocumentChunkModel, float]]:
        """Search similar chunks using LangChain similarity_search_with_score."""
        pgv = self._get_pgvector()
        if pgv:
            filter_dict: dict[str, Any] = {}
            if doc_type:
                filter_dict["doc_type"] = doc_type
            if doc_id:
                filter_dict["doc_id"] = doc_id

            try:
                results = pgv.similarity_search_with_score(
                    query=query,
                    k=top_k,
                    filter=filter_dict if filter_dict else None,
                )
                output = []
                for doc, score in results:
                    chunk_id = doc.id or doc.metadata.get("id")
                    chunk_model = self.session.get(DocumentChunkModel, chunk_id)
                    if chunk_model:
                        output.append((chunk_model, float(score)))
                if output:
                    return output
            except Exception as exc:
                logger.warning("LangChain PGVector similarity search failed: %s", exc)

        # Fallback query
        query_vector = self.embeddings.embed_query(query)
        stmt = select(DocumentChunkModel).where(DocumentChunkModel.embedding.is_not(None))
        if doc_type:
            stmt = stmt.where(DocumentChunkModel.doc_type == doc_type)
        if doc_id:
            stmt = stmt.where(DocumentChunkModel.doc_id == doc_id)

        chunks = list(self.session.execute(stmt).scalars().all())
        scored: list[tuple[DocumentChunkModel, float]] = []
        q_norm = math.sqrt(sum(x * x for x in query_vector))

        for chunk in chunks:
            if not chunk.embedding:
                continue
            emb = list(chunk.embedding)
            dot = sum(a * b for a, b in zip(emb, query_vector, strict=False))
            emb_norm = math.sqrt(sum(x * x for x in emb))
            sim = dot / (q_norm * emb_norm) if (q_norm * emb_norm) > 0 else 0.0
            scored.append((chunk, float(sim)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
