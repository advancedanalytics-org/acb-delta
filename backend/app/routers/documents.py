"""Endpoints for uploading, chunking, and ingesting PDF documents into vectorDB using LangChain."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
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

    # Normalize optional form fields
    clean_code = code.strip() if code and code.strip() else None
    clean_title = title.strip() if title and title.strip() else None
    clean_issuer = issuer.strip() if issuer and issuer.strip() else None
    clean_effective_date = (
        effective_date.strip() if effective_date and effective_date.strip() else None
    )
    clean_doc_id = doc_id.strip() if doc_id and doc_id.strip() else None

    try:
        inferred_meta, chunks = chunk_pdf(
            source=content,
            doc_id=clean_doc_id,
            doc_type=doc_type,
            code=clean_code,
            title=clean_title,
            issuer=clean_issuer,
            effective_date=clean_effective_date,
        )
    except Exception as exc:
        logger.error("Failed to parse and chunk PDF: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse and chunk PDF: {exc}",
        ) from exc

    import re

    final_code = clean_code or inferred_meta.code or "VBPL-01"
    if clean_doc_id:
        final_doc_id = clean_doc_id
    elif inferred_meta.doc_id and inferred_meta.doc_id != "doc-unknown":
        final_doc_id = inferred_meta.doc_id
    elif final_code:
        final_doc_id = re.sub(r"[^a-zA-Z0-9_\-]+", "-", final_code.lower()).strip("-")
    else:
        final_doc_id = "doc-unknown"

    final_title = clean_title or inferred_meta.title or filename.replace(".pdf", "")
    final_issuer = (
        clean_issuer
        or inferred_meta.issuer
        or ("Ngân hàng Nhà nước Việt Nam" if doc_type == "vbpl" else "Ngân hàng ACB")
    )
    final_date = clean_effective_date or inferred_meta.effective_date

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
                "code": final_code,
                "title": final_title,
                "doc_type": doc_type,
                "issuer": final_issuer,
                "effective_date": final_date,
                "article_path": c.article_path,
                "page": c.page,
                "bbox": c.bbox,
                "text": c.text,
                "embedding": emb,
                "metadata": {
                    **c.chunk_metadata,
                    "document_code": final_code,
                    "document_title": final_title,
                },
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
    from typing import Any

    from sqlalchemy import text

    from app.db import get_engine

    results_map: dict[str, DocumentResponse] = {}

    # 1. Read from VectorStore (documents table)
    for d in vector_store.list_documents(doc_type=doc_type):
        results_map[d.id] = DocumentResponse(
            id=d.id,
            code=d.code,
            title=d.title,
            doc_type=d.doc_type,
            issuer=d.issuer,
            effective_date=d.effective_date,
            page_count=d.page_count,
            pdf_url=d.pdf_url or f"/api/documents/{d.id}/pdf",
            created_at=d.created_at,
        )

    # 2. Also read from RIA document table
    try:
        with get_engine().connect() as conn:
            query = (
                "SELECT d.document_id, d.title, d.doc_type, d.owner, d.doc_number, d.issuer, "
                "v.version_label, v.valid_from, v.page_count, d.created_at "
                "FROM document d "
                "LEFT JOIN document_version v ON v.document_id = d.document_id"
            )
            params: dict[str, Any] = {}
            if doc_type:
                query += " WHERE d.doc_type = :dt"
                params["dt"] = doc_type
            query += " ORDER BY v.created_at DESC"

            rows = conn.execute(text(query), params).mappings().all()
            for r in rows:
                doc_id = r["document_id"]
                if doc_id not in results_map:
                    vf = r.get("valid_from")
                    vf_str = (
                        vf.isoformat()
                        if vf and hasattr(vf, "isoformat")
                        else (str(vf) if vf else None)
                    )
                    results_map[doc_id] = DocumentResponse(
                        id=doc_id,
                        code=r.get("doc_number") or doc_id,
                        title=r["title"],
                        doc_type=r["doc_type"],
                        issuer=r.get("issuer") or r.get("owner"),
                        effective_date=vf_str,
                        page_count=r.get("page_count") or 1,
                        pdf_url=f"/api/documents/{doc_id}/pdf",
                        created_at=r["created_at"],
                    )
    except Exception as exc:
        logger.debug("Could not query RIA document table for list_documents: %s", exc)

    return list(results_map.values())


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(
    doc_id: str,
    vector_store: VectorStoreDep,
) -> DocumentResponse:
    """Get document details by doc_id."""
    from sqlalchemy import text

    from app.db import get_engine

    doc = vector_store.get_document(doc_id)
    if doc:
        return DocumentResponse(
            id=doc.id,
            code=doc.code,
            title=doc.title,
            doc_type=doc.doc_type,
            issuer=doc.issuer,
            effective_date=doc.effective_date,
            page_count=doc.page_count,
            pdf_url=doc.pdf_url or f"/api/documents/{doc.id}/pdf",
            created_at=doc.created_at,
        )

    # Check RIA tables
    try:
        with get_engine().connect() as conn:
            r = (
                conn.execute(
                    text(
                        "SELECT d.document_id, d.title, d.doc_type, d.owner, "
                        "d.doc_number, d.issuer, v.version_label, v.valid_from, "
                        "v.page_count, d.created_at FROM document d "
                        "LEFT JOIN document_version v ON v.document_id = d.document_id "
                        "WHERE d.document_id = :d ORDER BY v.created_at DESC LIMIT 1"
                    ),
                    {"d": doc_id},
                )
                .mappings()
                .first()
            )
            if r:
                vf = r.get("valid_from")
                vf_str = (
                    vf.isoformat() if vf and hasattr(vf, "isoformat") else (str(vf) if vf else None)
                )
                return DocumentResponse(
                    id=r["document_id"],
                    code=r.get("doc_number") or r["document_id"],
                    title=r["title"],
                    doc_type=r["doc_type"],
                    issuer=r.get("issuer") or r.get("owner"),
                    effective_date=vf_str,
                    page_count=r.get("page_count") or 1,
                    pdf_url=f"/api/documents/{doc_id}/pdf",
                    created_at=r["created_at"],
                )
    except Exception as exc:
        logger.debug("Could not query RIA document for %s: %s", doc_id, exc)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Document '{doc_id}' not found",
    )


@router.get("/{doc_id}/pdf")
def get_document_pdf(
    doc_id: str,
) -> Response:
    """Download and stream the PDF for an internal document or regulation."""
    from pathlib import Path
    from typing import Any

    from sqlalchemy import text

    from app.db import get_engine
    from app.services.pdf_generator import generate_pdf_for_document

    data: bytes | None = None
    doc_info: dict[str, Any] = {}

    # 1. Check document_version in RIA database
    try:
        with get_engine().connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT d.title, d.doc_type, d.owner, d.doc_number, "
                        "v.source_uri, v.file_name, v.content, v.version_label, v.valid_from "
                        "FROM document d "
                        "LEFT JOIN document_version v ON v.document_id = d.document_id "
                        "WHERE d.document_id = :d ORDER BY v.created_at DESC LIMIT 1"
                    ),
                    {"d": doc_id},
                )
                .mappings()
                .first()
            )
            if row:
                doc_info = dict(row)
                uri = row.get("source_uri")
                if uri:
                    if uri.startswith("s3://"):
                        import boto3

                        settings = get_settings()
                        s3 = boto3.client(
                            "s3",
                            endpoint_url=settings.s3_endpoint,
                            aws_access_key_id=(settings.s3_access_key or settings.postgres_user),
                            aws_secret_access_key=(
                                settings.s3_secret_key or settings.postgres_password
                            ),
                        )
                        bucket, key = uri.removeprefix("s3://").split("/", 1)
                        raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
                        if raw.startswith(b"%PDF-"):
                            data = raw
                    elif uri.startswith("file://"):
                        p = Path(uri.removeprefix("file://"))
                        if p.is_file():
                            raw = p.read_bytes()
                            if raw.startswith(b"%PDF-"):
                                data = raw
                    else:
                        for base in [Path("."), Path(".."), Path("/app")]:
                            p = base / uri
                            if p.is_file():
                                raw = p.read_bytes()
                                if raw.startswith(b"%PDF-"):
                                    data = raw
                                    break
    except Exception as exc:
        logger.debug("Could not read PDF from document_version: %s", exc)

    # 2. Check MinIO S3 standard keys
    if not data:
        try:
            import boto3

            settings = get_settings()
            s3 = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key or settings.postgres_user,
                aws_secret_access_key=settings.s3_secret_key or settings.postgres_password,
            )
            for key in (
                f"internal/{doc_id}/{doc_id}.pdf",
                f"internal/{doc_id}.pdf",
                f"documents/{doc_id}.pdf",
                f"{doc_id}/{doc_id}.pdf",
                f"{doc_id}.pdf",
            ):
                try:
                    obj = s3.get_object(Bucket=settings.s3_bucket, Key=key)
                    raw = obj["Body"].read()
                    if raw.startswith(b"%PDF-"):
                        data = raw
                        break
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Could not fetch PDF from MinIO: %s", exc)

    # 3. Check local data directories fallback
    if not data:
        candidates = [
            Path(f"data/{doc_id}.pdf"),
            Path(f"../data/{doc_id}.pdf"),
            Path(f"frontend/public/demo/{doc_id}.pdf"),
            Path(f"../frontend/public/demo/{doc_id}.pdf"),
            Path(f"frontend/public/demo/{doc_id.lower()}.pdf"),
            Path(f"../frontend/public/demo/{doc_id.lower()}.pdf"),
            Path(f"db/{doc_id}.pdf"),
            Path(f"../db/{doc_id}.pdf"),
            Path(f"app/ria/data/{doc_id}.pdf"),
            Path(f"backend/app/ria/data/{doc_id}.pdf"),
        ]
        for c in candidates:
            if c.is_file():
                raw = c.read_bytes()
                if raw.startswith(b"%PDF-"):
                    data = raw
                    break

    # 4. Dynamic PDF generation fallback
    if not data:
        content_md: str | None = None
        for md_path in [
            Path(f"db/{doc_id}.md"),
            Path(f"../db/{doc_id}.md"),
            Path(f"app/ria/data/{doc_id}.md"),
            Path(f"backend/app/ria/data/{doc_id}.md"),
        ]:
            if md_path.is_file():
                content_md = md_path.read_text(encoding="utf-8")
                break

        if not content_md and doc_info.get("content"):
            content_md = str(doc_info["content"])

        clauses: list[dict[str, Any]] = []
        if not content_md:
            try:
                with get_engine().connect() as conn:
                    rows = (
                        conn.execute(
                            text(
                                "SELECT c.clause_id, c.numbering, c.heading, c.text, c.level "
                                "FROM clause c "
                                "JOIN document_version v ON v.version_id = c.version_id "
                                "WHERE v.document_id = :d ORDER BY c.ordinal ASC"
                            ),
                            {"d": doc_id},
                        )
                        .mappings()
                        .all()
                    )
                    clauses = [dict(r) for r in rows]
            except Exception as exc:
                logger.debug("Could not fetch clauses for PDF gen: %s", exc)

        if content_md or clauses or doc_info:
            save_paths = [
                Path(f"frontend/public/demo/{doc_id}.pdf"),
                Path(f"data/{doc_id}.pdf"),
            ]
            vf = doc_info.get("valid_from")
            vf_str = (
                vf.isoformat() if vf and hasattr(vf, "isoformat") else (str(vf) if vf else None)
            )
            data = generate_pdf_for_document(
                doc_id=doc_id,
                title=doc_info.get("title") or doc_id,
                content_md=content_md,
                clauses=clauses,
                owner=doc_info.get("owner"),
                version=doc_info.get("version_label"),
                effective_date=vf_str,
                save_paths=save_paths,
            )
            # Cache to MinIO
            try:
                import boto3

                settings = get_settings()
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.s3_endpoint,
                    aws_access_key_id=settings.s3_access_key or settings.postgres_user,
                    aws_secret_access_key=settings.s3_secret_key or settings.postgres_password,
                )
                s3.put_object(
                    Bucket=settings.s3_bucket,
                    Key=f"{doc_id}/{doc_id}.pdf",
                    Body=data,
                    ContentType="application/pdf",
                )
            except Exception as exc:
                logger.debug("Could not cache generated PDF to MinIO: %s", exc)

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PDF for document '{doc_id}' not found",
        )

    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc_id}.pdf"',
            "Content-Type": "application/pdf",
        },
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
