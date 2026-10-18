"""Knowledge graph of documents, clauses and legal references in FalkorDB (design 06, 07; RIA 4.0
04B/05.4). Postgres stays the source of truth; the graph is a derived index for traversals that
retrieval alone misses:

    (:Doc {id, type, number, title})<-[:OF]-(:Version {id, status})<-[:IN]-(:Clause)
    (:Clause)-[:PART_OF]->(:Clause)          structure
    (:Clause)-[:REFERS_TO]->(:Clause)        "khoản 6 Điều 5 Quy định này"
    (:Clause|:Doc)-[:CITES]->(:LegalRef)     a document number or law title it relies on
    (:Doc)-[:IDENTIFIED_BY]->(:LegalRef)     the regulation's own number / title
    (:Doc)-[:SUPERSEDES]->(:LegalRef)        documents it repeals or replaces
    (:Obligation)-[:FROM]->(:Clause)

Used by Engine 1 to (a) link internal documents that cite the regulation, a law it replaces, or
the same legal basis, even when no clause text is similar, and (b) add clauses that depend on an
evidence clause by cross-reference. Disabled when FALKORDB_URL is empty.
"""

import logging
import re
import threading
import unicodedata
from datetime import UTC, datetime

from sqlalchemy import text

from app.config import get_settings
from app.ria.legal_parser import RE_DOC_NUMBER

log = logging.getLogger(__name__)

_client_lock = threading.Lock()
_client: dict = {}

# "Căn cứ Luật Phòng, chống rửa tiền số 14/2022/QH15 ngày …" and law titles cited in clauses.
_LAW_TITLE_RE = re.compile(
    r"\b(Bộ luật|Luật|Nghị định|Thông tư|Pháp lệnh)\s+"
    r"((?:[A-ZĐÀ-Ỹ][^\s,;.()]*|phòng|chống|và)(?:[ ,]+(?:[A-ZĐÀ-Ỹa-zđà-ỹ][^\s,;.()]*))*?)"
    r"(?=\s+số\b|\s+ngày\b|\s+và\s+các\b|[;.()\n]|$)",
)
_TITLE_STOP = re.compile(r"\b(này|đó|hiện hành|có liên quan)\b", re.IGNORECASE)
# Same-document references in internal documents: "Điều 10 Quy định này", "khoản 6 Điều 5",
# "tại Điều 5", "khoản 2 và khoản 5 Điều này".
_SELF_REF_RE = re.compile(
    r"(?:điểm\s+([a-zđ])\s+)?(?:khoản\s+(\d+)(?:\s*(?:,|và)\s*khoản\s+\d+)*\s+)?Điều\s+(\d+|này)"
    r"(?!\s*(?:của\s+(?:Luật|Bộ luật|Nghị định|Thông tư)|\d))",
    re.IGNORECASE,
)


def enabled() -> bool:
    return bool(get_settings().falkordb_url)


def reset_client() -> None:
    with _client_lock:
        _client.clear()


def _graph():
    with _client_lock:
        if "graph" not in _client:
            from falkordb import FalkorDB

            db = FalkorDB.from_url(get_settings().falkordb_url, socket_timeout=30)
            graph = db.select_graph(get_settings().falkordb_graph)
            for label, prop in (
                ("Doc", "id"),
                ("Version", "id"),
                ("Clause", "id"),
                ("LegalRef", "key"),
                ("Obligation", "id"),
            ):
                try:
                    graph.create_node_range_index(label, prop)
                except Exception:  # index already exists
                    pass
            _client["graph"] = graph
        return _client["graph"]


def query(cypher: str, params: dict | None = None) -> list[list]:
    return _graph().query(cypher, params or {}).result_set


# --- Legal reference keys ------------------------------------------------------------------


def number_key(number: str) -> str:
    return "no:" + unicodedata.normalize("NFC", number).upper().replace(" ", "")


def title_key(kind: str, title: str) -> str | None:
    title = _TITLE_STOP.split(title)[0]
    title = re.sub(r"\s+", " ", re.sub(r"[,;.()]", " ", title)).strip().lower()
    if len(title) < 4:
        return None
    kind = "luật" if kind.lower() == "bộ luật" else kind.lower()
    return f"title:{kind} {unicodedata.normalize('NFC', title)}"


def legal_refs(text_: str, self_number: str | None = None) -> list[tuple[str, str]]:
    """(key, label) for document numbers and law titles cited in a text."""
    refs: dict[str, str] = {}
    for m in RE_DOC_NUMBER.finditer(text_):
        if m.group(1) != self_number:
            refs[number_key(m.group(1))] = m.group(1)
    for m in _LAW_TITLE_RE.finditer(text_):
        key = title_key(m.group(1), m.group(2))
        if key:
            refs.setdefault(key, f"{m.group(1)} {m.group(2).strip()}")
    return list(refs.items())


def self_references(numbering: str, clause_text: str, by_numbering: set[str]) -> list[str]:
    """Numberings of clauses of the same document that `clause_text` refers to."""
    article = numbering.split(".")[0]
    out = []
    for m in _SELF_REF_RE.finditer(clause_text):
        point, art = m.group(1), m.group(3)
        art = article if art.lower() == "này" else art
        khoans = re.findall(r"khoản\s+(\d+)", m.group(0), re.IGNORECASE) or [None]
        for khoan in khoans:
            target = art + (f".{khoan}" if khoan else "")
            target += f".{point.lower()}" if point and len(khoans) == 1 else ""
            if target in by_numbering and target != numbering and target not in out:
                out.append(target)
    return out


# --- Sync Postgres → graph ----------------------------------------------------------------


def sync_version(conn, version_id: str) -> dict:
    """Upsert one document version and everything hanging off it. Idempotent (MERGE)."""
    doc = (
        conn.execute(
            text(
                "SELECT d.document_id, d.doc_type, d.doc_number, d.title, d.legal_form, "
                "v.status, v.content, v.metadata FROM document_version v "
                "JOIN document d USING (document_id) WHERE v.version_id = :v"
            ),
            {"v": version_id},
        )
        .mappings()
        .first()
    )
    if not doc:
        return {}
    clauses = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT clause_id, parent_id, numbering, level, text, char_start, char_end "
                "FROM clause WHERE version_id = :v ORDER BY ordinal"
            ),
            {"v": version_id},
        ).mappings()
    ]
    refs = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT e.source_clause_id, e.target_doc_number, e.target_clause_id "
                "FROM reference_edge e JOIN clause c ON c.clause_id = e.source_clause_id "
                "WHERE c.version_id = :v"
            ),
            {"v": version_id},
        ).mappings()
    ]
    obligations = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT o.obligation_id, o.source_clause_id, o.applicability FROM obligation o "
                "JOIN clause c ON c.clause_id = o.source_clause_id WHERE c.version_id = :v"
            ),
            {"v": version_id},
        ).mappings()
    ]
    meta = (doc["metadata"] or {}).get("parsed", {})

    query(
        "MERGE (d:Doc {id: $doc}) SET d.type = $type, d.number = $number, d.title = $title "
        "MERGE (v:Version {id: $ver}) SET v.status = $status MERGE (v)-[:OF]->(d)",
        {
            "doc": doc["document_id"],
            "type": doc["doc_type"],
            "number": doc["doc_number"],
            "title": doc["title"],
            "ver": version_id,
            "status": doc["status"],
        },
    )
    rows = [
        {
            "id": c["clause_id"],
            "num": c["numbering"],
            "level": c["level"],
            "parent": c["parent_id"],
        }
        for c in clauses
    ]
    for chunk in _chunks(rows):
        query(
            "UNWIND $rows AS r MATCH (v:Version {id: $ver}) "
            "MERGE (c:Clause {id: r.id}) SET c.numbering = r.num, c.level = r.level, "
            "c.doc = $doc, c.version = $ver MERGE (c)-[:IN]->(v)",
            {"rows": chunk, "ver": version_id, "doc": doc["document_id"]},
        )
        query(
            "UNWIND $rows AS r WITH r WHERE r.parent IS NOT NULL "
            "MATCH (c:Clause {id: r.id}), (p:Clause {id: r.parent}) MERGE (c)-[:PART_OF]->(p)",
            {"rows": chunk},
        )

    # Cross references: stored edges (regulations, parsed at ingest) + same-document references
    # read from internal clause text.
    refers = [
        {"src": r["source_clause_id"], "dst": r["target_clause_id"]}
        for r in refs
        if r["target_clause_id"]
    ]
    if doc["doc_type"] == "internal":
        by_numbering = {c["numbering"]: c["clause_id"] for c in clauses}
        for c in clauses:
            for target in self_references(c["numbering"], c["text"], set(by_numbering)):
                refers.append({"src": c["clause_id"], "dst": by_numbering[target]})
    for chunk in _chunks(refers):
        query(
            "UNWIND $rows AS r MATCH (a:Clause {id: r.src}), (b:Clause {id: r.dst}) "
            "MERGE (a)-[:REFERS_TO]->(b)",
            {"rows": chunk},
        )

    # Legal references: from clause text, plus the document text outside any clause (the
    # "Căn cứ …" preamble of an internal decision is often not a clause).
    cites = []
    for c in clauses:
        for key, label in legal_refs(c["text"], doc["doc_number"]):
            cites.append({"src": c["clause_id"], "key": key, "label": label})
    for r in refs:
        if r["target_doc_number"] and r["target_doc_number"] != doc["doc_number"]:
            key = number_key(r["target_doc_number"])
            cites.append(
                {"src": r["source_clause_id"], "key": key, "label": r["target_doc_number"]}
            )
    for chunk in _chunks(cites):
        query(
            "UNWIND $rows AS r MATCH (c:Clause {id: r.src}) "
            "MERGE (l:LegalRef {key: r.key}) ON CREATE SET l.label = r.label "
            "MERGE (c)-[:CITES]->(l)",
            {"rows": chunk},
        )
    doc_cites = legal_refs(_uncovered_text(doc["content"] or "", clauses), doc["doc_number"])
    own = []
    if doc["doc_number"]:
        own.append((number_key(doc["doc_number"]), doc["doc_number"]))
    if doc["doc_type"] == "regulation" and doc["legal_form"] and meta.get("subject"):
        key = title_key(doc["legal_form"], meta["subject"])
        if key:
            own.append((key, f"{doc['legal_form']} {meta['subject']}"))
    supersedes = [(number_key(n), n) for n in meta.get("supersedes", [])]
    for rel, items in (("CITES", doc_cites), ("IDENTIFIED_BY", own), ("SUPERSEDES", supersedes)):
        rows_ = [{"key": k, "label": label} for k, label in items]
        if rows_:
            query(
                "UNWIND $rows AS r MATCH (d:Doc {id: $doc}) "
                "MERGE (l:LegalRef {key: r.key}) ON CREATE SET l.label = r.label "
                f"MERGE (d)-[:{rel}]->(l)",
                {"rows": rows_, "doc": doc["document_id"]},
            )

    for chunk in _chunks(obligations):
        query(
            "UNWIND $rows AS r MATCH (c:Clause {id: r.source_clause_id}) "
            "MERGE (o:Obligation {id: r.obligation_id}) SET o.applicability = r.applicability "
            "MERGE (o)-[:FROM]->(c)",
            {"rows": chunk},
        )
    conn.execute(
        text(
            "UPDATE document_version SET metadata = metadata || CAST(:m AS jsonb) "
            "WHERE version_id = :v"
        ),
        {"m": f'{{"graph_synced_at": "{datetime.now(UTC).isoformat()}"}}', "v": version_id},
    )
    return {
        "clauses": len(clauses),
        "refers_to": len(refers),
        "cites": len(cites) + len(doc_cites),
        "identified_by": len(own),
        "supersedes": len(supersedes),
        "obligations": len(obligations),
    }


def ensure_synced(conn, version_ids: list[str]) -> list[str]:
    """Sync versions missing from the graph. Asks the graph itself, so a wiped or new FalkorDB
    is rebuilt from Postgres. Returns the synced ids."""
    present = {
        row[0]
        for row in query(
            "MATCH (v:Version)<-[:IN]-(:Clause) WHERE v.id IN $ids RETURN DISTINCT v.id",
            {"ids": version_ids},
        )
    }
    pending = [v for v in version_ids if v not in present]
    for version_id in pending:
        sync_version(conn, version_id)
    return pending


def _uncovered_text(content: str, clauses: list[dict]) -> str:
    covered = sorted((c["char_start"], c["char_end"]) for c in clauses)
    parts, cursor = [], 0
    for start, end in covered:
        if start > cursor:
            parts.append(content[cursor:start])
        cursor = max(cursor, end)
    parts.append(content[cursor:])
    return "\n".join(parts)


def _chunks(rows: list, size: int = 500):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


# --- Traversals used by Engine 1 ---------------------------------------------------------

LINK_PRIORITY = {"cites_regulation": 0, "cites_superseded": 1, "shared_legal_basis": 2}


_INTERNAL_CLAUSE = (
    "(x:Clause)-[:IN]->(:Version {status: 'effective'})-[:OF]->(d:Doc {type: 'internal'})"
)
_INTERNAL_DOC = "(d:Doc {type: 'internal'})<-[:OF]-(:Version {status: 'effective'})"


def linked_internal_documents(regulation_id: str, version_id: str) -> list[dict]:
    """Effective internal documents tied to the regulation through legal references:

    - cites_regulation: they cite the regulation itself (number or title);
    - cites_superseded: they cite a document this regulation repeals or replaces;
    - shared_legal_basis: they cite a law that a clause of the regulation also cites.
    clause_id is None when the citation sits in the document's preamble ("Căn cứ …").
    """
    found: list[dict] = []
    for relation, rel in (
        ("cites_regulation", "IDENTIFIED_BY"),
        ("cites_superseded", "SUPERSEDES"),
    ):
        own = f"(:Doc {{id: $doc}})-[:{rel}]->(l:LegalRef)"
        params = {"doc": regulation_id}
        for d, c, label in query(
            f"MATCH {own}<-[:CITES]-{_INTERNAL_CLAUSE} RETURN d.id, x.id, l.label", params
        ) + query(f"MATCH {own}<-[:CITES]-{_INTERNAL_DOC} RETURN d.id, null, l.label", params):
            found.append({"document_id": d, "clause_id": c, "relation": relation, "via": label})
    basis = "(:Version {id: $ver})<-[:IN]-(rc:Clause)-[:CITES]->(l:LegalRef)"
    params = {"ver": version_id, "doc": regulation_id}
    exclude = "WHERE NOT (:Doc {id: $doc})-[:IDENTIFIED_BY]->(l) "
    for d, c, label, rc in query(
        f"MATCH {basis}<-[:CITES]-{_INTERNAL_CLAUSE} {exclude}RETURN d.id, x.id, l.label, rc.id",
        params,
    ) + query(
        f"MATCH {basis}<-[:CITES]-{_INTERNAL_DOC} {exclude}RETURN d.id, null, l.label, rc.id",
        params,
    ):
        found.append(
            {
                "document_id": d,
                "clause_id": c,
                "relation": "shared_legal_basis",
                "via": label,
                "regulation_clause_id": rc,
            }
        )
    # One entry per (document, clause, reference), strongest relation first.
    seen, unique = set(), []
    for item in sorted(found, key=lambda i: LINK_PRIORITY[i["relation"]]):
        key = (item["document_id"], item["clause_id"], item["via"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def dependent_clauses(clause_ids: list[str]) -> list[tuple[str, str]]:
    """(evidence clause, dependent clause): clauses that refer to an evidence clause or to one of
    its ancestors (a reference to "Điều 5" depends on every khoản of Điều 5)."""
    if not clause_ids:
        return []
    rows = query(
        "MATCH (x:Clause) WHERE x.id IN $ids "
        "MATCH (x)-[:PART_OF*0..3]->(a:Clause) "
        "MATCH (c:Clause)-[:REFERS_TO]->(a) "
        "WHERE NOT c.id IN $ids AND c.doc = x.doc "
        "RETURN DISTINCT x.id, c.id",
        {"ids": clause_ids},
    )
    return [(x, c) for x, c in rows]
