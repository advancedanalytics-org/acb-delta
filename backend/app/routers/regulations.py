"""Regulation ingest and impact analysis (design section 16).

POST /api/regulations               upload a VBPL PDF → document version + parse job (202)
POST /api/regulations/{id}/analyze  start impact analysis on a PARSED version → job (202)
GET  /api/regulations/{id}          document, versions and processing state
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import get_engine
from app.ria.analysis import AnalyzeError, start_analysis
from app.ria.ingest import IngestError, create_regulation
from app.ria.schema import ensure_schema

router = APIRouter(prefix="/regulations", tags=["regulations"])


class Check(BaseModel):
    check: str
    status: str
    detail: str | None = None


class RegulationCreated(BaseModel):
    regulation_id: str
    version_id: str
    version_label: str | None = None
    job_id: str | None
    status: str
    duplicate: bool
    checks: list[Check] = []


class AnalyzeRequest(BaseModel):
    """All fields optional; defaults are the benchmark baseline, not tuned constants."""

    # Swagger would otherwise prefill ["string"] lists, which scope the corpus to nothing.
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{}, {"internal_document_ids": ["DOC-102"], "max_llm_pairs": 20}]
        }
    )

    internal_document_ids: list[str] | None = Field(
        None, description="Limit the internal corpus (ACL / scope); default all effective docs"
    )
    modalities: list[Literal["must", "must_not", "may"]] | None = None
    use_llm: bool = Field(True, description="Use the LLM judge when LLM_MODEL is configured")
    max_llm_pairs: int = Field(200, ge=0, le=5000)
    rrf_k: int = Field(60, ge=1, le=1000)
    candidates_per_query: int = Field(20, ge=1, le=200)
    evidence_per_obligation: int = Field(3, ge=1, le=20)
    max_documents: int = Field(20, ge=1, le=500)
    alpha: float = Field(0.7, ge=0, le=1)
    min_shared_bigrams: int = Field(2, ge=0, le=20)
    min_idf_score: float = Field(6.0, ge=0)
    min_term_idf: float = Field(2.0, ge=0)
    relative_cutoff: float = Field(0.6, ge=0, le=1)
    dense_min_score: float = Field(0.55, ge=0, le=1)
    dense_strong_score: float = Field(0.7, ge=0, le=1)


class AnalysisStarted(BaseModel):
    job_id: str
    regulation_id: str
    version_id: str
    status: str
    duplicate: bool


def _db_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"database unavailable: {exc}")


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=RegulationCreated)
async def create(
    response: Response,
    file: Annotated[UploadFile, File(description="VBPL PDF (NHNN circular, decree, law…)")],
    title: Annotated[str | None, Form()] = None,
    doc_number: Annotated[str | None, Form(description="Override number read from the PDF")] = None,
    owner: Annotated[str | None, Form()] = None,
    valid_from: Annotated[date | None, Form(description="Override the effective date")] = None,
) -> RegulationCreated:
    data = await file.read()
    overrides = {
        k: v
        for k, v in {
            "title": title,
            "doc_number": doc_number,
            "owner": owner,
            "valid_from": valid_from.isoformat() if valid_from else None,
        }.items()
        if v
    }
    try:
        body, created = create_regulation(
            data, file.filename or "upload.pdf", file.content_type, overrides
        )
    except IngestError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except OperationalError as exc:
        raise _db_unavailable(exc) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return RegulationCreated(**body)


@router.post(
    "/{regulation_id}/analyze",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AnalysisStarted,
)
def analyze(
    regulation_id: str, response: Response, body: AnalyzeRequest | None = None
) -> AnalysisStarted:
    options = (body or AnalyzeRequest()).model_dump()
    try:
        result, created = start_analysis(regulation_id, options)
    except AnalyzeError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except OperationalError as exc:
        raise _db_unavailable(exc) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return AnalysisStarted(**result)


@router.get("/{regulation_id}")
def get_regulation(regulation_id: str) -> dict:
    try:
        ensure_schema()
        with get_engine().connect() as conn:
            doc = (
                conn.execute(
                    text(
                        "SELECT document_id, title, doc_type, owner, doc_number, issuer, "
                        "legal_form FROM document "
                        "WHERE document_id = :d AND doc_type = 'regulation'"
                    ),
                    {"d": regulation_id},
                )
                .mappings()
                .first()
            )
            if not doc:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"{regulation_id} not found")
            versions = conn.execute(
                text(
                    "SELECT v.version_id, v.version_label, v.status, v.processing_status, "
                    "v.valid_from, v.valid_to, v.issued_date, v.checksum, v.page_count, "
                    "v.file_name, v.created_at, "
                    "(SELECT count(*) FROM clause c WHERE c.version_id = v.version_id) AS clauses, "
                    "(SELECT count(*) FROM obligation o JOIN clause c "
                    " ON c.clause_id = o.source_clause_id WHERE c.version_id = v.version_id) "
                    " AS obligations, "
                    "(SELECT json_agg(json_build_object('job_id', j.job_id, "
                    " 'job_type', j.job_type, 'status', j.status, 'created_at', j.created_at) "
                    " ORDER BY j.created_at) "
                    " FROM job j WHERE j.version_id = v.version_id) AS jobs "
                    "FROM document_version v WHERE v.document_id = :d ORDER BY v.created_at"
                ),
                {"d": regulation_id},
            ).mappings()
            return {**doc, "versions": [dict(v) for v in versions]}
    except OperationalError as exc:
        raise _db_unavailable(exc) from exc
