"""POST /api/regulations/{id}/analyze: impact analysis job (design sections 07–11, 14–16).

PARSED → (Engine 1: retrieval, evidence) → RETRIEVAL_COMPLETED → (Engine 2: comparison,
findings) → AI_PROPOSED. Each run keeps its own evidence and findings (job_id = lineage);
nothing is overwritten and no internal document is modified.
"""

import json
import logging
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, fields

from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.ria import embeddings, graph, jobs, llm, rerank
from app.ria.applicability import classify_obligations
from app.ria.compare import PRIORITY, judge_group
from app.ria.retrieval import (
    RetrievalParams,
    aggregate_documents,
    best_sentence_span,
    build_queries,
    fuse_for_obligation,
    gate_query,
    lexical_overlap,
    load_internal_corpus,
    parent_context,
    rerank_entries,
    select_candidates,
)
from app.ria.schema import ensure_schema

ANALYZABLE = ("PARSED", "RETRIEVAL_COMPLETED", "AI_PROPOSED")
log = logging.getLogger(__name__)


# Which pair represents a finding: a conflict anywhere wins (fail closed); otherwise a clause
# that already satisfies the obligation; otherwise the most specific difference.
_CATEGORY_RANK = {
    "VALUE_CHANGE": 0,
    "CONTRADICTION": 1,
    "EQUIVALENT": 2,
    "SCOPE_CHANGE": 3,
    "ADDITION": 4,
    "INDIRECT_IMPACT": 5,
}


class AnalyzeError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _resolve_version(conn, regulation_id: str) -> dict:
    """{id} is a document id (latest version) or an explicit version id (REG-…@v2)."""
    if "@" in regulation_id:
        where, param = "v.version_id = :id", regulation_id
    else:
        where, param = "v.document_id = :id", regulation_id
    row = (
        conn.execute(
            text(
                "SELECT v.version_id, v.document_id, v.processing_status, d.doc_type "
                "FROM document_version v JOIN document d USING (document_id) "
                f"WHERE {where} ORDER BY v.created_at DESC LIMIT 1"
            ),
            {"id": param},
        )
        .mappings()
        .first()
    )
    if not row or row["doc_type"] != "regulation":
        raise AnalyzeError(404, f"regulation {regulation_id} not found")
    return dict(row)


def start_analysis(regulation_id: str, options: dict) -> tuple[dict, bool]:
    """Returns (body, created). An analysis already queued/running is returned, not duplicated."""
    ensure_schema()
    with get_engine().begin() as conn:
        version = _resolve_version(conn, regulation_id)
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:v))"), {"v": version["version_id"]}
        )
        active = (
            conn.execute(
                text(
                    "SELECT job_id, status FROM job WHERE version_id = :v AND job_type = 'analyze' "
                    "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1"
                ),
                {"v": version["version_id"]},
            )
            .mappings()
            .first()
        )
        if active:
            return {
                "job_id": active["job_id"],
                "regulation_id": version["document_id"],
                "version_id": version["version_id"],
                "status": active["status"],
                "duplicate": True,
            }, False
        if version["processing_status"] not in ANALYZABLE:
            raise AnalyzeError(
                409,
                f"{version['version_id']} is {version['processing_status']}; "
                "wait for the parse job to finish (status PARSED)",
            )
        n_obligations = conn.execute(
            text(
                "SELECT count(*) FROM obligation o "
                "JOIN clause c ON c.clause_id = o.source_clause_id WHERE c.version_id = :v"
            ),
            {"v": version["version_id"]},
        ).scalar()
        if not n_obligations:
            job_id = jobs.create_job(
                conn, "analyze", version["document_id"], version["version_id"], options
            )
            conn.execute(
                text(
                    "UPDATE job SET status = 'succeeded', stage = 'done', progress = 100, "
                    "finished_at = clock_timestamp(), result = CAST(:res AS jsonb) "
                    "WHERE job_id = :j"
                ),
                {
                    "j": job_id,
                    "res": json.dumps(
                        {
                            "regulation_id": version["document_id"],
                            "version_id": version["version_id"],
                            "status": "AI_PROPOSED",
                            "findings": 0,
                            "obligations": {"total": 0, "analyzed": 0},
                            "warnings": [
                                "Tài liệu không chứa các điều khoản nghĩa vụ pháp lý "
                                "bắt buộc (0 obligations extracted)."
                            ],
                        }
                    ),
                },
            )
            conn.execute(
                text(
                    "UPDATE document_version SET processing_status = 'AI_PROPOSED' "
                    "WHERE version_id = :v"
                ),
                {"v": version["version_id"]},
            )
            return {
                "job_id": job_id,
                "regulation_id": version["document_id"],
                "version_id": version["version_id"],
                "status": "succeeded",
                "duplicate": False,
            }, True
        docs = options.get("internal_document_ids")
        n_internal = conn.execute(
            text(
                "SELECT count(*) FROM document_version v JOIN document d USING (document_id) "
                "WHERE d.doc_type = 'internal' AND v.status = 'effective' "
                "AND (CAST(:docs AS text[]) IS NULL OR d.document_id = ANY(CAST(:docs AS text[])))"
            ),
            {"docs": docs},
        ).scalar()
        if not n_internal:
            if not docs:
                from pathlib import Path

                from app.ria.seed import seed_file

                for candidate in (
                    Path(__file__).parent / "data" / "DOC-102.parsed.json",
                    Path("../db/DOC-102.parsed.json"),
                    Path("db/DOC-102.parsed.json"),
                ):
                    if candidate.is_file():
                        try:
                            seed_file(candidate)
                            n_internal = conn.execute(
                                text(
                                    "SELECT count(*) FROM document_version v "
                                    "JOIN document d USING (document_id) "
                                    "WHERE d.doc_type = 'internal' AND v.status = 'effective'"
                                )
                            ).scalar()
                            if n_internal:
                                break
                        except Exception:
                            pass

        if not n_internal:
            if docs:
                known = sorted(
                    conn.execute(
                        text(
                            "SELECT d.document_id FROM document d JOIN document_version v "
                            "USING (document_id) WHERE d.doc_type = 'internal' "
                            "AND v.status = 'effective'"
                        )
                    ).scalars()
                )
                raise AnalyzeError(
                    409,
                    f"internal_document_ids {sorted(set(docs) - set(known))} are not effective "
                    f"internal documents; available: {known} (omit the field to use all)",
                )
            raise AnalyzeError(
                409, "no effective internal documents in scope; seed the corpus first"
            )
        job_id = jobs.create_job(
            conn, "analyze", version["document_id"], version["version_id"], options
        )
    jobs.submit(job_id)
    return {
        "job_id": job_id,
        "regulation_id": version["document_id"],
        "version_id": version["version_id"],
        "status": "queued",
        "duplicate": False,
    }, True


def _load_obligations(conn, version_id: str) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT o.*, c.text AS clause_text, c.numbering, c.clause_id, "
            "COALESCE(a.heading, a2.heading, a3.heading) AS article_heading "
            "FROM obligation o JOIN clause c ON c.clause_id = o.source_clause_id "
            "LEFT JOIN clause p ON p.clause_id = c.parent_id "
            "LEFT JOIN clause pp ON pp.clause_id = p.parent_id "
            "LEFT JOIN clause a ON a.clause_id = c.clause_id AND a.level = 'article' "
            "LEFT JOIN clause a2 ON a2.clause_id = p.clause_id AND a2.level = 'article' "
            "LEFT JOIN clause a3 ON a3.clause_id = pp.clause_id AND a3.level = 'article' "
            "WHERE c.version_id = :v ORDER BY c.ordinal, o.span_start"
        ),
        {"v": version_id},
    ).mappings()
    return [dict(r) for r in rows]


def _set_status(conn, version_id: str, status: str) -> None:
    conn.execute(
        text("UPDATE document_version SET processing_status = :s WHERE version_id = :v"),
        {"s": status, "v": version_id},
    )


def run_analysis(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    version_id = job["version_id"]
    options = job["params"] or {}
    known = {f.name for f in fields(RetrievalParams)}
    params = RetrievalParams(**{k: v for k, v in options.items() if k in known})
    modalities = set(options.get("modalities") or ("must", "must_not", "may"))
    model = embeddings.embedding_version()
    use_llm = bool(llm.llm_model()) and options.get("use_llm", True) is not False
    reranker = rerank.rerank_model() if options.get("use_rerank", True) is not False else None
    max_llm_calls = int(options.get("max_llm_calls", 150))
    refresh = bool(options.get("refresh_llm_cache", False))
    settings = get_settings()
    warnings: list[str] = []

    with get_engine().connect() as conn:
        legal = (
            conn.execute(
                text("SELECT status, valid_from FROM document_version WHERE version_id = :v"),
                {"v": version_id},
            )
            .mappings()
            .first()
        )
        obligations = _load_obligations(conn, version_id)
        corpus = load_internal_corpus(conn, options.get("internal_document_ids"))
        if not corpus.clauses:
            raise RuntimeError("no effective internal clauses in scope")
        if model:
            n_dense = conn.execute(
                text(
                    "SELECT count(*) FROM index_view WHERE embedding_version = :m "
                    "AND clause_id = ANY(:ids)"
                ),
                {"m": model, "ids": list(corpus.clauses)},
            ).scalar()
            if not n_dense:
                warnings.append(f"no internal vectors for {model}; dense retrieval skipped")
                model = None
        else:
            warnings.append("EMBEDDING_BASE_URL not set; sparse retrieval only")
        if not reranker:
            warnings.append("reranker not configured; lexical/dense relevance gate used")
        if not use_llm:
            warnings.append("LLM judge disabled; comparison is rule-based")

    # Knowledge graph (FalkorDB): make sure every version in scope is in the graph, then find
    # internal documents tied to this regulation by legal references.
    graph_info: dict = {"enabled": graph.enabled()}
    linked: list[dict] = []
    if graph.enabled():
        jobs.update_progress(job_id, "graph", 2)
        internal_versions = sorted({c["version_id"] for c in corpus.clauses.values()})
        try:
            with get_engine().begin() as conn:
                graph_info["synced_versions"] = graph.ensure_synced(
                    conn, [version_id, *internal_versions]
                )
            linked = [
                link
                for link in graph.linked_internal_documents(job["document_id"], version_id)
                if link["document_id"] in corpus.document_ids
            ]
        except Exception as exc:  # derived index: analysis continues without it
            log.warning("graph unavailable: %s", exc)
            warnings.append(f"knowledge graph unavailable ({exc.__class__.__name__}); skipped")
            graph_info["error"] = str(exc)[:300]
    linked_docs = {link["document_id"] for link in linked}

    # Applicability: drop obligations that cannot bind the bank before spending retrieval/LLM.
    jobs.update_progress(job_id, "applicability", 3)
    by_modality = [o for o in obligations if o["modality"] in modalities]
    skipped = Counter({"modality_filtered": len(obligations) - len(by_modality)})
    if options.get("filter_not_applicable", True) is not False:
        with get_engine().begin() as conn:
            applies = classify_obligations(conn, by_modality, use_llm, refresh=refresh)
        in_scope = [o for o in by_modality if applies.get(o["obligation_id"]) != "no"]
        skipped["not_applicable"] = len(by_modality) - len(in_scope)
        applicability = dict(Counter(applies.values()))
    else:
        in_scope, applicability = by_modality, {}
    skipped = +skipped  # drop zero counts

    # Engine 1: fuse sparse + dense per obligation (SQL), then rerank in parallel.
    jobs.update_progress(job_id, "retrieval", 10)
    query_vectors: dict[str, dict[str, list[float]]] = {}
    if model and in_scope:
        flat = [
            (o["obligation_id"], name, q)
            for o in in_scope
            for name, q in build_queries(o).items()
            if name in ("legal_text", "proposition")
        ]
        vectors = embeddings.embed([q for _, _, q in flat])
        for (oid, name, _), vector in zip(flat, vectors, strict=True):
            query_vectors.setdefault(oid, {})[name] = vector

    fused: dict[str, list[dict]] = {}
    traces: dict[str, dict] = {}
    with get_engine().connect() as conn:
        for i, o in enumerate(in_scope):
            entries, trace = fuse_for_obligation(
                conn, o, corpus, params, query_vectors.get(o["obligation_id"]), model
            )
            fused[o["obligation_id"]], traces[o["obligation_id"]] = entries, trace
            if i % 25 == 0:
                jobs.update_progress(job_id, "retrieval", 10 + int(20 * i / max(1, len(in_scope))))

    rerank_scores: dict[str, dict[str, float] | None] = {}
    rerank_failures = 0
    if reranker:
        jobs.update_progress(job_id, "rerank", 30)

        def score(o: dict) -> dict[str, float] | None:
            try:
                return rerank_entries(o, fused[o["obligation_id"]], corpus, params)
            except Exception as exc:  # fall back to the lexical/dense gate for this obligation
                log.warning("rerank failed for %s: %s", o["obligation_id"], exc)
                return None

        with ThreadPoolExecutor(
            max_workers=max(1, settings.rerank_concurrency), thread_name_prefix="ria-rerank"
        ) as pool:
            for o, scores in zip(in_scope, pool.map(score, in_scope), strict=True):
                rerank_scores[o["obligation_id"]] = scores
                rerank_failures += scores is None
        if rerank_failures:
            warnings.append(f"reranker failed for {rerank_failures} obligations; gate used")

    per_obligation = {
        oid: select_candidates(entries, corpus, params, rerank_scores.get(oid), linked_docs)
        for oid, entries in fused.items()
    }

    shortlist = aggregate_documents(per_obligation, params)
    shortlisted = {d["document_id"] for d in shortlist}
    for doc_id in sorted(linked_docs - shortlisted):  # never drop a document the graph links
        shortlist.append({"document_id": doc_id, "score": 0.0, "coverage": 0.0})
        shortlisted.add(doc_id)
    for d in shortlist:
        d["graph_relations"] = sorted(
            {link["relation"] for link in linked if link["document_id"] == d["document_id"]}
        )
    titles = {c["document_id"]: c["title"] for c in corpus.clauses.values()}
    for d in shortlist:
        d["title"] = titles.get(d["document_id"])

    # Evidence: top clauses per obligation inside shortlisted documents, with parent context.
    evidence_rows: list[dict] = []
    for o in in_scope:
        kept = [c for c in per_obligation[o["obligation_id"]] if c["document_id"] in shortlisted]
        for c in kept[: params.evidence_per_obligation]:
            clause = corpus.clauses[c["clause_id"]]
            start, end = best_sentence_span(clause["text"], c["shared_terms"])
            method = "+".join(sorted({k.split(":")[0] for k in c["ranks"]})) + "+rrf"
            if c["rerank"] is not None:
                method += "+rerank"
            evidence_rows.append(
                {
                    "evidence_id": f"EV-{uuid.uuid4().hex[:12]}",
                    "obligation": o,
                    "clause": clause,
                    "candidate": c,
                    "span": (start, end),
                    "method": method,
                    "context": parent_context(c["clause_id"], corpus),
                }
            )
    graph_info["dependent_clauses_added"] = (
        _add_dependent_clauses(evidence_rows, corpus, params)
        if graph.enabled() and not graph_info.get("error")
        else 0
    )
    uncovered = [o for o in in_scope if not per_obligation[o["obligation_id"]]]

    with get_engine().begin() as conn:
        if evidence_rows:
            conn.execute(
                text(
                    "INSERT INTO evidence (evidence_id, job_id, obligation_id, internal_clause_id, "
                    "span_start, span_end, span_text, retrieval_method, score, details) VALUES "
                    "(:id, :job, :obl, :cid, :s, :e, :st, :m, :score, CAST(:details AS jsonb))"
                ),
                [
                    {
                        "id": ev["evidence_id"],
                        "job": job_id,
                        "obl": ev["obligation"]["obligation_id"],
                        "cid": ev["clause"]["clause_id"],
                        "s": ev["span"][0],
                        "e": ev["span"][1],
                        "st": ev["clause"]["text"][ev["span"][0] : ev["span"][1]],
                        "m": ev["method"],
                        "score": ev["candidate"]["score"],
                        "details": json.dumps(
                            {
                                "ranks": ev["candidate"]["ranks"],
                                "rrf": ev["candidate"]["rrf"],
                                "dense": ev["candidate"]["dense"],
                                "rerank": ev["candidate"]["rerank"],
                                "shared_terms": ev["candidate"]["shared_terms"],
                                "idf_score": ev["candidate"]["idf_score"],
                                "queries": traces[ev["obligation"]["obligation_id"]]["queries"],
                                "parent_context": ev["context"],
                            },
                            ensure_ascii=False,
                        ),
                    }
                    for ev in evidence_rows
                ],
            )
        _set_status(conn, version_id, "RETRIEVAL_COMPLETED")

    # Engine 2: one LLM call per obligation with all its candidate clauses.
    jobs.update_progress(job_id, "comparison", 55)
    temporal = {"check": "temporal_validity", "status": "pass"}
    if legal["status"] == "pending":
        temporal = {
            "check": "temporal_validity",
            "status": "warn",
            "detail": f"văn bản chưa có hiệu lực (từ {legal['valid_from']})",
        }
    elif legal["status"] in ("superseded", "unknown"):
        temporal = {"check": "temporal_validity", "status": "warn", "detail": legal["status"]}

    groups: dict[str, list[int]] = {}
    for i, ev in enumerate(evidence_rows):
        groups.setdefault(ev["obligation"]["obligation_id"], []).append(i)
    # The LLM budget goes to the obligations with the strongest retrieval evidence.
    order = sorted(
        groups, key=lambda oid: -max(evidence_rows[i]["candidate"]["score"] for i in groups[oid])
    )
    llm_allowed = set(order[:max_llm_calls]) if use_llm else set()

    def compare_group(oid: str) -> tuple[str, list[dict], dict]:
        rows = [evidence_rows[i] for i in groups[oid]]
        o = rows[0]["obligation"]
        items = [
            {
                "internal": ev["clause"],
                "evidence": {"span": ev["span"], "shared_terms": ev["candidate"]["shared_terms"]},
                "context": ev["context"],
            }
            for ev in rows
        ]
        results, stats = judge_group(o, o["clause_text"], items, oid in llm_allowed, refresh)
        return oid, results, stats

    results: list[dict | None] = [None] * len(evidence_rows)
    llm_calls = cache_hits = 0
    workers = max(1, settings.llm_concurrency) if llm_allowed else 1
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ria-compare") as pool:
        futures = [pool.submit(compare_group, oid) for oid in groups]
        for done, future in enumerate(as_completed(futures), start=1):
            oid, group_results, stats = future.result()
            llm_calls += stats["llm_calls"]
            cache_hits += stats["cache_hits"]
            for i, r in zip(groups[oid], group_results, strict=True):
                results[i] = r
            if done % 10 == 0:
                jobs.update_progress(
                    job_id, "comparison", 55 + int(40 * done / max(1, len(groups)))
                )

    pairs_by_group: dict[tuple[str, str], list[tuple[dict, dict]]] = {}
    for ev, result in zip(evidence_rows, results, strict=True):
        key = (ev["obligation"]["obligation_id"], ev["clause"]["document_id"])
        pairs_by_group.setdefault(key, []).append((ev, result))

    finding_rows = []
    for pairs in pairs_by_group.values():
        # Most severe category first; among equals, the clause the LLM picked as best match,
        # then the strongest retrieval score.
        pairs.sort(
            key=lambda p: (
                _CATEGORY_RANK[p[1]["category"]],
                not p[1].get("llm_best"),
                -p[0]["candidate"]["score"],
            )
        )
        ev, result = pairs[0]
        o, clause = ev["obligation"], ev["clause"]
        checks = [*result["checks"], temporal]
        if o.get("condition") or o.get("exception"):
            checks.append(
                {
                    "check": "scope_exceptions",
                    "status": "needs_review",
                    "detail": {"condition": o.get("condition"), "exception": o.get("exception")},
                }
            )
        checks.append({"check": "human_approval", "status": "pending"})
        grounded = all(c["status"] != "fail" for c in checks if c["check"] == "source_grounding")
        category = result["category"]
        finding_rows.append(
            {
                "id": f"RIA-{uuid.uuid4().hex[:10]}",
                "job": job_id,
                "reg": version_id,
                "doc": clause["document_id"],
                "cid": clause["clause_id"],
                "obl": o["obligation_id"],
                "ev": ev["evidence_id"],
                "evs": [p[0]["evidence_id"] for p in pairs],
                "category": category,
                "rationale": result["rationale"],
                "status": "NO_ACTION_PROPOSED" if category == "EQUIVALENT" else "AI_PROPOSED",
                "priority": PRIORITY[category],
                "confidence": result["confidence"],
                "src": json.dumps(result["source_span"], ensure_ascii=False),
                "tgt": json.dumps(result["target_span"], ensure_ascii=False),
                "verification": json.dumps(
                    {
                        "status": "NEEDS_HUMAN_REVIEW" if grounded else "BLOCKED",
                        "checks": checks,
                        "conditions_to_verify": result.get("conditions_to_verify", []),
                        "llm_best_clause": result.get("llm_best", False),
                        "other_clauses": [
                            {"clause_id": p[0]["clause"]["clause_id"], "category": p[1]["category"]}
                            for p in pairs[1:]
                        ],
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                "citations": [o["clause_id"], *[p[0]["clause"]["clause_id"] for p in pairs]],
                "method": result["method"],
            }
        )

    finding_rows += _graph_findings(
        linked, corpus, job_id, version_id, job["document_id"], temporal
    )
    graph_info["findings"] = sum(1 for f in finding_rows if f["method"] == "graph")
    graph_info["linked_documents"] = linked[:50]

    with get_engine().begin() as conn:
        if finding_rows:
            conn.execute(
                text(
                    "INSERT INTO impact_finding (finding_id, job_id, regulation_version_id, "
                    "impacted_document_id, internal_clause_id, obligation_id, evidence_id, "
                    "evidence_ids, category, rationale, status, priority, confidence, "
                    "source_span, target_span, verification, citations, method) VALUES "
                    "(:id, :job, :reg, :doc, :cid, :obl, :ev, :evs, :category, :rationale, "
                    ":status, :priority, :confidence, CAST(:src AS jsonb), CAST(:tgt AS jsonb), "
                    "CAST(:verification AS jsonb), :citations, :method)"
                ),
                finding_rows,
            )
            conn.execute(
                text(
                    "INSERT INTO obligation_clause (obligation_id, clause_id, role) "
                    "VALUES (:obl, :cid, 'aligned') ON CONFLICT DO NOTHING"
                ),
                [
                    {"obl": ev["obligation"]["obligation_id"], "cid": ev["clause"]["clause_id"]}
                    for ev in evidence_rows
                ],
            )
        _set_status(conn, version_id, "AI_PROPOSED")

    by_category = Counter(f["category"] for f in finding_rows)
    covered = len(in_scope) - len(uncovered)
    return {
        "regulation_id": job["document_id"],
        "version_id": version_id,
        "status": "AI_PROPOSED",
        "parameters": {**asdict(params), "modalities": sorted(modalities)},
        "retrieval_methods": ["sparse"]
        + (["dense"] if model else [])
        + (["rerank"] if reranker else []),
        "embedding_version": model or "none",
        "rerank_model": reranker,
        "llm_model": llm.llm_model() if use_llm else None,
        "llm_calls": llm_calls,
        "llm_cache_hits": cache_hits,
        "obligations": {
            "total": len(obligations),
            "analyzed": len(in_scope),
            "skipped": dict(skipped),
            "applicability": applicability,
            "with_evidence": covered,
            "coverage": round(covered / max(1, len(in_scope)), 4),
        },
        "internal_corpus": {
            "documents": len(corpus.document_ids),
            "clauses": len(corpus.clauses),
        },
        "documents": shortlist,
        "evidence": len(evidence_rows),
        "findings": len(finding_rows),
        "findings_by_category": dict(by_category),
        "findings_by_priority": dict(Counter(f["priority"] for f in finding_rows)),
        # Coverage audit: "chưa tìm thấy" — not a conclusion of non-compliance.
        "uncovered_obligations": [
            {"obligation_id": o["obligation_id"], "text": o["text"][:200]} for o in uncovered[:50]
        ],
        "graph": graph_info,
        "warnings": warnings,
    }


def _add_dependent_clauses(evidence_rows: list[dict], corpus, params: RetrievalParams) -> int:
    """Knowledge graph expansion: clauses that refer to an evidence clause (or its article) may be
    impacted too ("thời hạn tại Điều 5"). Add them as evidence; Engine 2 judges them."""
    top: dict[str, list[dict]] = {}
    for ev in evidence_rows:
        top.setdefault(ev["obligation"]["obligation_id"], []).append(ev)
    sources = {
        ev["clause"]["clause_id"]
        for rows in top.values()
        for ev in sorted(rows, key=lambda e: -e["candidate"]["score"])[:2]
    }
    try:
        pairs = graph.dependent_clauses(sorted(sources))
    except Exception as exc:
        log.warning("graph expansion failed: %s", exc)
        return 0
    dependents: dict[str, list[str]] = {}
    for src, dep in pairs:
        if dep in corpus.clauses:
            dependents.setdefault(src, []).append(dep)
    added = 0
    for rows in top.values():
        have = {ev["clause"]["clause_id"] for ev in rows}
        o = rows[0]["obligation"]
        new = 0
        for ev in sorted(rows, key=lambda e: -e["candidate"]["score"])[:2]:
            for dep in dependents.get(ev["clause"]["clause_id"], []):
                if dep in have or new >= params.graph_neighbors:
                    continue
                have.add(dep)
                new += 1
                clause = corpus.clauses[dep]
                lex = lexical_overlap(gate_query(o), dep, corpus, params.min_term_idf)
                evidence_rows.append(
                    {
                        "evidence_id": f"EV-{uuid.uuid4().hex[:12]}",
                        "obligation": o,
                        "clause": clause,
                        "candidate": {
                            "clause_id": dep,
                            "document_id": clause["document_id"],
                            "score": round(ev["candidate"]["score"] * 0.9, 4),
                            "rrf": 0.0,
                            "ranks": {"graph:refers_to": 1},
                            "dense": None,
                            "rerank": None,
                            "shared_terms": lex["shared"][:10],
                            "idf_score": round(lex["idf_score"], 3),
                            "graph_from": ev["clause"]["clause_id"],
                        },
                        "span": best_sentence_span(clause["text"], lex["shared"]),
                        "method": "graph:refers_to",
                        "context": parent_context(dep, corpus),
                    }
                )
        added += new
    return added


_GRAPH_RATIONALE = {
    "cites_regulation": "dẫn chiếu trực tiếp văn bản đang phân tích ({via})",
    "cites_superseded": (
        "căn cứ văn bản {via}, văn bản đã bị văn bản đang phân tích thay thế/bãi bỏ"
    ),
    "shared_legal_basis": (
        "cùng căn cứ pháp lý {via} với điều khoản {rc} của văn bản đang phân tích"
    ),
}
_GRAPH_PRIORITY = {
    "cites_regulation": "high",
    "cites_superseded": "high",
    "shared_legal_basis": "low",
}


def _graph_findings(linked, corpus, job_id, version_id, regulation_id, temporal) -> list[dict]:
    """Document-level findings: an internal document relies on the regulation, on a document it
    replaces, or on the same law. No obligation: the link is to the document as a whole."""
    groups: dict[tuple, list[dict]] = {}
    for link in linked:
        groups.setdefault((link["document_id"], link["relation"], link["via"]), []).append(link)
    rows = []
    for (doc_id, relation, via), links in groups.items():
        clause_ids = [lk["clause_id"] for lk in links if lk["clause_id"]]
        first = clause_ids[0] if clause_ids else None
        target = None
        if first:
            clause_text = corpus.clauses[first]["text"]
            at = clause_text.find(via.split(" ", 1)[-1]) if via else -1
            if at >= 0:
                end = at + len(via.split(" ", 1)[-1])
                target = {"text": clause_text[at:end], "start": at, "end": end}
        rc = (links[0].get("regulation_clause_id") or "").split("#")[-1]
        where = f"Điều khoản {first.split('#')[-1]}" if first else "Phần căn cứ của văn bản"
        rows.append(
            {
                "id": f"RIA-{uuid.uuid4().hex[:10]}",
                "job": job_id,
                "reg": version_id,
                "doc": doc_id,
                "cid": first,
                "obl": None,
                "ev": None,
                "evs": [],
                "category": "INDIRECT_IMPACT",
                "rationale": (
                    f"{where} của {doc_id} "
                    + _GRAPH_RATIONALE[relation].format(via=via, rc=rc or "?")
                    + ". Liên kết tìm qua đồ thị tri thức, không qua so khớp nội dung; "
                    "cần rà soát căn cứ và các điều khoản dựa trên nó."
                ),
                "status": "AI_PROPOSED",
                "priority": _GRAPH_PRIORITY[relation],
                "confidence": 0.6 if relation != "shared_legal_basis" else 0.3,
                "src": json.dumps(None),
                "tgt": json.dumps(target, ensure_ascii=False),
                "verification": json.dumps(
                    {
                        "status": "NEEDS_HUMAN_REVIEW",
                        "checks": [
                            {
                                "check": "graph_link",
                                "status": "info",
                                "detail": {"relation": relation, "via": via, "clauses": clause_ids},
                            },
                            temporal,
                            {"check": "human_approval", "status": "pending"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                "citations": [regulation_id, *(clause_ids or [doc_id])],
                "method": "graph",
            }
        )
    return rows


jobs.register("analyze", run_analysis)
