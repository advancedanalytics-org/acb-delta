"""Multi-view index over clauses (design section 06).

Each substantive clause gets three views that all point back to its clause_id:
- raw: the clause text, verbatim (normalised whitespace)
- context: heading path + parent lead-in + clause text, so short points keep their meaning
- keywords: distinctive syllable bigrams
Sparse rows use embedding_version='none'. When embeddings are configured the context view is
also stored with a vector under the model id; changing model adds rows, never overwrites.

An article (Điều) also gets an "article" view: the mean of its clauses' context vectors (DICE,
Document Inference via Chunk Evidence). An article's own text excludes its clauses, so without
it no vector stands for an obligation that spans several points of one article.
"""

import json
import math

from sqlalchemy import text

from app.ria import embeddings
from app.ria.textutil import content_bigrams, normalize, syllables

INDEXED_LEVELS = ("article", "clause", "point", "chunk")
MAX_CONTEXT_CHARS = 1500
ARTICLE_VIEW = "article"


def _load_clauses(conn, version_id: str) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT c.clause_id, c.parent_id, c.numbering, c.level, c.heading, c.text, d.title "
            "FROM clause c JOIN document_version v ON v.version_id = c.version_id "
            "JOIN document d ON d.document_id = v.document_id "
            "WHERE c.version_id = :v ORDER BY c.ordinal"
        ),
        {"v": version_id},
    ).mappings()
    return [dict(r) for r in rows]


def context_text(clause: dict, by_id: dict[str, dict], with_title: bool = True) -> str:
    path, parent_text = [], None
    node = by_id.get(clause["parent_id"]) if clause["parent_id"] else None
    while node:
        if node["level"] in ("clause", "point") and parent_text is None:
            parent_text = node["text"]
        elif node["level"] == "article":
            path.append(node["heading"] or node["text"][:120])
        elif node["level"] in ("chapter", "section", "appendix"):
            path.append(node["heading"] or node["text"][:120])
        node = by_id.get(node["parent_id"]) if node["parent_id"] else None
    parts = [clause["title"] if with_title else None, *reversed(path)]
    if parent_text:
        parts.append(parent_text)
    parts.append(clause["text"])
    return normalize(" › ".join(p for p in parts if p))[:MAX_CONTEXT_CHARS]


def build_index_views(conn, version_id: str, with_embeddings: bool = True) -> dict:
    clauses = _load_clauses(conn, version_id)
    by_id = {c["clause_id"]: c for c in clauses}
    rows: list[dict] = []
    contexts: list[tuple[str, str]] = []
    for clause in clauses:
        if clause["level"] not in INDEXED_LEVELS or len(syllables(clause["text"])) < 3:
            continue
        cid = clause["clause_id"]
        ctx = context_text(clause, by_id)
        contexts.append((cid, ctx))
        views = {
            "raw": normalize(clause["text"]),
            "context": ctx,
            "keywords": ", ".join(content_bigrams(clause["text"])[:30]),
        }
        for view_type, content in views.items():
            if content:
                rows.append(
                    {
                        "id": f"{cid}|{view_type}|none",
                        "cid": cid,
                        "type": view_type,
                        "content": content,
                        "emb": None,
                        "ver": "none",
                    }
                )

    model = embeddings.embedding_version() if with_embeddings else None
    if model and contexts:
        vectors = embeddings.embed([ctx for _, ctx in contexts])
        for (cid, ctx), vector in zip(contexts, vectors, strict=True):
            rows.append(
                {
                    "id": f"{cid}|context|{model}",
                    "cid": cid,
                    "type": "context",
                    "content": ctx,
                    "emb": embeddings.to_pgvector(vector),
                    "ver": model,
                }
            )

    if rows:
        conn.execute(
            text(
                "INSERT INTO index_view (view_id, clause_id, view_type, content, embedding, "
                "embedding_version) "
                "VALUES (:id, :cid, :type, :content, CAST(:emb AS vector), :ver) "
                "ON CONFLICT (clause_id, view_type, embedding_version) DO UPDATE SET "
                "content = EXCLUDED.content, embedding = EXCLUDED.embedding"
            ),
            rows,
        )
    articles = build_article_views(conn, [version_id], model) if model and contexts else 0
    return {
        "indexed_clauses": len(contexts),
        "views": len(rows) + articles,
        "article_views": articles,
        "embedding_version": model or "none",
    }


def article_of(clause: dict, by_id: dict[str, dict]) -> str | None:
    """The article (Điều) a clause belongs to, itself included."""
    node = clause
    while node:
        if node["level"] == "article":
            return node["clause_id"]
        node = by_id.get(node["parent_id"]) if node["parent_id"] else None
    return None


def mean_vector(vectors: list[list[float]]) -> list[float]:
    """DICE agg_mode="mean" on unit vectors, renormalised for cosine search. DICE's norm-weighted
    modes need raw hidden states; OpenAI-style /embeddings return unit vectors."""
    total = [sum(xs) for xs in zip(*vectors, strict=True)]
    norm = math.sqrt(sum(x * x for x in total)) or 1.0
    return [x / norm for x in total]


def build_article_views(conn, version_ids: list[str], model: str) -> int:
    """Article vectors from the context vectors already stored for its clauses (no embedding
    call). Articles with a single indexed clause are skipped: the vector would be a duplicate."""
    rows = conn.execute(
        text(
            "SELECT c.clause_id, CAST(iv.embedding AS text) AS emb FROM clause c "
            "JOIN index_view iv ON iv.clause_id = c.clause_id "
            "WHERE c.version_id = ANY(:v) AND iv.view_type = 'context' "
            "AND iv.embedding_version = :m"
        ),
        {"v": list(version_ids), "m": model},
    ).all()
    vectors = {cid: json.loads(emb) for cid, emb in rows}
    out = []
    for version_id in version_ids:
        clauses = _load_clauses(conn, version_id)
        by_id = {c["clause_id"]: c for c in clauses}
        members: dict[str, list[str]] = {}
        for c in clauses:
            aid = article_of(c, by_id) if c["clause_id"] in vectors else None
            if aid:
                members.setdefault(aid, []).append(c["clause_id"])
        for aid, cids in members.items():
            if len(cids) < 2:
                continue
            article = by_id[aid]
            out.append(
                {
                    "id": f"{aid}|{ARTICLE_VIEW}|{model}",
                    "cid": aid,
                    "type": ARTICLE_VIEW,
                    "content": normalize(
                        " › ".join(p for p in (article["heading"], article["text"]) if p)
                    )[:MAX_CONTEXT_CHARS]
                    or aid,
                    "emb": embeddings.to_pgvector(mean_vector([vectors[c] for c in cids])),
                    "ver": model,
                }
            )
    if out:
        conn.execute(
            text(
                "INSERT INTO index_view (view_id, clause_id, view_type, content, embedding, "
                "embedding_version) "
                "VALUES (:id, :cid, :type, :content, CAST(:emb AS vector), :ver) "
                "ON CONFLICT (clause_id, view_type, embedding_version) DO UPDATE SET "
                "content = EXCLUDED.content, embedding = EXCLUDED.embedding"
            ),
            out,
        )
    return len(out)


def ensure_article_views(conn, version_ids: set[str], model: str) -> int:
    """Backfill article views for versions indexed before they existed."""
    have = set(
        conn.execute(
            text(
                "SELECT DISTINCT c.version_id FROM index_view iv "
                "JOIN clause c ON c.clause_id = iv.clause_id "
                "WHERE iv.view_type = :t AND iv.embedding_version = :m "
                "AND c.version_id = ANY(:v)"
            ),
            {"t": ARTICLE_VIEW, "m": model, "v": list(version_ids)},
        ).scalars()
    )
    missing = sorted(version_ids - have)
    return build_article_views(conn, missing, model) if missing else 0
