"""Impact findings of RIA analyses (design section 16).

GET /api/findings                  list; filter by job, regulation, document, category, status,
                                   priority, method; paginate
GET /api/findings/{id}             one finding
GET /api/findings/{id}/evidence    evidence pack: obligation, internal clause, every evidence row

Engine 3 (design 13-15; DRAFT pending the M04 ownership decision in PLAN.md):
POST /api/findings/{id}/amendments      draft + verify a minimal patch (201, or 200 if one exists)
GET  /api/findings/{id}/amendments      patches drafted for the finding
GET  /api/amendments/{id}               patch, verification report, patched clause
POST /api/amendments/{id}/validate      re-run verification (e.g. after the clause changed)
POST /api/amendments/{id}/decision      approve | reject | return
GET  /api/amendments/{id}/redline       HTML before/after
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError

from app.ria import amendment, findings
from app.ria.amendment import AmendmentError
from app.ria.findings import FindingError
from app.ria.schema import ensure_schema

router = APIRouter(tags=["findings"])


class DraftRequest(BaseModel):
    refresh: bool = Field(False, description="Draft a new patch even if one is pending/approved")


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "return"]
    reviewer: str = Field(..., min_length=1, max_length=200)
    comment: str | None = Field(None, max_length=4000)


def _call(fn, *args):
    try:
        ensure_schema()
        return fn(*args)
    except (FindingError, AmendmentError) as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except OperationalError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc


@router.get("/findings")
def list_findings(
    job_id: str | None = None,
    regulation_id: str | None = None,
    regulation_version_id: str | None = None,
    impacted_document_id: str | None = None,
    category: str | None = None,
    status_: str | None = Query(None, alias="status"),
    priority: str | None = None,
    method: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    filters = {
        "job_id": job_id,
        "regulation_id": regulation_id,
        "regulation_version_id": regulation_version_id,
        "impacted_document_id": impacted_document_id,
        "category": category,
        "status": status_,
        "priority": priority,
        "method": method,
    }
    rows, total = _call(findings.finding_rows, filters, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


@router.get("/findings/{finding_id}")
def get_finding(finding_id: str) -> dict:
    return _call(findings.evidence_pack, finding_id)["finding"]


@router.get("/findings/{finding_id}/evidence")
def get_evidence(finding_id: str) -> dict:
    return _call(findings.evidence_pack, finding_id)


@router.post("/findings/{finding_id}/amendments", status_code=status.HTTP_201_CREATED)
def draft_amendment(finding_id: str, response: Response, body: DraftRequest | None = None) -> dict:
    result, created = _call(
        amendment.create_amendment, finding_id, (body or DraftRequest()).refresh
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/findings/{finding_id}/amendments")
def list_amendments(finding_id: str) -> list[dict]:
    return _call(amendment.list_for_finding, finding_id)


@router.get("/amendments/{patch_id}")
def get_amendment(patch_id: str) -> dict:
    return _call(amendment.get_amendment, patch_id)


@router.post("/amendments/{patch_id}/validate")
def validate(patch_id: str) -> dict:
    return _call(amendment.validate_amendment, patch_id)


@router.post("/amendments/{patch_id}/decision")
def decide(patch_id: str, body: DecisionRequest) -> dict:
    return _call(amendment.decide, patch_id, body.decision, body.reviewer, body.comment)


@router.get("/amendments/{patch_id}/redline", response_class=HTMLResponse)
def redline(patch_id: str) -> str:
    return _call(amendment.redline_html, patch_id)
