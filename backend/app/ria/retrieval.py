"""Engine 1 — multi-query hybrid retrieval over the internal corpus (design sections 07–09).

For each obligation: several controlled query views → sparse (Postgres full-text over syllable
bigrams) and, when configured, dense (pgvector) search → Reciprocal Rank Fusion → lexical
relevance gate → document-level aggregation → parent-context expansion.

Dense search also matches whole articles (Điều) on the mean of their clause vectors (DICE, see
indexing.build_article_views); the clauses of the best articles join the fusion as their own lists.
"""

import math
import re
from dataclasses import dataclass, field

from sqlalchemy import text

from app.ria import embeddings, rerank
from app.ria.indexing import ARTICLE_VIEW, INDEXED_LEVELS, context_text
from app.ria.textutil import content_bigrams, normalize, tsquery_from_bigrams

_EXCEPTION_HINT = re.compile(r"\b(trừ|ngoại trừ|không áp dụng|miễn)\b", re.IGNORECASE)


@dataclass
class RetrievalParams:
    rrf_k: int = 60
    candidates_per_query: int = 20
    # One LLM call judges all of them, so keeping more clauses costs little and protects recall.
    evidence_per_obligation: int = 5
    max_documents: int = 20
    alpha: float = 0.7  # S(D,Q) = α·max(s) + (1−α)·mean(TopK(s))
    top_k_mean: int = 3
    min_shared_bigrams: int = 2
    min_idf_score: float = 6.0
    min_term_idf: float = 2.0  # rarer than ~1 in 7 clauses; commoner terms are topic, not evidence
    relative_cutoff: float = 0.6  # keep candidates scoring ≥ this share of the obligation's best
    dense_min_score: float = 0.55
    # Below this, dense similarity alone is register, not topic (Vietnamese legal text sits at
    # 0.55–0.65 with bge-m3): it also needs one shared gated term to count as evidence.
    dense_strong_score: float = 0.7
    # Reranker (when configured): how many fused entries it scores, and its relevance floor.
    rerank_candidates: int = 20
    rerank_min_score: float | None = None  # None = the backend's calibrated default
    # Knowledge graph: documents linked to the regulation by legal references get this share of
    # the usual threshold; evidence clauses pull in up to graph_neighbors dependent clauses.
    graph_relax: float = 0.6
    graph_neighbors: int = 3
    # DICE: articles matched per dense query view on their aggregated vector; their clauses
    # join the fusion. 0 turns article matching off.
    article_candidates: int = 3


@dataclass
class InternalCorpus:
    """Effective internal clauses in scope, with bigram statistics for the relevance gate."""

    clauses: dict[str, dict]
    bigrams: dict[str, set[str]]
    idf: dict[str, float]
    children: dict[str, list[str]] = field(default_factory=dict)

    @property
    def document_ids(self) -> set[str]:
        return {c["document_id"] for c in self.clauses.values()}


def load_internal_corpus(conn, document_ids: list[str] | None) -> InternalCorpus:
    rows = conn.execute(
        text(
            "SELECT c.clause_id, c.parent_id, c.numbering, c.level, c.heading, c.text, "
            "c.version_id, d.document_id, d.title "
            "FROM clause c JOIN document_version v ON v.version_id = c.version_id "
            "JOIN document d ON d.document_id = v.document_id "
            "WHERE d.doc_type = 'internal' AND v.status = 'effective' "
            "AND (CAST(:docs AS text[]) IS NULL OR d.document_id = ANY(CAST(:docs AS text[]))) "
            "ORDER BY c.version_id, c.ordinal"
        ),
        {"docs": document_ids},
    ).mappings()
    clauses = {r["clause_id"]: dict(r) for r in rows}
    children: dict[str, list[str]] = {}
    for c in clauses.values():
        if c["parent_id"]:
            children.setdefault(c["parent_id"], []).append(c["clause_id"])
    # Gate on the clause and its heading path, not the document title: the title is shared by
    # every clause of the document and says nothing about which clause matches.
    bigrams = {
        cid: set(content_bigrams(context_text(c, clauses, with_title=False)))
        for cid, c in clauses.items()
    }
    return InternalCorpus(clauses, bigrams, corpus_idf(conn), children)


def corpus_idf(conn) -> dict[str, float]:
    """Bigram IDF over every indexed clause, regulations included. A term that is everywhere in
    a regulation ("dữ liệu cá nhân" in a data-protection law) is its topic, not evidence that
    one internal clause matches one obligation."""
    rows = conn.execute(
        text(
            "SELECT content FROM index_view WHERE view_type = 'raw' AND embedding_version = 'none'"
        )
    ).scalars()
    df: dict[str, int] = {}
    n = 0
    for content in rows:
        n += 1
        for g in set(content_bigrams(content)):
            df[g] = df.get(g, 0) + 1
    return {g: math.log((n + 1) / (d + 0.5)) for g, d in df.items()}


def build_queries(obligation: dict) -> dict[str, str]:
    """Controlled query views (design section 07): legal wording, normalised proposition,
    topic (article heading) and the values / conditions phrase."""
    views = {
        "legal_text": obligation["text"],
        "proposition": " ".join(
            p for p in (obligation["subject"], obligation["action"], obligation["object"]) if p
        ),
        "topic": " ".join(p for p in (obligation.get("article_heading"), obligation["text"]) if p),
    }
    values = " ".join(
        p
        for p in (
            obligation.get("deadline"),
            obligation.get("condition"),
            obligation.get("exception"),
        )
        if p
    )
    if values:
        views["values_conditions"] = f"{obligation['object']} {values}"
    return {k: normalize(v) for k, v in views.items() if v and v.strip()}


def _sparse(conn, query: str, corpus: InternalCorpus, limit: int) -> list[tuple[str, float]]:
    bigrams = [g for g in content_bigrams(query) if g in corpus.idf]
    if not bigrams:
        return []
    # Rarest bigrams first so the tsquery keeps the discriminative ones.
    bigrams.sort(key=lambda g: -corpus.idf[g])
    rows = conn.execute(
        text(
            "SELECT iv.clause_id, max(ts_rank_cd(iv.tsv, q, 1)) AS score "
            "FROM index_view iv, to_tsquery('simple', :q) q "
            "WHERE iv.embedding_version = 'none' AND iv.view_type IN ('raw', 'context') "
            "AND iv.tsv @@ q AND iv.clause_id = ANY(:ids) "
            "GROUP BY iv.clause_id ORDER BY score DESC LIMIT :n"
        ),
        {"q": tsquery_from_bigrams(bigrams), "ids": list(corpus.clauses), "n": limit},
    )
    return [(cid, float(score)) for cid, score in rows]


def _dense(
    conn,
    vector: list[float],
    model: str,
    corpus: InternalCorpus,
    limit: int,
    view: str = "context",
    ids: list[str] | None = None,
):
    rows = conn.execute(
        text(
            "SELECT iv.clause_id, 1 - (iv.embedding <=> CAST(:qv AS vector)) AS score "
            "FROM index_view iv WHERE iv.embedding_version = :model AND iv.view_type = :view "
            "AND iv.clause_id = ANY(:ids) "
            "ORDER BY iv.embedding <=> CAST(:qv AS vector) LIMIT :n"
        ),
        {
            "qv": embeddings.to_pgvector(vector),
            "model": model,
            "view": view,
            "ids": list(ids if ids is not None else corpus.clauses),
            "n": limit,
        },
    )
    return [(cid, float(score)) for cid, score in rows]


def article_members(article_id: str, corpus: InternalCorpus) -> list[str]:
    """The article and its descendant clauses, in document order."""
    out, stack = [], [article_id]
    while stack:
        cid = stack.pop()
        if corpus.clauses[cid]["level"] in INDEXED_LEVELS:
            out.append(cid)
        stack.extend(reversed(corpus.children.get(cid, [])))
    return out


def _dense_articles(
    conn, vector: list[float], model: str, corpus: InternalCorpus, params: RetrievalParams
) -> tuple[list[tuple[str, float]], dict[str, float]]:
    """Clauses of the best-matching articles: article rank first, then each clause's own
    similarity. Returns the ranked clauses and the article score each one came from."""
    articles = _dense(conn, vector, model, corpus, params.article_candidates, view=ARTICLE_VIEW)
    members = {aid: article_members(aid, corpus) for aid, _ in articles}
    ids = [cid for cids in members.values() for cid in cids]
    if not ids:
        return [], {}
    own = dict(_dense(conn, vector, model, corpus, len(ids), ids=ids))
    # origin must cover exactly the returned clauses: fuse_for_obligation looks each one up
    # in the fused results, so a clause dropped by the cap must not keep an article score.
    ranked, origin = [], {}
    for aid, a_score in articles:
        for cid in sorted(members[aid], key=lambda c: -own.get(c, 0.0)):
            if len(ranked) >= params.candidates_per_query:
                return ranked, origin
            if cid not in origin and cid in own:
                ranked.append((cid, own[cid]))
                origin[cid] = a_score
    return ranked, origin


def rrf(ranked_lists: dict[str, list[tuple[str, float]]], k: int) -> dict[str, dict]:
    """RRF(d) = Σ 1/(k + rank_i(d)). Keeps each list's rank for the evidence trace."""
    fused: dict[str, dict] = {}
    for name, ranked in ranked_lists.items():
        for rank, (cid, score) in enumerate(ranked, start=1):
            entry = fused.setdefault(cid, {"rrf": 0.0, "ranks": {}, "dense": None})
            entry["rrf"] += 1.0 / (k + rank)
            entry["ranks"][name] = rank
            # Article lists carry each clause's own similarity, so it counts as dense evidence.
            if name.startswith(("dense:", "article:")):
                entry["dense"] = max(entry["dense"] or 0.0, score)
    return fused


def lexical_overlap(
    obligation_text: str, cid: str, corpus: InternalCorpus, min_term_idf: float = 0.0
) -> dict:
    query = [g for g in content_bigrams(obligation_text) if corpus.idf.get(g, 0.0) >= min_term_idf]
    shared = [g for g in query if g in corpus.bigrams[cid]]
    total = sum(corpus.idf[g] for g in query) or 1.0
    score = sum(corpus.idf[g] for g in shared)
    shared.sort(key=lambda g: -corpus.idf[g])
    return {"shared": shared, "idf_score": score, "ratio": score / total}


def best_sentence_span(clause_text: str, terms: list[str]) -> tuple[int, int]:
    """Sentence of the clause with most shared bigrams; offsets inside the clause text."""
    best, best_hits = (0, len(clause_text)), -1
    for m in re.finditer(r"[^.;\n]+[.;]?", clause_text):
        sentence = m.group(0)
        grams = set(content_bigrams(sentence))
        hits = sum(1 for t in terms if t in grams)
        if hits > best_hits and sentence.strip():
            lead = len(sentence) - len(sentence.lstrip())
            best, best_hits = (m.start() + lead, m.start() + len(sentence.rstrip())), hits
    return best


def parent_context(cid: str, corpus: InternalCorpus) -> list[dict]:
    """Parent chain plus sibling clauses that carry exceptions (design section 09)."""
    out = []
    clause = corpus.clauses[cid]
    node = corpus.clauses.get(clause["parent_id"]) if clause["parent_id"] else None
    while node:
        out.append({"clause_id": node["clause_id"], "role": "parent", "text": node["text"][:500]})
        node = corpus.clauses.get(node["parent_id"]) if node["parent_id"] else None
    for sib in corpus.children.get(clause["parent_id"], []) if clause["parent_id"] else []:
        sib_text = corpus.clauses[sib]["text"]
        if sib != cid and _EXCEPTION_HINT.search(sib_text):
            out.append({"clause_id": sib, "role": "exception", "text": sib_text[:500]})
    return out


def fuse_for_obligation(
    conn,
    obligation: dict,
    corpus: InternalCorpus,
    params: RetrievalParams,
    query_vectors: dict[str, list[float]] | None,
    model: str | None,
) -> tuple[list[dict], dict]:
    """Sparse + dense lists for every query view, fused by RRF, best first. No gating yet."""
    queries = build_queries(obligation)
    ranked: dict[str, list[tuple[str, float]]] = {}
    for name, q in queries.items():
        hits = _sparse(conn, q, corpus, params.candidates_per_query)
        if hits:
            ranked[f"sparse:{name}"] = hits
    article_scores: dict[str, float] = {}
    if model and query_vectors:
        for name, vector in query_vectors.items():
            ranked[f"dense:{name}"] = _dense(
                conn, vector, model, corpus, params.candidates_per_query
            )
            if params.article_candidates > 0:
                hits, origin = _dense_articles(conn, vector, model, corpus, params)
                if hits:
                    ranked[f"article:{name}"] = hits
                for cid, score in origin.items():
                    article_scores[cid] = max(article_scores.get(cid, 0.0), score)

    fused = rrf(ranked, params.rrf_k)
    for cid, score in article_scores.items():
        fused[cid]["article"] = score
    max_rrf = max(1, len(ranked)) / (params.rrf_k + 1)
    gate_text = gate_query(obligation)
    entries = []
    for cid, entry in fused.items():
        lex = lexical_overlap(gate_text, cid, corpus, params.min_term_idf)
        entries.append({"clause_id": cid, **entry, "rrf_norm": entry["rrf"] / max_rrf, "lex": lex})
    entries.sort(key=lambda e: -e["rrf"])
    trace = {
        "queries": queries,
        "lists": {k: len(v) for k, v in ranked.items()},
        "fused": len(fused),
    }
    return entries, trace


def gate_query(obligation: dict) -> str:
    return " ".join(p for p in (obligation["text"], obligation.get("article_heading")) if p)


def rerank_entries(
    obligation: dict, entries: list[dict], corpus: InternalCorpus, params: RetrievalParams
) -> dict[str, float]:
    """Cross-encoder scores for the top fused entries (design section 05.6)."""
    top = entries[: params.rerank_candidates]
    # Jev judges "same activity"; the document title ("…rà soát hồ sơ khách hàng") on every
    # clause makes all of them look related, so it gets the clause and its heading path only.
    with_title = rerank.backend() != "jev"
    docs = [
        context_text(corpus.clauses[e["clause_id"]], corpus.clauses, with_title=with_title)
        for e in top
    ]
    scores = rerank.rerank(gate_query(obligation), docs)
    return {e["clause_id"]: s for e, s in zip(top, scores, strict=True)}


def select_candidates(
    entries: list[dict],
    corpus: InternalCorpus,
    params: RetrievalParams,
    rerank_scores: dict[str, float] | None = None,
    relaxed_docs: set[str] | None = None,
) -> list[dict]:
    """Keep relevant entries. With rerank scores the reranker decides; without them the
    lexical/dense gate does. Then drop the tail below relative_cutoff × best.

    relaxed_docs: documents the knowledge graph links to the regulation. Their entries pass at
    graph_relax × the usual threshold, and the best one per document survives the tail cut.
    """
    candidates = []
    for entry in entries:
        cid, lex, dense = entry["clause_id"], entry["lex"], entry["dense"]
        relax = params.graph_relax if relaxed_docs and _doc_of(cid, corpus) in relaxed_docs else 1
        rr = rerank_scores.get(cid) if rerank_scores is not None else None
        if rerank_scores is not None:
            floor = (
                params.rerank_min_score
                if params.rerank_min_score is not None
                else rerank.default_min_score()
            )
            if rr is None or rr < floor * relax:
                continue
            score = rr
            relaxed_only = rr < floor
        else:
            dense_ok = dense is not None and (
                dense >= params.dense_strong_score * relax
                or (dense >= params.dense_min_score * relax and len(lex["shared"]) >= 1)
            )
            lexical_ok = (
                len(lex["shared"]) >= max(1, round(params.min_shared_bigrams * relax))
                and lex["idf_score"] >= params.min_idf_score * relax
            )
            if not (lexical_ok or dense_ok):
                continue
            relevance = dense if dense is not None else lex["ratio"]
            score = 0.5 * entry["rrf_norm"] + 0.5 * min(1.0, relevance)
            relaxed_only = relax < 1 and not (
                len(lex["shared"]) >= params.min_shared_bigrams
                and lex["idf_score"] >= params.min_idf_score
            )
        candidates.append(
            {
                "clause_id": cid,
                "document_id": corpus.clauses[cid]["document_id"],
                "score": round(score, 4),
                "rrf": round(entry["rrf"], 5),
                "ranks": entry["ranks"],
                "dense": dense,
                "rerank": None if rr is None else round(rr, 4),
                "article": None if entry.get("article") is None else round(entry["article"], 4),
                "shared_terms": lex["shared"][:10],
                "idf_score": round(lex["idf_score"], 3),
                "graph_relaxed": bool(relax < 1 and relaxed_only),
            }
        )
    candidates.sort(key=lambda c: -c["score"])
    if candidates:
        floor = params.relative_cutoff * candidates[0]["score"]
        kept, linked_seen = [], set()
        for c in candidates:
            linked = relaxed_docs and c["document_id"] in relaxed_docs
            if c["score"] >= floor or (linked and c["document_id"] not in linked_seen):
                kept.append(c)
            if linked:
                linked_seen.add(c["document_id"])
        candidates = kept
    return candidates


def _doc_of(clause_id: str, corpus: InternalCorpus) -> str:
    return corpus.clauses[clause_id]["document_id"]


def retrieve_for_obligation(
    conn,
    obligation: dict,
    corpus: InternalCorpus,
    params: RetrievalParams,
    query_vectors: dict[str, list[float]] | None,
    model: str | None,
) -> tuple[list[dict], dict]:
    """Fuse and gate without a reranker."""
    entries, trace = fuse_for_obligation(conn, obligation, corpus, params, query_vectors, model)
    return select_candidates(entries, corpus, params), trace


def aggregate_documents(
    per_obligation: dict[str, list[dict]], params: RetrievalParams
) -> list[dict]:
    """Document scores from clause evidence: S(D,Q) per obligation, then the same α-mix over
    obligations, plus coverage (share of obligations with evidence in D) and sections hit."""
    per_doc_q: dict[str, dict[str, float]] = {}
    sections: dict[str, set[str]] = {}
    for obligation_id, cands in per_obligation.items():
        by_doc: dict[str, list[float]] = {}
        for c in cands:
            by_doc.setdefault(c["document_id"], []).append(c["score"])
            sections.setdefault(c["document_id"], set()).add(
                c["clause_id"].split("#")[1].split(".")[0]
            )
        for doc, scores in by_doc.items():
            scores.sort(reverse=True)
            top = scores[: params.top_k_mean]
            s = params.alpha * scores[0] + (1 - params.alpha) * sum(top) / len(top)
            per_doc_q.setdefault(doc, {})[obligation_id] = s
    n_obligations = max(1, len(per_obligation))
    docs = []
    for doc, by_q in per_doc_q.items():
        values = sorted(by_q.values(), reverse=True)
        top = values[: params.top_k_mean]
        docs.append(
            {
                "document_id": doc,
                "score": round(
                    params.alpha * values[0] + (1 - params.alpha) * sum(top) / len(top), 4
                ),
                "maxp": round(values[0], 4),
                "topk_mean": round(sum(top) / len(top), 4),
                "coverage": round(len(by_q) / n_obligations, 4),
                "obligations_hit": len(by_q),
                "sections_hit": len(sections.get(doc, ())),
            }
        )
    docs.sort(key=lambda d: (-d["score"], -d["coverage"]))
    return docs[: params.max_documents]
