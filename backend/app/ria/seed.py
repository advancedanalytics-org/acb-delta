"""Load parsed internal documents (db/*.parsed.json) into the RIA tables and index them.

Usage (from backend/): uv run python -m app.ria.seed ../db/DOC-102.parsed.json [more.json ...]
Idempotent: re-running updates clause text and rebuilds the index views.
"""

import json
import re
import sys
from pathlib import Path

from sqlalchemy import text

from app.db import get_engine
from app.ria import graph
from app.ria.indexing import build_index_views
from app.ria.schema import ensure_schema


def infer_level(numbering: str) -> str:
    """DOC-102 numbering: I (chương), 5 (điều), 5.2 (khoản), 5.6.a (điểm), PL-I (phụ lục)."""
    if re.fullmatch(r"[IVXLC]+", numbering):
        return "chapter"
    if re.fullmatch(r"\d+", numbering):
        return "article"
    if re.fullmatch(r"\d+\.\d+", numbering):
        return "clause"
    if re.fullmatch(r"\d+(\.\d+)?\.[a-zđ]", numbering):
        return "point"
    if re.fullmatch(r"PL-[IVXLC\d]+", numbering):
        return "appendix"
    if numbering.startswith("PL-"):
        return "point" if re.search(r"\.[a-zđ]$", numbering) else "clause"
    if numbering.startswith("QD."):
        return "article"
    return "part"


def seed_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    doc, ver = data["document"], data["document_version"]
    content = None
    for base in (path.parent, path.parent.parent):
        source = base / data.get("source_file", "")
        if data.get("source_file") and source.is_file():
            content = source.read_text(encoding="utf-8")
            break

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO document (document_id, title, doc_type, owner) "
                "VALUES (:id, :title, :type, :owner) ON CONFLICT (document_id) DO UPDATE SET "
                "title = EXCLUDED.title, owner = EXCLUDED.owner"
            ),
            {
                "id": doc["document_id"],
                "title": doc["title"],
                "type": doc["doc_type"],
                "owner": doc["owner"],
            },
        )
        conn.execute(
            text(
                "INSERT INTO document_version (version_id, document_id, version_label, status, "
                "valid_from, valid_to, checksum, processing_status, content, source_uri) "
                "VALUES (:id, :doc, :label, :status, :vf, :vt, :checksum, 'PARSED', "
                ":content, :src) "
                "ON CONFLICT (version_id) DO UPDATE SET status = EXCLUDED.status, "
                "valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to, "
                "content = COALESCE(EXCLUDED.content, document_version.content)"
            ),
            {
                "id": ver["version_id"],
                "doc": ver["document_id"],
                "label": ver["version_label"],
                "status": ver["status"],
                "vf": ver.get("valid_from"),
                "vt": ver.get("valid_to"),
                "checksum": ver["checksum"],
                "content": content,
                "src": data.get("source_file"),
            },
        )
        rows = []
        for ordinal, c in enumerate(data["clause"]):
            level = infer_level(c["numbering"])
            first_line = c["text"].split("\n", 1)[0].strip()
            rows.append(
                {
                    "id": c["clause_id"],
                    "v": c["version_id"],
                    "parent": c["parent_id"],
                    "num": c["numbering"],
                    "level": level,
                    "heading": first_line if level in ("chapter", "article", "appendix") else None,
                    "text": c["text"],
                    "page": c.get("page"),
                    "start": c["char_start"],
                    "end": c["char_end"],
                    "ord": ordinal,
                }
            )
        conn.execute(
            text(
                "INSERT INTO clause (clause_id, version_id, parent_id, numbering, level, heading, "
                "text, page, char_start, char_end, ordinal) VALUES (:id, :v, :parent, :num, "
                ":level, :heading, :text, :page, :start, :end, :ord) "
                "ON CONFLICT (clause_id) DO UPDATE SET "
                "text = EXCLUDED.text, level = EXCLUDED.level, heading = EXCLUDED.heading, "
                "char_start = EXCLUDED.char_start, char_end = EXCLUDED.char_end, "
                "ordinal = EXCLUDED.ordinal"
            ),
            rows,
        )
        stats = build_index_views(conn, ver["version_id"], with_embeddings=True)
        if graph.enabled():
            stats["graph"] = graph.sync_version(conn, ver["version_id"])
    return {
        "document_id": doc["document_id"],
        "version_id": ver["version_id"],
        "clauses": len(rows),
        **stats,
    }


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    ensure_schema()
    for arg in argv:
        print(json.dumps(seed_file(Path(arg)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
