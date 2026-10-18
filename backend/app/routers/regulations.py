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
            "examples": [{}, {"internal_document_ids": ["DOC-102"], "max_llm_calls": 20}]
        }
    )

    internal_document_ids: list[str] | None = Field(
        None, description="Limit the internal corpus (ACL / scope); default all effective docs"
    )
    modalities: list[Literal["must", "must_not", "may"]] | None = None
    use_llm: bool = Field(True, description="Use the LLM judge when LLM_MODEL is configured")
    max_llm_calls: int = Field(
        150, ge=0, le=5000, description="LLM judge calls, one per obligation (strongest first)"
    )
    use_rerank: bool = Field(True, description="Use the reranker when RERANK_MODEL is configured")
    rerank_candidates: int = Field(20, ge=1, le=200)
    rerank_min_score: float = Field(0.2, ge=0, le=1)
    filter_not_applicable: bool = Field(
        True, description="Skip obligations that do not bind the bank (rules + LLM, cached)"
    )
    refresh_llm_cache: bool = Field(
        False, description="Ask the LLM again instead of reusing cached answers"
    )
    rrf_k: int = Field(60, ge=1, le=1000)
    candidates_per_query: int = Field(20, ge=1, le=200)
    evidence_per_obligation: int = Field(5, ge=1, le=20)
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


@router.get("")
def list_regulations() -> list[dict]:
    try:
        ensure_schema()
        with get_engine().connect() as conn:
            docs = (
                conn.execute(
                    text(
                        "SELECT d.document_id, d.title, d.doc_number, d.issuer, d.owner, "
                        "v.version_id, v.processing_status, v.page_count, v.created_at, "
                        "(SELECT count(*) FROM impact_finding f "
                        " WHERE f.regulation_version_id = v.version_id) AS impact_count, "
                        "(SELECT count(*) FROM impact_finding f "
                        " WHERE f.regulation_version_id = v.version_id "
                        " AND NOT EXISTS ( "
                        "   SELECT 1 FROM decisions dec "
                        "   WHERE dec.impact_id = f.finding_id AND dec.undone_at IS NULL "
                        " )) AS pending_count "
                        "FROM document d "
                        "JOIN document_version v ON v.document_id = d.document_id "
                        "WHERE d.doc_type = 'regulation' "
                        "ORDER BY v.created_at DESC"
                    )
                )
                .mappings()
                .all()
            )
            results = []
            for d in docs:
                row = dict(d)
                ps = row.get("processing_status")
                ic = row.get("impact_count", 0)
                pc = row.get("pending_count", 0)
                if ps in ("AI_PROPOSED", "PROPOSED", "COMPLETED"):
                    row["status"] = (
                        "not_found" if ic == 0 else ("done" if pc == 0 else "awaiting_review")
                    )
                elif ps == "FAILED":
                    row["status"] = "failed"
                else:
                    row["status"] = "processing"
                results.append(row)
            return results
    except OperationalError as exc:
        raise _db_unavailable(exc) from exc


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


@router.get("/{regulation_id}/impacts")
def list_regulation_impacts(regulation_id: str) -> list[dict]:
    """List impact findings for a regulation, formatted for the Review workspace."""
    try:
        ensure_schema()
        with get_engine().connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT f.finding_id, f.regulation_version_id, f.impacted_document_id, "
                        "f.internal_clause_id, f.category, f.rationale, f.priority, f.status, "
                        "f.source_span, f.target_span, f.citations, "
                        "c.numbering, c.heading, c.page, c.bbox, c.text AS affected_text "
                        "FROM impact_finding f "
                        "JOIN document_version v ON v.version_id = f.regulation_version_id "
                        "LEFT JOIN clause c ON c.clause_id = f.internal_clause_id "
                        "WHERE v.document_id = :d "
                        "ORDER BY f.priority DESC, f.created_at ASC"
                    ),
                    {"d": regulation_id},
                )
                .mappings()
                .all()
            )

            # Query active decisions for these findings
            decision_map = {}
            if rows:
                try:
                    fids = [r["finding_id"] for r in rows]
                    dec_rows = (
                        conn.execute(
                            text(
                                "SELECT d.id, d.impact_id, d.action, d.edited_text, "
                                "d.reason_tags, d.reviewer_id, d.at, "
                                "r.name AS reviewer_name, r.role AS reviewer_role "
                                "FROM decisions d "
                                "JOIN reviewers r ON r.id = d.reviewer_id "
                                "WHERE d.undone_at IS NULL AND d.impact_id = ANY(:fids) "
                                "ORDER BY d.at DESC"
                            ),
                            {"fids": fids},
                        )
                        .mappings()
                        .all()
                    )
                    for d in dec_rows:
                        if d["impact_id"] not in decision_map:
                            decision_map[d["impact_id"]] = d
                except Exception:
                    pass

            results = []
            for r in rows:
                category_map = {
                    "conflict": "conflict",
                    "outdated_reference": "outdated_reference",
                }
                impact_type = category_map.get(str(r["category"]).lower(), "new_obligation")
                loc = r.get("numbering") or r.get("heading") or "Điều khoản"
                src_text = (r.get("source_span") or {}).get("text", "")
                tgt_text = r.get("affected_text") or (r.get("target_span") or {}).get("text", "")

                active_dec = decision_map.get(r["finding_id"])
                if active_dec:
                    action = active_dec["action"]
                    status = "accepted" if action in ("accept", "edit") else "rejected"
                    final_text = (
                        active_dec["edited_text"] if action == "edit" else (src_text or tgt_text)
                    )
                    dec_obj = {
                        "id": active_dec["id"],
                        "impactId": r["finding_id"],
                        "vbplId": regulation_id,
                        "documentId": r["impacted_document_id"],
                        "action": action,
                        "editedText": active_dec.get("edited_text"),
                        "reasonTags": active_dec.get("reason_tags") or [],
                        "reviewer": {
                            "id": active_dec["reviewer_id"],
                            "name": active_dec.get("reviewer_name") or active_dec["reviewer_id"],
                            "role": active_dec.get("reviewer_role") or "Chuyên viên",
                        },
                        "at": active_dec["at"].isoformat() if active_dec.get("at") else "",
                    }
                else:
                    status = "pending"
                    final_text = None
                    dec_obj = None

                results.append(
                    {
                        "id": r["finding_id"],
                        "vbplId": regulation_id,
                        "documentId": r["impacted_document_id"],
                        "location": loc,
                        "changeClause": src_text,
                        "citation": ", ".join(r["citations"]) if r.get("citations") else "",
                        "affectedText": tgt_text,
                        "page": r.get("page") or 1,
                        "bboxes": [r["bbox"]] if r.get("bbox") else [],
                        "type": impact_type,
                        "severity": (r.get("priority") or "medium").lower(),
                        "reasoning": r.get("rationale") or "",
                        "suggestedText": src_text or tgt_text,
                        "status": status,
                        "finalText": final_text,
                        "decision": dec_obj,
                    }
                )
            return results
    except OperationalError as exc:
        raise _db_unavailable(exc) from exc
