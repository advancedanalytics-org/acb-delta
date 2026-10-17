"""Endpoints for uploading, chunking, and ingesting PDF documents into vectorDB using LangChain."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.schemas import (
    ChunkResponse,
    DocumentResponse,
    IngestResponse,
    SearchRequest,
    SearchResult,
)
from app.services.chunker import chunk_pdf
from app.services.embedding import LangChainEmbeddingService
from app.services.storage import StorageService
from app.services.vector_store import LangChainPGVectorStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def get_storage_service() -> StorageService:
    settings = get_settings()
    return StorageService(
        endpoint_url=settings.s3_endpoint,
        bucket=settings.s3_bucket,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        local_dir=settings.storage_local_dir,
    )


def get_embedding_service() -> LangChainEmbeddingService:
    settings = get_settings()
    return LangChainEmbeddingService(
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        api_key=settings.embedding_api_key,
        dim=settings.embedding_dim,
    )


DbDep = Annotated[Session, Depends(get_db)]
StorageDep = Annotated[StorageService, Depends(get_storage_service)]
EmbeddingDep = Annotated[LangChainEmbeddingService, Depends(get_embedding_service)]


def get_vector_store(
    db: DbDep,
    embedding_svc: EmbeddingDep,
) -> LangChainPGVectorStore:
    settings = get_settings()
    return LangChainPGVectorStore(
        session=db,
        embeddings=embedding_svc,
        connection_url=settings.database_url,
    )


VectorStoreDep = Annotated[LangChainPGVectorStore, Depends(get_vector_store)]


@router.post("/upload", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: Annotated[UploadFile, File(description="PDF file to upload and chunk")],
    storage: StorageDep,
    embedding_svc: EmbeddingDep,
    vector_store: VectorStoreDep,
    doc_id: Annotated[str | None, Form(description="Optional custom document ID")] = None,
    doc_type: Annotated[str, Form(description="Document type: 'internal' or 'vbpl'")] = "internal",
    title: Annotated[str | None, Form(description="Optional document title")] = None,
    code: Annotated[str | None, Form(description="Optional document code / number")] = None,
    issuer: Annotated[str | None, Form(description="Optional issuing authority")] = None,
    effective_date: Annotated[str | None, Form(description="Optional effective date")] = None,
) -> IngestResponse:
    """Upload a PDF, chunk into legal structural units, and ingest into pgvector."""
    filename = file.filename or "uploaded_document.pdf"
    if not (filename.lower().endswith(".pdf") or file.content_type == "application/pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a PDF document (.pdf)",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    try:
        inferred_meta, chunks = chunk_pdf(
            source=content,
            doc_id=doc_id,
            doc_type=doc_type,
            issuer=issuer,
            effective_date=effective_date,
        )
    except Exception as exc:
        logger.error("Failed to parse and chunk PDF: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse and chunk PDF: {exc}",
        ) from exc

    final_doc_id = doc_id or inferred_meta.doc_id or "doc-unknown"
    final_code = code or inferred_meta.code or final_doc_id
    final_title = title or inferred_meta.title or filename
    final_issuer = issuer or inferred_meta.issuer
    final_date = effective_date or inferred_meta.effective_date

    # Upload raw PDF to object storage (MinIO / vStorage / local fallback)
    storage_key = f"{final_doc_id}/{filename}"
    pdf_url = storage.upload_file(content=content, key=storage_key)

    # Generate embeddings for each chunk via LangChain Embeddings
    texts_to_embed = [c.text for c in chunks]
    embeddings = embedding_svc.embed_documents(texts_to_embed)

    # Prepare chunk data with embeddings and metadata
    chunks_data = []
    for idx, c in enumerate(chunks):
        emb = embeddings[idx] if idx < len(embeddings) else None
        chunks_data.append(
            {
                "chunk_id": c.chunk_id,
                "doc_id": final_doc_id,
                "doc_type": doc_type,
                "issuer": final_issuer,
                "effective_date": final_date,
                "article_path": c.article_path,
                "page": c.page,
                "bbox": c.bbox,
                "text": c.text,
                "embedding": emb,
                "metadata": c.chunk_metadata,
            }
        )

    # Ingest document and chunks into pgvector via LangChain
    doc_model = vector_store.save_document(
        doc_id=final_doc_id,
        code=final_code,
        title=final_title,
        doc_type=doc_type,
        issuer=final_issuer,
        effective_date=final_date,
        page_count=inferred_meta.page_count,
        pdf_url=pdf_url,
    )
    saved_chunks = vector_store.save_chunks_with_langchain(final_doc_id, chunks_data)

    return IngestResponse(
        status="success",
        document=DocumentResponse(
            id=doc_model.id,
            code=doc_model.code,
            title=doc_model.title,
            doc_type=doc_model.doc_type,
            issuer=doc_model.issuer,
            effective_date=doc_model.effective_date,
            page_count=doc_model.page_count,
            pdf_url=doc_model.pdf_url,
            created_at=doc_model.created_at,
        ),
        chunk_count=len(saved_chunks),
        chunks=[
            ChunkResponse(
                id=sc.id,
                doc_id=sc.doc_id,
                doc_type=sc.doc_type,
                issuer=sc.issuer,
                effective_date=sc.effective_date,
                article_path=sc.article_path,
                page=sc.page,
                bbox=sc.bbox,
                text=sc.text,
                chunk_metadata=sc.chunk_metadata,
            )
            for sc in saved_chunks
        ],
    )


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    vector_store: VectorStoreDep,
    doc_type: str | None = None,
) -> list[DocumentResponse]:
    """List ingested documents, optionally filtered by doc_type."""
    docs = vector_store.list_documents(doc_type=doc_type)
    return [
        DocumentResponse(
            id=d.id,
            code=d.code,
            title=d.title,
            doc_type=d.doc_type,
            issuer=d.issuer,
            effective_date=d.effective_date,
            page_count=d.page_count,
            pdf_url=d.pdf_url,
            created_at=d.created_at,
        )
        for d in docs
    ]


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(
    doc_id: str,
    vector_store: VectorStoreDep,
) -> DocumentResponse:
    """Get document details by doc_id."""
    doc = vector_store.get_document(doc_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found",
        )
    return DocumentResponse(
        id=doc.id,
        code=doc.code,
        title=doc.title,
        doc_type=doc.doc_type,
        issuer=doc.issuer,
        effective_date=doc.effective_date,
        page_count=doc.page_count,
        pdf_url=doc.pdf_url,
        created_at=doc.created_at,
    )


@router.get("/{doc_id}/chunks", response_model=list[ChunkResponse])
def get_document_chunks(
    doc_id: str,
    vector_store: VectorStoreDep,
) -> list[ChunkResponse]:
    """Get all chunks for a document."""
    chunks = vector_store.get_chunks(doc_id)
    return [
        ChunkResponse(
            id=c.id,
            doc_id=c.doc_id,
            doc_type=c.doc_type,
            issuer=c.issuer,
            effective_date=c.effective_date,
            article_path=c.article_path,
            page=c.page,
            bbox=c.bbox,
            text=c.text,
            chunk_metadata=c.chunk_metadata,
        )
        for c in chunks
    ]


@router.post("/search", response_model=list[SearchResult])
def search_chunks(
    req: SearchRequest,
    vector_store: VectorStoreDep,
) -> list[SearchResult]:
    """Perform similarity search on document chunks using LangChain PGVector."""
    matches = vector_store.similarity_search_langchain(
        query=req.query,
        top_k=req.top_k,
        doc_type=req.doc_type,
        doc_id=req.doc_id,
    )
    return [
        SearchResult(
            chunk=ChunkResponse(
                id=c.id,
                doc_id=c.doc_id,
                doc_type=c.doc_type,
                issuer=c.issuer,
                effective_date=c.effective_date,
                article_path=c.article_path,
                page=c.page,
                bbox=c.bbox,
                text=c.text,
                chunk_metadata=c.chunk_metadata,
            ),
            score=round(score, 4),
        )
        for c, score in matches
    ]
