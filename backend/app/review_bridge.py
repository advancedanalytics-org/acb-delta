"""RIA findings → HITL review package (docs/amendment-review-contract.md).

One finished RIA analyze job becomes one `vbpls` row; each reviewable finding becomes one
`impacts` row carrying the agent's patch. Runs as a RIA job of type `review`. RIA tables are only
read; the job row is written through `app.ria.jobs`.

With REVIEW_AUTO_START the package is started as soon as an analyze job finishes: the `analyze`
handler is re-registered here as "RIA analysis, then queue the review" (RIA's own code unchanged).
"""

import json
import logging
import re
import threading
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy import exists, select, text
from sqlalchemy.dialects.postgresql import insert

from app import agent_client
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.models.hitl import Decision, Impact, Vbpl, new_id
from app.ria import analysis, jobs

log = logging.getLogger(__name__)

JOB_TYPE = "review"

# RIA category → UI impact type. EQUIVALENT findings are NO_ACTION_PROPOSED and never imported.
TYPE_BY_CATEGORY = {
    "VALUE_CHANGE": "conflict",
    "CONTRADICTION": "conflict",
    "SCOPE_CHANGE": "conflict",
    "ADDITION": "new_obligation",
    "INDIRECT_IMPACT": "outdated_reference",
}
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
OPERATIONS = {"REPLACE", "INSERT", "DELETE"}
# Prefix of `_draft_one` errors that mean "not drafted on purpose" (draft_status = skipped).
SKIPPED = "skipped: "


class ReviewError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def start_review(analyze_job_id: str, require_succeeded: bool = True) -> tuple[dict, bool]:
    """Create (or return) the review package of an analyze job. Returns (body, started).

    A package is created once per analyze job (`vbpls.ria_job_id` is unique). Calling again
    returns it; only when its last review job failed is a new one started, which drafts the
    findings still missing or failed. `require_succeeded=False` is for the analyze handler
    itself: its findings are committed but the job row is marked succeeded only after it returns.
    """
    job = jobs.get_job(analyze_job_id)
    if job is None or job["job_type"] != "analyze":
        raise ReviewError(404, f"analyze job {analyze_job_id} not found")
    if require_succeeded and job["status"] != "succeeded":
        raise ReviewError(409, f"analyze job {analyze_job_id} is {job['status']}, not succeeded")
    fields = _vbpl_fields(job)
    # One transaction with the package row locked: concurrent calls start at most one job.
    with get_engine().begin() as conn:
        conn.execute(
            insert(Vbpl.__table__)
            .values(id=new_id(), ria_job_id=analyze_job_id, status="processing", **fields)
            .on_conflict_do_nothing(index_elements=["ria_job_id"])
        )
        vbpl_id = conn.execute(
            text("SELECT id FROM vbpls WHERE ria_job_id = :a FOR UPDATE"), {"a": analyze_job_id}
        ).scalar_one()
        latest = conn.execute(
            text(
                "SELECT job_id, status FROM job WHERE job_type = :t "
                "AND params->>'analyze_job_id' = :a ORDER BY created_at DESC LIMIT 1"
            ),
            {"t": JOB_TYPE, "a": analyze_job_id},
        ).first()
        if latest is not None and latest.status != "failed":
            return {"vbpl_id": vbpl_id, "review_job_id": latest.job_id}, False
        review_job_id = jobs.create_job(
            conn,
            JOB_TYPE,
            job["document_id"],
            job["version_id"],
            {"analyze_job_id": analyze_job_id, "vbpl_id": vbpl_id},
        )
        conn.execute(
            text("UPDATE vbpls SET status = 'processing', error = NULL WHERE id = :id"),
            {"id": vbpl_id},
        )
    jobs.submit(review_job_id)
    return {"vbpl_id": vbpl_id, "review_job_id": review_job_id}, True


def review_for_regulation(regulation_id: str) -> tuple[dict, bool]:
    """The review package of the regulation's latest finished analysis (started if missing)."""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT job_id, status FROM job WHERE job_type = 'analyze' AND document_id = :d "
                "ORDER BY created_at DESC"
            ),
            {"d": regulation_id},
        ).all()
    done = next((r.job_id for r in rows if r.status == "succeeded"), None)
    if done is not None:
        return start_review(done)
    if any(r.status in ("queued", "running") for r in rows):
        raise ReviewError(409, f"{regulation_id} is still being analyzed")
    raise ReviewError(404, f"no finished analysis for {regulation_id}")


def _analyze_then_review(job_id: str) -> dict:
    """`analyze` job handler: RIA's analysis, then queue the review package (REVIEW_AUTO_START)."""
    result = analysis.run_analysis(job_id)
    if get_settings().review_auto_start:
        try:
            start_review(job_id, require_succeeded=False)
        except Exception:
            # The analysis itself succeeded; POST .../review can still start the package.
            log.exception("could not start the review package of %s", job_id)
    return result


def _vbpl_fields(job: dict) -> dict:
    """VBPL header from the regulation's RIA document / version metadata."""
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT d.title, d.doc_number, d.issuer, v.issued_date, v.valid_from, v.content, "
                "v.created_at FROM document_version v JOIN document d USING (document_id) "
                "WHERE v.version_id = :v"
            ),
            {"v": job["version_id"]},
        ).mappings()
        row = row.one()
    # The HITL columns are NOT NULL; fall back to the date RIA received the file.
    received = row["created_at"].date() if row["created_at"] else date.today()
    issued = row["issued_date"] or row["valid_from"] or received
    return {
        "number": row["doc_number"] or job["document_id"],
        "title": row["title"],
        "issuer": row["issuer"] or "",
        "issued_date": issued,
        "effective_date": row["valid_from"] or issued,
        "summary": "",
        "text": row["content"] or "",
    }


def load_findings(analyze_job_id: str) -> list[dict]:
    """Every reviewable finding of the job with the context /draft needs, in review order.

    The only SQL on RIA's finding tables, so a RIA schema change is fixed here.
    """
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT f.finding_id, f.job_id, f.obligation_id, f.evidence_id, f.category, "
                "f.rationale, f.status, f.priority, f.confidence, f.source_span, f.target_span, "
                "f.verification, f.citations, f.method, f.impacted_document_id, "
                "f.internal_clause_id, o.text AS obligation_text, o.source_clause_id, "
                "rc.numbering AS regulation_numbering, rd.doc_number AS regulation_number, "
                "ic.numbering AS clause_numbering, "
                "ic.heading AS clause_heading, pc.heading AS parent_heading, "
                "ic.text AS clause_text, ic.bbox AS clause_bbox, e.score "
                "FROM impact_finding f "
                "JOIN obligation o ON o.obligation_id = f.obligation_id "
                "JOIN clause rc ON rc.clause_id = o.source_clause_id "
                "JOIN document_version rv ON rv.version_id = rc.version_id "
                "JOIN document rd ON rd.document_id = rv.document_id "
                "LEFT JOIN clause ic ON ic.clause_id = f.internal_clause_id "
                "LEFT JOIN clause pc ON pc.clause_id = ic.parent_id "
                "LEFT JOIN evidence e ON e.evidence_id = f.evidence_id "
                "WHERE f.job_id = :j AND f.status = 'AI_PROPOSED'"
            ),
            {"j": analyze_job_id},
        ).mappings()
        findings = [dict(r) for r in rows]
    findings.sort(
        key=lambda f: (PRIORITY_RANK.get(f["priority"], 9), -(f["score"] or 0), f["finding_id"])
    )
    return findings


def draft_request(f: dict) -> dict:
    return {
        "finding_id": f["finding_id"],
        "category": f["category"],
        "rationale": f["rationale"],
        "obligation": {"clause_id": f["source_clause_id"], "text": f["obligation_text"]},
        "source_span": f["source_span"],
        "clause": {
            "clause_id": f["internal_clause_id"],
            "numbering": f["clause_numbering"],
            "text": f["clause_text"],
        },
        "target_span": f["target_span"],
        "citations": list(f["citations"] or []),
    }


def page_and_boxes(
    bbox: list | None, default_page: int | None = None
) -> tuple[int | None, list[list[float]]]:
    """Parse bounding boxes in 5-element [page, x0, y0, x1, y1] or 4-element [x0, y0, x1, y1]."""
    if not bbox:
        return None, []
    first = bbox[0]
    if isinstance(first, list):
        if len(first) == 5:
            page = int(first[0])
            return page, [list(map(float, b[1:5])) for b in bbox if int(b[0]) == page]
        elif len(first) == 4:
            return default_page, [list(map(float, b)) for b in bbox]
    return None, []


def apply_patch(clause_text: str, patch: dict) -> str:
    return clause_text[: patch["start"]] + patch["new_text"] + clause_text[patch["end"] :]


_locate_lock = threading.Lock()


@lru_cache(maxsize=16)
def _get_doc_pdf_bytes(doc_id: str) -> bytes | None:
    for base in [Path("/"), Path("."), Path(".."), Path("/app")]:
        for candidate in [
            base / f"frontend/public/demo/{doc_id}.pdf",
            base / f"frontend/public/demo/{doc_id.lower()}.pdf",
            base / f"data/{doc_id}.pdf",
            base / f"data/{doc_id.lower()}.pdf",
            base / f"db/{doc_id}.pdf",
        ]:
            if candidate.is_file():
                try:
                    raw = candidate.read_bytes()
                    if raw.startswith(b"%PDF-"):
                        return raw
                except Exception:
                    pass
    try:
        import boto3

        from app.config import get_settings

        settings = get_settings()
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key or settings.postgres_user,
            aws_secret_access_key=settings.s3_secret_key or settings.postgres_password,
        )
        for key in [
            f"{doc_id}/{doc_id}.pdf",
            f"documents/{doc_id}.pdf",
            f"internal/{doc_id}/{doc_id}.pdf",
            f"internal/{doc_id}.pdf",
            f"{doc_id}.pdf",
        ]:
            try:
                raw = s3.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
                if raw.startswith(b"%PDF-"):
                    return raw
            except Exception:
                continue
    except Exception:
        pass
    try:
        from app.routers.documents import get_document_pdf

        resp = get_document_pdf(doc_id)
        if resp and resp.body and resp.body.startswith(b"%PDF-"):
            return resp.body
    except Exception:
        pass
    return None


def _locate_in_document(doc_id: str, clause_text: str) -> tuple[int, list[list[float]]] | None:
    try:
        import pymupdf
    except ImportError:
        return None
    raw_bytes = _get_doc_pdf_bytes(doc_id)
    if not raw_bytes:
        return None
    with _locate_lock:
        try:
            pdf = pymupdf.open(stream=raw_bytes, filetype="pdf")
        except Exception:
            return None
        clean = re.sub(r"[*#_]", "", clause_text).replace("`", "")
        lines = [line.strip() for line in clean.split("\n") if line.strip()]
        if not lines:
            return None
        candidates = [clean[:120], lines[0][:80], lines[0][:50], lines[0].split(".")[0]]
        for cand in candidates:
            cand = cand.strip()
            if len(cand) < 6:
                continue
            for page_num in range(len(pdf)):
                page = pdf[page_num]
                rects = page.search_for(cand)
                if rects:
                    m_lines: list[pymupdf.Rect] = []
                    for rect in sorted(rects, key=lambda r: (round(r.y0), r.x0)):
                        if m_lines and abs(m_lines[-1].y0 - rect.y0) < 3:
                            m_lines[-1] |= rect
                        else:
                            m_lines.append(pymupdf.Rect(rect))
                    boxes = [[round(v, 2) for v in (r.x0, r.y0, r.x1, r.y1)] for r in m_lines]
                    return page_num + 1, boxes
    return None


def impact_row(f: dict, position: int, proposal: dict | None, error: str | None) -> dict:
    """`Impact` column values for one finding. `proposal` is the agent's AmendmentProposal."""
    clause_text = f["clause_text"] or ""
    verification = (proposal or {}).get("verification") or {}
    patch = None
    if verification.get("status") == "review_required":
        patch = {k: proposal[k] for k in ("operation", "start", "end", "old_text", "new_text")}
    if error is not None:
        draft_status = "skipped" if error.startswith(SKIPPED) else "failed"
        draft_error = error.removeprefix(SKIPPED)
    elif patch is None:
        draft_status, draft_error = "failed", verification.get("reason") or "no usable patch"
    else:
        draft_status, draft_error = "review_required", None
    page, boxes = page_and_boxes(f.get("clause_bbox"), f.get("clause_page"))
    if (
        (
            not boxes
            or any(not isinstance(b, list) or len(b) != 4 for b in boxes)
            or not page
            or page > 50
        )
        and f.get("impacted_document_id")
        and clause_text
    ):
        loc = _locate_in_document(f["impacted_document_id"], clause_text)
        if loc:
            page, boxes = loc
    if page is None:
        page = f.get("clause_page") or 1
    heading = f["clause_heading"] or f["parent_heading"]
    numbering = f["clause_numbering"] or ""
    finding = {
        k: f[k]
        for k in (
            "finding_id", "job_id", "obligation_id", "evidence_id", "internal_clause_id",
            "category", "rationale", "status", "priority", "confidence", "source_span",
            "target_span", "verification", "citations", "method",
        )
    }  # fmt: skip
    return {
        "position": position,
        "document_id": f["impacted_document_id"],
        "chunk_id": f["internal_clause_id"] or "",
        "location": f"{numbering}. {heading}" if heading else numbering,
        # The UI shows change_clause as the new rule's wording and citation as its reference.
        "change_clause": f["obligation_text"],
        "citation": ", ".join(
            filter(None, [f["regulation_number"], f"điều khoản {f['regulation_numbering']}"])
        ),
        "affected_text": clause_text,
        "page": page,
        "bboxes": boxes,
        "type": TYPE_BY_CATEGORY.get(f["category"], "conflict"),
        "severity": f["priority"],
        "reasoning": f["rationale"],
        "suggested_text": apply_patch(clause_text, patch) if patch else "",
        # json round trip: the finding row holds Decimal / list types JSONB cannot take as-is.
        "model_output": json.loads(
            json.dumps({"finding": finding, "draft": proposal}, ensure_ascii=False, default=str)
        ),
        "finding_id": f["finding_id"],
        "category": f["category"],
        "patch": patch,
        "draft_status": draft_status,
        "draft_error": draft_error,
    }


def _draft_one(f: dict, vbpl_id: str) -> tuple[dict | None, str | None]:
    """Agent call for one finding. Errors stay on this finding: (proposal, error)."""
    if not f["internal_clause_id"] or not f["clause_text"]:
        return None, SKIPPED + "finding has no internal clause"
    if not f["target_span"]:
        return None, SKIPPED + "finding has no target_span"
    try:
        proposal = agent_client.draft(draft_request(f), session_id=f"review-{vbpl_id}")
    except Exception as exc:
        log.warning("draft failed for finding %s: %s", f["finding_id"], exc)
        return None, agent_client.describe(exc)
    if problem := invalid_proposal(f["clause_text"], proposal):
        log.warning("invalid draft for finding %s: %s", f["finding_id"], problem)
        return None, f"Agent reply invalid: {problem}"
    return proposal, None


def invalid_proposal(clause_text: str, proposal) -> str | None:
    """Why an agent reply cannot be stored, or None. A usable patch must fit the clause exactly."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get("verification"), dict):
        return "no verification"
    if proposal["verification"].get("status") != "review_required":
        return None  # failed proposals carry no patch
    op, start, end = proposal.get("operation"), proposal.get("start"), proposal.get("end")
    old, new = proposal.get("old_text"), proposal.get("new_text")
    if op not in OPERATIONS:
        return f"operation {op!r}"
    if not (isinstance(start, int) and isinstance(end, int) and 0 <= start <= end):
        return "offsets"
    if end > len(clause_text) or not isinstance(old, str) or clause_text[start:end] != old:
        return "old_text does not match the clause"
    if not isinstance(new, str):
        return "new_text"
    return None


def _imported(vbpl_id: str) -> tuple[set[str], dict[str, str]]:
    """(finding ids to leave alone, finding id → impact id of failed drafts to draft again)."""
    with get_sessionmaker()() as session:
        rows = session.execute(
            select(Impact.id, Impact.finding_id, Impact.draft_status).where(
                Impact.vbpl_id == vbpl_id
            )
        ).all()
    done = {r.finding_id for r in rows if r.draft_status != "failed"}
    redo = {r.finding_id: r.id for r in rows if r.draft_status == "failed"}
    return done, redo


def _store(vbpl_id: str, row: dict, redo_impact_id: str | None) -> None:
    """Insert the impact, or overwrite a failed draft in place while nobody has decided on it.

    The row lock blocks a concurrent POST /api/decisions (its FK check needs a share lock on the
    impact), so a reviewer's decision is never lost; a decided impact keeps what was reviewed.
    """
    with get_sessionmaker()() as session:
        if redo_impact_id is None:
            session.add(Impact(vbpl_id=vbpl_id, **row))
        else:
            impact = session.get(Impact, redo_impact_id, with_for_update=True)
            decided = session.scalar(select(exists().where(Decision.impact_id == redo_impact_id)))
            if impact is not None and not decided:
                for key, value in row.items():
                    setattr(impact, key, value)
        session.commit()


def run_review(job_id: str) -> dict:
    """`review` job handler: draft every reviewable finding and store it as a pending impact."""
    params = jobs.get_job(job_id)["params"]
    vbpl_id = params["vbpl_id"]
    try:
        findings = load_findings(params["analyze_job_id"])
        done, redo = _imported(vbpl_id)
        todo = [(pos, f) for pos, f in enumerate(findings) if f["finding_id"] not in done]
        jobs.update_progress(job_id, "drafting", 5)
        workers = max(1, get_settings().review_draft_concurrency)
        finished = 0
        lock = threading.Lock()

        def handle(item: tuple[int, dict]) -> str:
            nonlocal finished
            position, f = item
            proposal, error = _draft_one(f, vbpl_id)
            row = impact_row(f, position, proposal, error)
            # Own short session per finding: nothing is held open during the agent call.
            _store(vbpl_id, row, redo.get(f["finding_id"]))
            with lock:
                finished += 1
                progress = 5 + 90 * finished // len(todo)
            jobs.update_progress(job_id, "drafting", progress)
            return row["draft_status"]

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ria-review") as pool:
            futures = [pool.submit(handle, item) for item in todo]
            # Agent errors never get here; the first DB / infra error stops the drafts not started.
            _, pending = wait(futures, return_when=FIRST_EXCEPTION)
            for future in pending:
                future.cancel()
            statuses = [future.result() for future in futures if not future.cancelled()]
        counts: dict[str, int] = {}
        for status in statuses:
            counts[status] = counts.get(status, 0) + 1
        summary = f"{len(findings)} tác động từ phân tích RIA {params['analyze_job_id']}"
        _set_vbpl(vbpl_id, status="awaiting_review", error=None, summary=summary)
    except Exception as exc:
        log.exception("review job %s failed", job_id)
        error = f"Internal error: {exc.__class__.__name__}"
        _set_vbpl(vbpl_id, status="failed", error=error)
        # The job row is public (GET /api/jobs); keep SQL and clause text in the log only.
        raise RuntimeError(error) from None
    return {
        "vbpl_id": vbpl_id,
        "findings": len(findings),
        "drafted": len(todo),
        "draft_status": counts,
    }


def fail_interrupted_packages() -> None:
    """On startup, after RIA job recovery: a package whose review job died with the process."""
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE vbpls v SET status = 'failed', error = 'interrupted by API restart' "
                "WHERE v.status = 'processing' AND v.ria_job_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM job j WHERE j.job_type = :t AND j.params->>'vbpl_id' = v.id "
                "AND j.status IN ('queued', 'running'))"
            ),
            {"t": JOB_TYPE},
        )


def _set_vbpl(vbpl_id: str, **values) -> None:
    with get_sessionmaker()() as session:
        vbpl = session.get(Vbpl, vbpl_id)
        for key, value in values.items():
            setattr(vbpl, key, value)
        session.commit()


jobs.register(JOB_TYPE, run_review)
jobs.register("analyze", _analyze_then_review)
