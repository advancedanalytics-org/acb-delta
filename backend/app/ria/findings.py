"""Read access to impact findings (design section 16): list with filters, evidence pack.

Findings are the output of Engine 2 (M03). Drafting and reviewing patches is M04/M05 (agent
`/draft` + HITL, docs/amendment-review-contract.md), so nothing here writes.
"""

from sqlalchemy import text

from app.db import get_engine


class FindingError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def load_finding(conn, finding_id: str) -> dict:
    row = (
        conn.execute(
            text(
                "SELECT f.*, c.text AS clause_text, c.char_start AS clause_start, "
                "c.version_id AS internal_version_id, c.numbering AS clause_numbering, "
                "o.text AS obligation_text, o.modality, o.condition, o.exception, "
                "o.subject AS obligation_subject, rc.clause_id AS regulation_clause_id, "
                "rc.text AS regulation_clause_text, rv.status AS regulation_status "
                "FROM impact_finding f "
                "LEFT JOIN clause c ON c.clause_id = f.internal_clause_id "
                "LEFT JOIN obligation o ON o.obligation_id = f.obligation_id "
                "LEFT JOIN clause rc ON rc.clause_id = o.source_clause_id "
                "LEFT JOIN document_version rv ON rv.version_id = f.regulation_version_id "
                "WHERE f.finding_id = :id"
            ),
            {"id": finding_id},
        )
        .mappings()
        .first()
    )
    if not row:
        raise FindingError(404, f"finding {finding_id} not found")
    return dict(row)


def finding_rows(filters: dict, limit: int, offset: int) -> tuple[list[dict], int]:
    clauses, params = [], {"limit": limit, "offset": offset}
    for key, column in (
        ("job_id", "f.job_id"),
        ("regulation_version_id", "f.regulation_version_id"),
        ("impacted_document_id", "f.impacted_document_id"),
        ("category", "f.category"),
        ("status", "f.status"),
        ("priority", "f.priority"),
        ("method", "f.method"),
    ):
        if filters.get(key):
            clauses.append(f"{column} = :{key}")
            params[key] = filters[key]
    if filters.get("regulation_id"):
        clauses.append("rv.document_id = :regulation_id")
        params["regulation_id"] = filters["regulation_id"]
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    base = (
        "FROM impact_finding f "
        "LEFT JOIN document_version rv ON rv.version_id = f.regulation_version_id "
        f"{where}"
    )
    with get_engine().connect() as conn:
        total = conn.execute(text(f"SELECT count(*) {base}"), params).scalar()
        rows = conn.execute(
            text(
                f"SELECT f.* {base} ORDER BY CASE f.priority WHEN 'high' THEN 0 "
                "WHEN 'medium' THEN 1 ELSE 2 END, f.created_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).mappings()
        return [dict(r) for r in rows], total


def evidence_pack(finding_id: str) -> dict:
    """Finding + obligation + every evidence clause with its retrieval trace (design 09)."""
    with get_engine().connect() as conn:
        f = load_finding(conn, finding_id)
        evidence = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT e.*, c.text AS clause_text, c.numbering FROM evidence e "
                    "JOIN clause c ON c.clause_id = e.internal_clause_id "
                    "WHERE e.evidence_id = ANY(:ids)"
                ),
                {"ids": list(f.get("evidence_ids") or [])},
            ).mappings()
        ]
    order = {eid: i for i, eid in enumerate(f.get("evidence_ids") or [])}
    evidence.sort(key=lambda e: order.get(e["evidence_id"], 99))
    return {
        "finding": {k: v for k, v in f.items() if not k.endswith("_text")},
        "obligation": {
            "obligation_id": f["obligation_id"],
            "text": f["obligation_text"],
            "modality": f["modality"],
            "condition": f["condition"],
            "exception": f["exception"],
            "regulation_clause_id": f["regulation_clause_id"],
        },
        "internal_clause": {"clause_id": f["internal_clause_id"], "text": f["clause_text"]},
        "evidence": evidence,
    }
