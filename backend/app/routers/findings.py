"""Impact findings of RIA analyses (design section 16).

GET /api/findings                  list; filter by job, regulation, document, category, status,
                                   priority, method; paginate
GET /api/findings/{id}             one finding
GET /api/findings/{id}/evidence    evidence pack: obligation, internal clause, every evidence row
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import OperationalError

from app.ria import findings
from app.ria.findings import FindingError
from app.ria.schema import ensure_schema

router = APIRouter(tags=["findings"])


def _call(fn, *args):
    try:
        ensure_schema()
        return fn(*args)
    except FindingError as exc:
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
