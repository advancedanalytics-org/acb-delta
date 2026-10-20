"""Pydantic schemas for document and chunk APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChunkResponse(BaseModel):
    id: str
    doc_id: str
    doc_type: str
    issuer: str | None = None
    effective_date: str | None = None
    article_path: str | None = None
    page: int
    bbox: list[list[float]]
    text: str
    chunk_metadata: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class DocumentResponse(BaseModel):
    id: str
    code: str | None = None
    title: str | None = None
    doc_type: str
    issuer: str | None = None
    version_label: str | None = None
    effective_date: str | None = None
    page_count: int = 0
    pdf_url: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class IngestResponse(BaseModel):
    status: str = "success"
    document: DocumentResponse
    chunk_count: int
    chunks: list[ChunkResponse] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    doc_type: str | None = None
    doc_id: str | None = None


class SearchResult(BaseModel):
    chunk: ChunkResponse
    score: float


# Caps on text that goes into an LLM prompt, so one request cannot run up the model bill.
# A clause or a regulation excerpt is a few thousand characters at most.
MAX_PROMPT_TEXT_CHARS = 20_000
MAX_LABEL_CHARS = 500


class SuggestEditRequest(BaseModel):
    impact_id: str | None = Field(None, max_length=MAX_LABEL_CHARS)
    affected_text: str = Field(max_length=MAX_PROMPT_TEXT_CHARS)
    change_clause: str | None = Field(None, max_length=MAX_PROMPT_TEXT_CHARS)
    citation: str | None = Field(None, max_length=MAX_LABEL_CHARS)
    location: str | None = Field(None, max_length=MAX_LABEL_CHARS)
    document_code: str | None = Field(None, max_length=MAX_LABEL_CHARS)


class SuggestEditResponse(BaseModel):
    suggested_text: str
    reasoning: str | None = None
    confidence: float = 0.95
