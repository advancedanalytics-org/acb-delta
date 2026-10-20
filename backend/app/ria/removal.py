"""Delete a regulation version that is not processing, so the same PDF can be uploaded again.

Postgres is cleaned in one transaction (HITL package, findings, obligations, clauses, jobs, the
version, and the document once it has no versions left). A version with reviewer decisions is
never deleted: those decisions are the audit trail. The stored original
and the knowledge graph nodes are derived copies, removed best-effort after the commit.
"""

import logging

from sqlalchemy import text

from app.db import get_engine
from app.ria import graph
from app.ria.schema import ensure_schema
from app.ria.storage import get_storage

log = logging.getLogger(__name__)


class RemovalError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# Row sets shared by the delete statements below; :v is the version id.
_CLAUSES = "SELECT clause_id FROM clause WHERE version_id = :v"
_JOBS = "SELECT job_id FROM job WHERE version_id = :v"
_OBLIGATIONS = f"SELECT obligation_id FROM obligation WHERE source_clause_id IN ({_CLAUSES})"
_FINDINGS = (
    "SELECT finding_id FROM impact_finding WHERE regulation_version_id = :v "
    f"OR job_id IN ({_JOBS}) OR obligation_id IN ({_OBLIGATIONS}) "
    f"OR internal_clause_id IN ({_CLAUSES})"
)

# Children before parents, so no foreign key is ever left dangling.
_DELETES = [
    # Impacts cascade with it; versions with reviewer decisions are refused before this runs.
    f"DELETE FROM vbpls WHERE ria_job_id IN ({_JOBS})",
    f"DELETE FROM amendment WHERE finding_id IN ({_FINDINGS}) OR clause_id IN ({_CLAUSES})",
    f"DELETE FROM impact_finding WHERE finding_id IN ({_FINDINGS})",
    f"DELETE FROM evidence WHERE job_id IN ({_JOBS}) OR obligation_id IN ({_OBLIGATIONS}) "
    f"OR internal_clause_id IN ({_CLAUSES})",
    f"DELETE FROM obligation_clause WHERE obligation_id IN ({_OBLIGATIONS}) "
    f"OR clause_id IN ({_CLAUSES})",
    f"DELETE FROM obligation WHERE obligation_id IN ({_OBLIGATIONS})",
    f"DELETE FROM index_view WHERE clause_id IN ({_CLAUSES})",
    f"DELETE FROM reference_edge WHERE source_clause_id IN ({_CLAUSES})",
    # Other documents' references to these clauses stay, but no longer resolve.
    f"UPDATE reference_edge SET target_clause_id = NULL WHERE target_clause_id IN ({_CLAUSES})",
    "DELETE FROM clause WHERE version_id = :v",
    "DELETE FROM job WHERE version_id = :v",
    "DELETE FROM document_version WHERE version_id = :v",
]


def delete_regulation_version(version_id: str) -> dict:
    """Removes one regulation version. The caller checks that it is not processing; this function
    refuses while a job still runs on it, or once a reviewer has decided on any of its impacts."""
    ensure_schema()
    with get_engine().begin() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT v.document_id, v.source_uri, d.doc_type "
                    "FROM document_version v JOIN document d USING (document_id) "
                    "WHERE v.version_id = :v"
                ),
                {"v": version_id},
            )
            .mappings()
            .first()
        )
        if not row or row["doc_type"] != "regulation":
            raise RemovalError(404, f"regulation version {version_id} not found")
        document_id = row["document_id"]
        # Same locks as upload (per document) and analyze (per version): no job can start
        # on this version while it is being deleted.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:d))"), {"d": document_id})
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:v))"), {"v": version_id})
        active = conn.execute(
            text(
                "SELECT count(*) FROM job WHERE version_id = :v AND status IN ('queued', 'running')"
            ),
            {"v": version_id},
        ).scalar()
        if active:
            raise RemovalError(409, f"{version_id} still has a job running; wait for it to finish")
        decided = conn.execute(
            text(
                "SELECT count(*) FROM decisions dec JOIN impacts i ON i.id = dec.impact_id "
                f"JOIN vbpls vb ON vb.id = i.vbpl_id WHERE vb.ria_job_id IN ({_JOBS})"
            ),
            {"v": version_id},
        ).scalar()
        if decided:
            raise RemovalError(
                409,
                f"{version_id} has {decided} reviewer decision(s); "
                "it cannot be deleted because they are the audit trail",
            )
        for statement in _DELETES:
            conn.execute(text(statement), {"v": version_id})
        document_removed = bool(
            conn.execute(
                text(
                    "DELETE FROM document WHERE document_id = :d AND NOT EXISTS "
                    "(SELECT 1 FROM document_version WHERE document_id = :d) RETURNING 1"
                ),
                {"d": document_id},
            ).scalar()
        )

    warnings = []
    if row["source_uri"]:
        try:
            get_storage().delete(row["source_uri"])
        except Exception as exc:
            log.warning("could not delete stored original %s: %s", row["source_uri"], exc)
            warnings.append(f"stored file not deleted: {exc.__class__.__name__}")
    if graph.enabled():
        try:
            _delete_from_graph(version_id, document_id if document_removed else None)
        except Exception as exc:
            log.warning("could not delete %s from the knowledge graph: %s", version_id, exc)
            warnings.append(f"knowledge graph not cleaned: {exc.__class__.__name__}")
    return {
        "regulation_id": document_id,
        "version_id": version_id,
        "document_removed": document_removed,
        "warnings": warnings,
    }


def _delete_from_graph(version_id: str, document_id: str | None) -> None:
    graph.query(
        "MATCH (o:Obligation)-[:FROM]->(c:Clause {version: $ver}) DETACH DELETE o",
        {"ver": version_id},
    )
    graph.query("MATCH (c:Clause {version: $ver}) DETACH DELETE c", {"ver": version_id})
    graph.query("MATCH (v:Version {id: $ver}) DETACH DELETE v", {"ver": version_id})
    if document_id:
        graph.query("MATCH (d:Doc {id: $doc}) DETACH DELETE d", {"doc": document_id})
