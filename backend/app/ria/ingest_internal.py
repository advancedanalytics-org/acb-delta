"""Ingest internal bank documents (văn bản nội bộ) from data/ into VectorDB.

Follows the structural parsing and chunking format of run_parse in backend/app/ria/ingest.py.
Extracts chapters, articles, clauses, points, and appendices with exact character offsets
and bounding boxes, stores them in the RIA schema (document, document_version, clause,
reference_edge, obligation, index_view), and populates vector embeddings.

Usage:
    cd backend && uv run python -m app.ria.ingest_internal [dir_or_files ...]
    (Defaults to scanning ../data/*.pdf or data/*.pdf)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import threading
from datetime import UTC, date, datetime
from pathlib import Path

import pymupdf
from sqlalchemy import text

from app.db import get_engine
from app.ria import legal_parser, obligations, textutil
from app.ria.indexing import build_index_views
from app.ria.legal_parser import extract_references, parse_pdf
from app.ria.obligations import ClauseInput, extract_obligations
from app.ria.schema import ensure_schema

logger = logging.getLogger(__name__)

# Fingerprint of the code that turns a PDF into clauses and obligations. Stored on each version:
# re-uploading an unchanged PDF is skipped only when it was parsed by this same code, so a parser
# fix (e.g. dropping page footers) reaches documents ingested before it.
PARSER_VERSION = hashlib.sha256(
    b"".join(Path(m.__file__).read_bytes() for m in (legal_parser, obligations, textutil))
).hexdigest()[:12]

_CURRENT_INGEST_JOB: dict = {
    "is_processing": False,
    "filename": None,
    "status": "idle",
    "message": None,
    "error": None,
    "progress": None,
    "started_at": None,
    "completed_at": None,
    "result": None,
}
_JOB_LOCK = threading.Lock()


def get_current_ingest_job() -> dict:
    with _JOB_LOCK:
        return dict(_CURRENT_INGEST_JOB)


def set_current_ingest_job(**kwargs) -> dict:
    with _JOB_LOCK:
        _CURRENT_INGEST_JOB.update(kwargs)
        return dict(_CURRENT_INGEST_JOB)


def extract_internal_metadata(pdf_bytes: bytes, filename: str) -> dict:
    """Extract standard metadata from internal bank document PDFs."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page_count = len(doc)
    p1 = doc[0].get_text("text") if page_count > 0 else ""
    p2 = doc[1].get_text("text") if page_count > 1 else ""
    full_head = p1 + "\n" + p2

    stem = Path(filename).stem

    # 1. Document ID (e.g. DOC-215)
    m_id = (
        re.search(r"Mã tài liệu:\s*([A-Za-z0-9_-]+)", full_head, re.IGNORECASE)
        or re.search(r"\b(DOC-\d+)\b", stem, re.IGNORECASE)
        or re.search(r"\b(DOC-\d+)\b", full_head, re.IGNORECASE)
    )
    doc_id = m_id.group(1).upper() if m_id else stem.upper()

    # 2. Version label (e.g. 2.0 -> v2, 1.0 -> v1)
    m_ver = re.search(r"Phiên bản:?\s*([0-9.]+)", full_head, re.IGNORECASE)
    if m_ver:
        ver_str = m_ver.group(1).strip()
        try:
            ver_label = f"v{int(float(ver_str))}"
        except ValueError:
            ver_label = f"v{ver_str}"
    else:
        ver_label = "v1"

    # 3. Document number (e.g. 42/2025/QĐ-TGĐ)
    m_num = re.search(r"Số:\s*([^\s\n]+)", full_head)
    doc_number = m_num.group(1).strip() if m_num else None

    # 4. Title
    m_title = re.search(r"Về việc ban hành\s+([^\n]+(?:\n[^\n]+)?)", p1)
    if m_title:
        title = " ".join(m_title.group(1).split()).strip(" .;,")
    else:
        m_reg_title = re.search(r"(?:QUY ĐỊNH|QUY CHẾ|QUY TRÌNH)\n([^\n]+(?:\n[^\n]+)?)", p2)
        if m_reg_title:
            title = " ".join(m_reg_title.group(0).split()).strip(" .;,")
        else:
            title = stem

    # 5. Owner
    m_owner = re.search(r"Đơn vị sở hữu:\s*([^\n·]+)", full_head)
    if not m_owner:
        m_owner = re.search(r"NGÂN HÀNG[^\n]+\n([^\n]+)", p1)
    owner = m_owner.group(1).strip() if m_owner else "Khối Tuân thủ"

    # 6. Valid from
    m_valid = re.search(r"Hiệu lực:\s*(\d{2}/\d{2}/\d{4})", full_head)
    if m_valid:
        d, m, y = m_valid.group(1).split("/")
        valid_from = f"{y}-{m}-{d}"
    else:
        m_date = re.search(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", p1)
        if m_date:
            d, m, y = m_date.groups()
            valid_from = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        else:
            valid_from = date.today().isoformat()

    return {
        "document_id": doc_id,
        "version_label": ver_label,
        "version_id": f"{doc_id}@{ver_label}",
        "doc_number": doc_number,
        "title": title,
        "owner": owner,
        "issuer": "Ngân hàng TMCP Á Châu",
        "valid_from": valid_from,
        "page_count": page_count,
    }


def upload_to_minio(doc_id: str, filename: str, pdf_bytes: bytes) -> str | None:
    """Upload internal PDF to MinIO S3 bucket under internal/{doc_id}/{filename}."""
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
        try:
            s3.head_bucket(Bucket=settings.s3_bucket)
        except Exception:
            s3.create_bucket(Bucket=settings.s3_bucket)

        key = f"internal/{doc_id}/{filename}"
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=f"internal/{doc_id}.pdf",
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        return f"s3://{settings.s3_bucket}/{key}"
    except Exception as exc:
        logger.warning("Could not upload %s to MinIO: %s", filename, exc)
        return None


def _do_ingest_internal_pdf(path: Path) -> dict:
    pdf_bytes = path.read_bytes()
    checksum = f"sha256:{hashlib.sha256(pdf_bytes).hexdigest()}"

    ensure_schema()
    with get_engine().connect() as conn:
        existing = (
            conn.execute(
                text(
                    "SELECT v.version_id, v.document_id, v.file_name, v.parser_version, d.title, "
                    "d.doc_type, "
                    "(SELECT count(*) FROM clause WHERE version_id = v.version_id) AS clause_count "
                    "FROM document_version v "
                    "JOIN document d USING (document_id) "
                    "WHERE v.checksum = :c"
                ),
                {"c": checksum},
            )
            .mappings()
            .first()
        )
        if existing and existing["parser_version"] != PARSER_VERSION:
            logger.info(
                "[%s] Same file as %s but parsed by older code (%s → %s). Re-parsing.",
                path.name,
                existing["version_id"],
                existing["parser_version"],
                PARSER_VERSION,
            )
        elif existing:
            existing_doc_id = existing["document_id"]
            existing_title = existing["title"]
            existing_file = existing["file_name"]

            if existing_file and existing_title and existing_title != existing_doc_id:
                doc_label = f'"{existing_title}" ({existing_file})'
            elif existing_title:
                doc_label = f'"{existing_title}"'
            elif existing_file:
                doc_label = f'"{existing_file}"'
            else:
                doc_label = f'"{existing_doc_id}"'

            msg = f"Nội dung tệp không có thay đổi so với tài liệu {doc_label}."
            logger.info(
                "[%s] Checksum matches existing version %s (%s). Skipping ingest.",
                path.name,
                existing["version_id"],
                doc_label,
            )
            print(f">>> [INGEST SKIPPED] {path.name}: {msg}", flush=True)
            return {
                "document_id": existing_doc_id,
                "version_id": existing["version_id"],
                "title": existing_title or existing_doc_id,
                "clauses": existing["clause_count"] or 0,
                "obligations": 0,
                "views_indexed": 0,
                "status": "unchanged",
                "unchanged": True,
                "message": msg,
            }

    meta = extract_internal_metadata(pdf_bytes, path.name)
    logger.info(
        "[%s] Metadata: %s, title='%s', pages=%d",
        path.name,
        meta["version_id"],
        meta["title"][:60],
        meta["page_count"],
    )

    # 1. Parse document structure (exact format used by run_parse)
    parsed = parse_pdf(pdf_bytes)
    version_id = meta["version_id"]
    document_id = meta["document_id"]
    logger.info("[%s] Parsed %d clauses from PDF", path.name, len(parsed.clauses))
    set_current_ingest_job(
        message=f"Đã trích xuất {len(parsed.clauses)} điều khoản ({path.name}), đang lưu dữ liệu..."
    )

    # Upload to MinIO
    s3_uri = upload_to_minio(document_id, path.name, pdf_bytes)
    source_uri = s3_uri or str(path)

    with get_engine().begin() as conn:
        # 2. Upsert document table
        conn.execute(
            text(
                "INSERT INTO document (document_id, title, doc_type, owner, doc_number, issuer, "
                "legal_form) "
                "VALUES (:id, :title, 'internal', :owner, :num, :issuer, 'QUYẾT ĐỊNH') "
                "ON CONFLICT (document_id) DO UPDATE SET "
                "title = EXCLUDED.title, owner = EXCLUDED.owner, "
                "doc_number = COALESCE(EXCLUDED.doc_number, document.doc_number), "
                "issuer = COALESCE(EXCLUDED.issuer, document.issuer)"
            ),
            {
                "id": document_id,
                "title": meta["title"],
                "owner": meta["owner"],
                "num": meta["doc_number"],
                "issuer": meta["issuer"],
            },
        )

        # 3. Upsert document_version table (effective and PARSED)
        conn.execute(
            text(
                "INSERT INTO document_version (version_id, document_id, version_label, status, "
                "valid_from, checksum, processing_status, page_count, content, source_uri, "
                "file_name, parser_version) "
                "VALUES (:v, :d, :label, 'effective', :vf, :c, 'PARSED', :pages, :content, "
                ":src, :name, :pv) "
                "ON CONFLICT (version_id) DO UPDATE SET "
                "status = 'effective', processing_status = 'PARSED', "
                "valid_from = EXCLUDED.valid_from, page_count = EXCLUDED.page_count, "
                "content = COALESCE(EXCLUDED.content, document_version.content), "
                "source_uri = EXCLUDED.source_uri, "
                "checksum = EXCLUDED.checksum, "
                "file_name = EXCLUDED.file_name, "
                "parser_version = EXCLUDED.parser_version"
            ),
            {
                "v": version_id,
                "d": document_id,
                "label": meta["version_label"],
                "vf": meta["valid_from"],
                "c": checksum,
                "pages": parsed.page_count,
                "content": parsed.text,
                "src": source_uri,
                "name": path.name,
                "pv": PARSER_VERSION,
            },
        )

        # 4. Clean previous clauses/index views for clean idempotent re-ingest
        conn.execute(
            text("DELETE FROM index_view WHERE clause_id LIKE :prefix"),
            {"prefix": f"{version_id}%"},
        )
        conn.execute(
            text("DELETE FROM obligation_clause WHERE clause_id LIKE :prefix"),
            {"prefix": f"{version_id}%"},
        )
        conn.execute(
            text("DELETE FROM obligation WHERE source_clause_id LIKE :prefix"),
            {"prefix": f"{version_id}%"},
        )
        conn.execute(
            text("DELETE FROM reference_edge WHERE source_clause_id LIKE :prefix"),
            {"prefix": f"{version_id}%"},
        )
        # Avoid deleting clauses referenced by existing evidence
        conn.execute(
            text(
                "DELETE FROM clause WHERE version_id = :v "
                "AND clause_id NOT IN (SELECT internal_clause_id FROM evidence)"
            ),
            {"v": version_id},
        )

        # 5. Insert clauses (Chương / Mục / Điều / Khoản / Điểm / Phụ lục / Chunk)
        numbering_to_id: dict[str, str] = {}
        used: set[str] = set()
        clause_rows = []
        for ordinal, c in enumerate(parsed.clauses):
            numbering = c.numbering
            while f"{version_id}#{numbering}" in used:
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

        if clause_rows:
            conn.execute(
                text(
                    "INSERT INTO clause (clause_id, version_id, parent_id, numbering, level, "
                    "heading, text, page, char_start, char_end, bbox, ordinal) "
                    "VALUES (:id, :v, :parent, :num, :level, :heading, :text, :page, :start, "
                    ":end, CAST(:bbox AS jsonb), :ord) "
                    "ON CONFLICT (clause_id) DO UPDATE SET "
                    "parent_id = EXCLUDED.parent_id, numbering = EXCLUDED.numbering, "
                    "level = EXCLUDED.level, heading = EXCLUDED.heading, text = EXCLUDED.text, "
                    "page = COALESCE(EXCLUDED.page, clause.page), "
                    "char_start = EXCLUDED.char_start, char_end = EXCLUDED.char_end, "
                    "bbox = COALESCE(EXCLUDED.bbox, clause.bbox), ordinal = EXCLUDED.ordinal"
                ),
                clause_rows,
            )

        # 6. Cross references
        refs = extract_references(parsed.clauses, meta["doc_number"])
        ref_rows = []
        for i, r in enumerate(refs):
            target_clause = numbering_to_id.get(r.target_numbering) if r.target_numbering else None
            src_cid = numbering_to_id.get(r.source_numbering, f"{version_id}#{r.source_numbering}")
            ref_rows.append(
                {
                    "id": f"{version_id}#ref{i + 1}",
                    "src": src_cid,
                    "ref": r.ref_text,
                    "num": r.target_doc_number,
                    "tgt": target_clause,
                    "status": "resolved" if target_clause else "missing_source",
                }
            )
        if ref_rows:
            conn.execute(
                text(
                    "INSERT INTO reference_edge (edge_id, source_clause_id, ref_text, "
                    "target_doc_number, target_clause_id, status) "
                    "VALUES (:id, :src, :ref, :num, :tgt, :status) ON CONFLICT DO NOTHING"
                ),
                ref_rows,
            )

        # 7. Obligations
        obligations = extract_obligations(
            [ClauseInput(c.numbering, c.level, c.text, c.parent, c.heading) for c in parsed.clauses]
        )
        obl_rows = []
        for numbering, items in obligations.items():
            cid = numbering_to_id.get(numbering)
            if not cid:
                continue
            for n, o in enumerate(items, start=1):
                obl_rows.append(
                    {
                        "id": f"{cid}~o{n}",
                        "src": cid,
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
        if obl_rows:
            conn.execute(
                text(
                    "INSERT INTO obligation (obligation_id, source_clause_id, subject, action, "
                    "object, modality, condition, deadline, exception, text, span_start, span_end, "
                    "extraction_method) VALUES (:id, :src, :subject, :action, :object, :modality, "
                    ":condition, :deadline, :exception, :text, :start, :end, 'rule') "
                    "ON CONFLICT DO NOTHING"
                ),
                obl_rows,
            )
            conn.execute(
                text(
                    "INSERT INTO obligation_clause (obligation_id, clause_id, role) "
                    "VALUES (:id, :src, 'source') ON CONFLICT DO NOTHING"
                ),
                [{"id": r["id"], "src": r["src"]} for r in obl_rows],
            )

        # 8. Multi-view index and vector embeddings (raw / context / keywords + pgvector)
        logger.info(
            "[%s] Generating vector embeddings for %s...",
            path.name,
            version_id,
        )
        stats = build_index_views(conn, version_id, with_embeddings=True)
        logger.info(
            "[%s] FINISHED: %s -> %s (%d clauses, %d obligations, %d vectors)",
            path.name,
            path.name,
            document_id,
            len(clause_rows),
            len(obl_rows),
            stats.get("views", 0),
        )
        print(
            f">>> [INGEST FINISHED] {path.name} -> {document_id} "
            f"({len(clause_rows)} clauses, {stats.get('views', 0)} vectors)",
            flush=True,
        )

        # 9. Sync into LangChain PGVector tables (documents & document_chunks). Optional, so it
        # runs in a savepoint: a failure here must not roll back the RIA ingest above.
        try:
            with conn.begin_nested():
                conn.execute(
                    text(
                        "INSERT INTO documents (id, code, title, doc_type, issuer, effective_date, "
                        "page_count, pdf_url, created_at) "
                        "VALUES (:id, :code, :title, 'internal', :issuer, :vf, :pages, :url, "
                        "NOW()) "
                        "ON CONFLICT (id) DO UPDATE SET "
                        "title = EXCLUDED.title, page_count = EXCLUDED.page_count, "
                        "effective_date = EXCLUDED.effective_date"
                    ),
                    {
                        "id": document_id,
                        "code": document_id,
                        "title": meta["title"],
                        "issuer": meta["issuer"],
                        "vf": meta["valid_from"],
                        "pages": parsed.page_count,
                        "url": str(path),
                    },
                )
                conn.execute(
                    text("DELETE FROM document_chunks WHERE doc_id = :d"),
                    {"d": document_id},
                )
                chunk_rows = []
                for row in clause_rows:
                    bbox_val = "[]"
                    if row["bbox"] and row["bbox"] != "[]":
                        raw_boxes = json.loads(row["bbox"])
                        if raw_boxes:
                            bbox_val = json.dumps(raw_boxes[0][1:])
                    chunk_rows.append(
                        {
                            "id": row["id"],
                            "doc_id": document_id,
                            "doc_type": "internal",
                            "issuer": meta["issuer"],
                            "effective_date": meta["valid_from"],
                            "article_path": row["num"],
                            "page": row["page"] or 1,
                            "bbox": bbox_val,
                            "text": row["text"],
                            "meta": json.dumps(
                                {
                                    "level": row["level"],
                                    "heading": row["heading"],
                                    "version_id": version_id,
                                }
                            ),
                        }
                    )
                if chunk_rows:
                    conn.execute(
                        text(
                            "INSERT INTO document_chunks (id, doc_id, doc_type, issuer, "
                            "effective_date, article_path, page, bbox, text, chunk_metadata, "
                            "created_at) "
                            "VALUES (:id, :doc_id, :doc_type, :issuer, :effective_date, "
                            ":article_path, :page, CAST(:bbox AS json), :text, "
                            "CAST(:meta AS json), NOW())"
                        ),
                        chunk_rows,
                    )
        except Exception as exc:
            logger.debug("LangChain PGVector tables sync optional: %s", exc)

        return {
            "document_id": document_id,
            "version_id": version_id,
            "title": meta["title"],
            "clauses": len(clause_rows),
            "obligations": len(obl_rows),
            "views_indexed": stats.get("views", 0),
            "status": "effective",
        }


def ingest_internal_pdf(pdf_path: Path | str) -> dict:
    """Parse an internal document PDF and ingest its clauses and vectors into vectorDB."""
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found: {path}")

    logger.info(">>> [INGESTING] Processing file: %s (%d bytes)", path.name, path.stat().st_size)
    print(f"\n>>> [INGEST] Processing file: {path.name}", flush=True)

    set_current_ingest_job(
        is_processing=True,
        filename=path.name,
        status="processing",
        message=f"Đang đọc và phân tích cấu trúc: {path.name}",
        started_at=datetime.now(UTC).isoformat(),
        error=None,
    )
    try:
        res = _do_ingest_internal_pdf(path)
        message = res.get("message") or (
            f"Nạp thành công {res['document_id']} ({res['clauses']} điều khoản, "
            f"{res['views_indexed']} vector index)"
        )
        set_current_ingest_job(
            is_processing=False,
            status="completed",
            completed_at=datetime.now(UTC).isoformat(),
            message=message,
            result=res,
            error=None,
        )
        return res
    except Exception as exc:
        set_current_ingest_job(
            is_processing=False,
            status="failed",
            completed_at=datetime.now(UTC).isoformat(),
            message=f"Lỗi nạp {path.name}: {exc}",
            error=str(exc),
        )
        raise


def find_data_dir() -> Path:
    """Locate the internal documents data directory."""
    candidates = (
        Path("/data"),
        Path("../data"),
        Path("./data"),
        Path("data"),
        Path(__file__).resolve().parents[3] / "data",
    )
    for c in candidates:
        if c.is_dir() and any(c.glob("*.pdf")):
            return c
    raise FileNotFoundError("Could not find data/ folder containing internal document PDFs")


def ingest_all(targets: list[str] | None = None) -> list[dict]:
    """Ingest all specified PDFs or all PDFs found in data/."""
    files: list[Path] = []
    if targets:
        for t in targets:
            p = Path(t)
            if p.is_dir():
                files.extend(sorted(p.glob("*.pdf")))
            elif p.is_file():
                files.append(p)
    else:
        data_dir = find_data_dir()
        files = sorted(data_dir.glob("*.pdf"))

    if not files:
        logger.warning("No internal PDF documents found to ingest.")
        return []

    total = len(files)
    set_current_ingest_job(
        is_processing=True,
        filename=files[0].name if files else None,
        status="processing",
        progress=f"0/{total}",
        message=f"Đang tự động nạp {total} tài liệu nội bộ...",
        started_at=datetime.now(UTC).isoformat(),
        error=None,
    )
    logger.info("Found %d internal document(s) to ingest into VectorDB...", total)
    print(
        f"\n=======================================================\n"
        f"Found {total} internal document(s) to ingest into VectorDB\n"
        f"=======================================================\n",
        flush=True,
    )
    results = []
    for idx, f in enumerate(files, 1):
        set_current_ingest_job(
            filename=f.name,
            progress=f"{idx}/{total}",
            message=f"[{idx}/{total}] Đang nạp: {f.name}",
        )
        logger.info("[%d/%d] Starting ingest for internal document: %s", idx, total, f.name)
        print(f">>> [{idx}/{total}] Starting ingest: {f.name}", flush=True)
        try:
            res = ingest_internal_pdf(f)
            results.append(res)
            d_id, n_c, n_v = res["document_id"], res["clauses"], res["views_indexed"]
            logger.info(
                "[%d/%d] Successfully ingested %s: %s (%d clauses, %d views indexed)",
                idx,
                total,
                f.name,
                d_id,
                n_c,
                n_v,
            )
            print(
                f">>> [{idx}/{total}] COMPLETED: {f.name} -> {d_id} "
                f"({n_c} clauses, {n_v} vectors)\n",
                flush=True,
            )
        except Exception as exc:
            logger.exception("[%d/%d] Failed to ingest %s: %s", idx, total, f, exc)
            print(f"!!! [{idx}/{total}] FAILED: {f.name} - error: {exc}\n", flush=True)

    set_current_ingest_job(
        is_processing=False,
        status="completed",
        completed_at=datetime.now(UTC).isoformat(),
        message=f"Đã hoàn thành nạp {len(results)}/{total} tài liệu nội bộ",
        progress=f"{total}/{total}",
    )
    logger.info("Successfully ingested %d/%d document(s) into VectorDB.", len(results), total)
    print(
        f"=== [INGEST DONE] Successfully ingested {len(results)}/{total} documents ===\n",
        flush=True,
    )
    return results


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    results = ingest_all(argv if argv else None)
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
