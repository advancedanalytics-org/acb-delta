"""POST /api/regulations: create a regulation version and its parse job (design sections 05, 16).

Synchronous part (request thread): validate the upload, checksum, dedupe, store the original
immutably, create document / document_version / job rows. The parse job then builds the clause
tree, references, atomic obligations and the multi-view index, and moves the version to PARSED.
"""

import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import pymupdf
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.ria import graph, jobs
from app.ria.indexing import build_index_views
from app.ria.legal_parser import RE_DOC_NUMBER, parse_pdf
from app.ria.obligations import ClauseInput, extract_obligations
from app.ria.schema import ensure_schema
from app.ria.storage import get_storage


class IngestError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def document_id_for(doc_number: str | None, checksum: str) -> str:
    if not doc_number:
        return f"REG-{checksum[:10].upper()}"
    ascii_number = doc_number.upper().replace("Đ", "D")
    return "REG-" + re.sub(r"[^A-Z0-9]+", "-", ascii_number).strip("-")


def _peek_doc_number(data: bytes) -> tuple[str | None, int]:
    """Open the PDF (validates it) and read the document number from the first page."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise IngestError(422, f"file is not a readable PDF: {exc}") from exc
    if doc.needs_pass:
        raise IngestError(422, "PDF is password protected")
    if len(doc) == 0:
        raise IngestError(422, "PDF has no pages")
    first = doc[0].get_text()
    for line in first.splitlines()[:40]:
        if re.search(r"\bsố\b", line, re.IGNORECASE) and (m := RE_DOC_NUMBER.search(line)):
            return m.group(1), len(doc)
    return None, len(doc)


def _latest_parse_job(conn, version_id: str) -> dict | None:
    row = (
        conn.execute(
            text(
                "SELECT job_id, status FROM job WHERE version_id = :v AND job_type = 'parse' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"v": version_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def create_regulation(
    data: bytes,
    file_name: str,
    content_type: str | None,
    overrides: dict,
) -> tuple[dict, bool]:
    """Returns (response body, created). created=False means an identical file already exists."""
    settings = get_settings()
    if not data:
        raise IngestError(422, "empty file")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise IngestError(413, f"file larger than {settings.max_upload_mb} MB")
    if not data.startswith(b"%PDF-"):
        raise IngestError(415, "only PDF files are supported (missing %PDF- header)")

    checksum = hashlib.sha256(data).hexdigest()
    doc_number = overrides.get("doc_number")
    peeked, page_count = _peek_doc_number(data)
    doc_number = doc_number or peeked
    document_id = document_id_for(doc_number, checksum)

    ensure_schema()
    with get_engine().begin() as conn:
        # Serialise uploads of the same logical document so version labels stay unique.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:d))"), {"d": document_id})
        existing = (
            conn.execute(
                text(
                    "SELECT v.version_id, v.document_id, v.processing_status, d.doc_type "
                    "FROM document_version v JOIN document d USING (document_id) "
                    "WHERE v.checksum = :c"
                ),
                {"c": f"sha256:{checksum}"},
            )
            .mappings()
            .first()
        )
        if existing:
            body, created = _existing_version(conn, existing)
        else:
            body = _new_version(
                conn,
                data,
                file_name,
                content_type,
                overrides,
                document_id,
                doc_number,
                checksum,
                page_count,
            )
            created = True
    if created:
        jobs.submit(body["job_id"])
    return body, created


def _existing_version(conn, existing) -> tuple[dict, bool]:
    """Same file uploaded again: return it; if its parse failed, queue a retry."""
    if existing["doc_type"] != "regulation":
        raise IngestError(409, f"file already stored as {existing['document_id']}")
    last = _latest_parse_job(conn, existing["version_id"])
    body = {
        "regulation_id": existing["document_id"],
        "version_id": existing["version_id"],
        "job_id": last["job_id"] if last else None,
        "status": existing["processing_status"],
        "duplicate": True,
    }
    if existing["processing_status"] != "DRAFT" or (last and last["status"] != "failed"):
        return body, False
    body["job_id"] = jobs.create_job(
        conn,
        "parse",
        existing["document_id"],
        existing["version_id"],
        {"retry_of": last["job_id"] if last else None},
    )
    return body, True


def _new_version(
    conn,
    data: bytes,
    file_name: str,
    content_type: str | None,
    overrides: dict,
    document_id: str,
    doc_number: str | None,
    checksum: str,
    page_count: int,
) -> dict:
    doc = conn.execute(
        text("SELECT doc_type FROM document WHERE document_id = :d"), {"d": document_id}
    ).scalar()
    if doc is None:
        conn.execute(
            text(
                "INSERT INTO document (document_id, title, doc_type, owner, doc_number) "
                "VALUES (:d, :title, 'regulation', :owner, :num)"
            ),
            {
                "d": document_id,
                "title": overrides.get("title") or Path(file_name).stem,
                "owner": overrides.get("owner") or "external",
                "num": doc_number,
            },
        )
    elif doc != "regulation":
        raise IngestError(409, f"{document_id} exists as a {doc} document")

    n_versions = conn.execute(
        text("SELECT count(*) FROM document_version WHERE document_id = :d"),
        {"d": document_id},
    ).scalar()
    label = f"v{n_versions + 1}"
    version_id = f"{document_id}@{label}"
    key = f"regulations/{document_id}/{label}/{checksum[:16]}.pdf"
    uri = get_storage().put(key, data, "application/pdf")
    checks = [
        {"check": "format", "status": "pass", "detail": "PDF header and structure valid"},
        {"check": "checksum", "status": "pass", "detail": f"sha256:{checksum}"},
        {"check": "malware_scan", "status": "skipped", "detail": "no scanner configured"},
    ]
    conn.execute(
        text(
            "INSERT INTO document_version (version_id, document_id, version_label, status, "
            "checksum, processing_status, source_uri, file_name, mime_type, page_count, "
            "valid_from, metadata) VALUES (:v, :d, :label, 'pending', :c, 'DRAFT', :uri, "
            ":name, :mime, :pages, :valid_from, CAST(:meta AS jsonb))"
        ),
        {
            "v": version_id,
            "d": document_id,
            "label": label,
            "c": f"sha256:{checksum}",
            "uri": uri,
            "name": file_name,
            "mime": content_type or "application/pdf",
            "pages": page_count,
            "valid_from": overrides.get("valid_from"),
            "meta": json.dumps({"ingest_checks": checks, "overrides": overrides}),
        },
    )
    job_id = jobs.create_job(conn, "parse", document_id, version_id, {"source_uri": uri})
    return {
        "regulation_id": document_id,
        "version_id": version_id,
        "version_label": label,
        "job_id": job_id,
        "status": "DRAFT",
        "duplicate": False,
        "checks": checks,
    }


# --- Parse job ---------------------------------------------------------------------------


def _resolve_doc_numbers(conn, numbers: set[str]) -> dict[str, str]:
    if not numbers:
        return {}
    rows = conn.execute(
        text("SELECT doc_number, document_id FROM document WHERE doc_number = ANY(:n)"),
        {"n": list(numbers)},
    )
    return {num: doc_id for num, doc_id in rows}


def run_parse(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    version_id, document_id = job["version_id"], job["document_id"]
    with get_engine().connect() as conn:
        version = (
            conn.execute(
                text("SELECT * FROM document_version WHERE version_id = :v"), {"v": version_id}
            )
            .mappings()
            .first()
        )
    if version["processing_status"] != "DRAFT":
        raise RuntimeError(f"{version_id} is {version['processing_status']}, expected DRAFT")
    overrides = (version["metadata"] or {}).get("overrides", {})

    jobs.update_progress(job_id, "extracting_text", 10)
    parsed = parse_pdf(get_storage().get(version["source_uri"]))
    meta = parsed.metadata

    jobs.update_progress(job_id, "persisting_structure", 40)
    with get_engine().begin() as conn:
        numbering_to_id: dict[str, str] = {}
        used: set[str] = set()
        clause_rows = []
        for ordinal, c in enumerate(parsed.clauses):
            numbering = c.numbering
            while f"{version_id}#{numbering}" in used:  # defensive: keep ids unique
                numbering += "~"
            clause_id = f"{version_id}#{numbering}"
            used.add(clause_id)
            numbering_to_id.setdefault(c.numbering, clause_id)
            clause_rows.append(
                {
                    "id": clause_id,
                    "v": version_id,
                    "parent": numbering_to_id.get(c.parent) if c.parent else None,
                    "num": numbering,
                    "level": c.level,
                    "heading": c.heading,
                    "text": c.text,
                    "page": c.page,
                    "start": c.start,
                    "end": c.end,
                    "bbox": json.dumps(c.bbox),
                    "ord": ordinal,
                }
            )
        conn.execute(
            text(
                "INSERT INTO clause (clause_id, version_id, parent_id, numbering, level, heading, "
                "text, page, char_start, char_end, bbox, ordinal) VALUES (:id, :v, :parent, :num, "
                ":level, :heading, :text, :page, :start, :end, CAST(:bbox AS jsonb), :ord)"
            ),
            clause_rows,
        )

        # References: other documents by number, or clauses of this document.
        resolved_docs = _resolve_doc_numbers(
            conn, {r.target_doc_number for r in parsed.references if r.target_doc_number}
        )
        ref_rows = []
        for i, r in enumerate(parsed.references):
            target_clause = numbering_to_id.get(r.target_numbering) if r.target_numbering else None
            ok = target_clause or (r.target_doc_number and r.target_doc_number in resolved_docs)
            ref_rows.append(
                {
                    "id": f"{version_id}#ref{i + 1}",
                    "src": numbering_to_id[r.source_numbering],
                    "ref": r.ref_text,
                    "num": r.target_doc_number,
                    "tgt": target_clause,
                    "status": "resolved" if ok else "missing_source",
                }
            )
        if ref_rows:
            conn.execute(
                text(
                    "INSERT INTO reference_edge (edge_id, source_clause_id, ref_text, "
                    "target_doc_number, target_clause_id, status) "
                    "VALUES (:id, :src, :ref, :num, :tgt, :status)"
                ),
                ref_rows,
            )

        jobs.update_progress(job_id, "extracting_obligations", 60)
        obligations = extract_obligations(
            [ClauseInput(c.numbering, c.level, c.text, c.parent, c.heading) for c in parsed.clauses]
        )
        obl_rows = []
        for numbering, items in obligations.items():
            clause_id = numbering_to_id[numbering]
            for n, o in enumerate(items, start=1):
                obl_rows.append(
                    {
                        "id": f"{clause_id}~o{n}",
                        "src": clause_id,
                        "subject": o.subject,
                        "action": o.action,
                        "object": o.object,
                        "modality": o.modality,
                        "condition": o.condition,
                        "deadline": o.deadline,
                        "exception": o.exception,
                        "text": o.text,
                        "start": o.span_start,
                        "end": o.span_end,
                    }
                )

        if not obl_rows:
            substantive = [
                c
                for c in parsed.clauses
                if c.level in ("article", "clause", "point") and len(c.text.strip()) >= 20
            ]
            for c in substantive:
                clause_id = numbering_to_id.get(c.numbering)
                if not clause_id:
                    continue
                obl_rows.append(
                    {
                        "id": f"{clause_id}~o1",
                        "src": clause_id,
                        "subject": c.heading or meta.get("issuer") or "Đơn vị áp dụng",
                        "action": "thực hiện",
                        "object": c.text[:200],
                        "modality": "must",
                        "condition": None,
                        "deadline": None,
                        "exception": None,
                        "text": c.text,
                        "start": 0,
                        "end": len(c.text),
                    }
                )

        if obl_rows:
            conn.execute(
                text(
                    "INSERT INTO obligation (obligation_id, source_clause_id, subject, action, "
                    "object, modality, condition, deadline, exception, text, span_start, span_end, "
                    "extraction_method) VALUES (:id, :src, :subject, :action, :object, :modality, "
                    ":condition, :deadline, :exception, :text, :start, :end, 'rule')"
                ),
                obl_rows,
            )
            conn.execute(
                text(
                    "INSERT INTO obligation_clause (obligation_id, clause_id, role) "
                    "VALUES (:id, :src, 'source')"
                ),
                [{"id": r["id"], "src": r["src"]} for r in obl_rows],
            )

        jobs.update_progress(job_id, "indexing", 75)
        # Regulation clauses are the query side: sparse views only, no embedding cost here.
        index_stats = build_index_views(conn, version_id, with_embeddings=False)

        # Legal version resolution: effective dates and superseded versions.
        valid_from = overrides.get("valid_from") or meta.get("valid_from")
        if valid_from:
            legal_status = (
                "effective" if date.fromisoformat(valid_from) <= date.today() else "pending"
            )
        else:
            legal_status = "unknown"
        superseded = _supersede(conn, document_id, version_id, meta, valid_from)

        title = overrides.get("title") or " ".join(
            p
            for p in (
                (meta.get("legal_form") or "").capitalize(),
                meta.get("doc_number"),
                f"– {meta['subject']}" if meta.get("subject") else None,
            )
            if p
        )
        conn.execute(
            text(
                "UPDATE document SET title = COALESCE(NULLIF(:title, ''), title), "
                "owner = CASE WHEN owner = 'external' AND CAST(:issuer AS text) IS NOT NULL "
                "THEN :issuer ELSE owner END, "
                "doc_number = COALESCE(doc_number, :num), issuer = :issuer, legal_form = :form "
                "WHERE document_id = :d"
            ),
            {
                "title": title,
                "issuer": meta.get("issuer"),
                "num": meta.get("doc_number"),
                "form": meta.get("legal_form"),
                "d": document_id,
            },
        )
        conn.execute(
            text(
                "UPDATE document_version SET content = :content, page_count = :pages, "
                "valid_from = :valid_from, issued_date = :issued, status = :status, "
                "processing_status = 'PARSED', "
                "metadata = metadata || CAST(:meta AS jsonb) WHERE version_id = :v"
            ),
            {
                "content": parsed.text,
                "pages": parsed.page_count,
                "valid_from": valid_from,
                "issued": meta.get("issued_date"),
                "status": legal_status,
                "meta": json.dumps({"parsed": meta, "parse_warnings": parsed.warnings}),
                "v": version_id,
            },
        )

    graph_stats = None
    if graph.enabled():
        # Derived index: a graph outage must not fail an otherwise good parse.
        try:
            with get_engine().begin() as conn:
                graph_stats = graph.sync_version(conn, version_id)
        except Exception as exc:
            graph_stats = {"error": f"{exc.__class__.__name__}: {exc}"[:300]}

    refs = Counter(r["status"] for r in ref_rows)
    return {
        "regulation_id": document_id,
        "version_id": version_id,
        "status": "PARSED",
        "metadata": meta,
        "legal_status": legal_status,
        "pages": parsed.page_count,
        "clauses": dict(Counter(c.level for c in parsed.clauses)),
        "obligations": len(obl_rows),
        "obligations_by_modality": dict(Counter(r["modality"] for r in obl_rows)),
        "references": dict(refs),
        "superseded_versions": superseded,
        "index": index_stats,
        "graph": graph_stats,
        "warnings": parsed.warnings,
    }


def _supersede(conn, document_id: str, version_id: str, meta: dict, valid_from) -> list[str]:
    """Earlier versions of this document, and documents this one repeals, become superseded."""
    numbers = meta.get("supersedes", [])
    rows = conn.execute(
        text(
            "UPDATE document_version v SET status = 'superseded', "
            "valid_to = COALESCE(v.valid_to, CAST(:vf AS date)) "
            "FROM document d WHERE d.document_id = v.document_id AND v.version_id <> :v "
            "AND v.status <> 'superseded' AND d.doc_type = 'regulation' "
            "AND (v.document_id = :d OR d.doc_number = ANY(:nums)) RETURNING v.version_id"
        ),
        {"vf": valid_from, "v": version_id, "d": document_id, "nums": numbers},
    )
    return list(rows.scalars())


jobs.register("parse", run_parse)
