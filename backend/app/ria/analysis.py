"""POST /api/regulations/{id}/analyze: impact analysis job (design sections 07–11, 14–16).

PARSED → (Engine 1: retrieval, evidence) → RETRIEVAL_COMPLETED → (Engine 2: comparison,
findings) → AI_PROPOSED. Each run keeps its own evidence and findings (job_id = lineage);
nothing is overwritten and no internal document is modified.
"""

import json
import re
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, fields

from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.ria import embeddings, jobs, llm
from app.ria.compare import PRIORITY, classify
from app.ria.retrieval import (
    RetrievalParams,
    aggregate_documents,
    best_sentence_span,
    build_queries,
    load_internal_corpus,
    parent_context,
    retrieve_for_obligation,
)
from app.ria.schema import ensure_schema

ANALYZABLE = ("PARSED", "RETRIEVAL_COMPLETED", "AI_PROPOSED")
# Duties of state bodies (ministries, the Government, People's Committees) bind no bank unit.
_STATE_SUBJECT = re.compile(
    r"^(Bộ\s|Bộ trưởng|Chính phủ|Thủ tướng|Ủy ban nhân dân|Ủy ban Nhân dân|Cơ quan chuyên trách|"
    r"Cơ quan quản lý nhà nước|Ngân hàng Nhà nước|Thống đốc|Thanh tra|Quốc hội)",
)


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
    max_llm_pairs = int(options.get("max_llm_pairs", 200))
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
        if not use_llm:
            warnings.append("LLM judge disabled; comparison is rule-based")

        in_scope, skipped = [], Counter()
        for o in obligations:
            if o["modality"] not in modalities:
                skipped["modality_filtered"] += 1
            elif _STATE_SUBJECT.match(o["subject"] or ""):
                skipped["state_body_duty"] += 1
            else:
                in_scope.append(o)

        # Engine 1: retrieval per obligation.
        jobs.update_progress(job_id, "retrieval", 5)
        query_vectors: dict[str, dict[str, list[float]]] = {}
        if model:
            flat = [
                (o["obligation_id"], name, q)
                for o in in_scope
                for name, q in build_queries(o).items()
                if name in ("legal_text", "proposition")
            ]
            vectors = embeddings.embed([q for _, _, q in flat])
            for (oid, name, _), vector in zip(flat, vectors, strict=True):
                query_vectors.setdefault(oid, {})[name] = vector

        per_obligation: dict[str, list[dict]] = {}
        traces: dict[str, dict] = {}
        for i, o in enumerate(in_scope):
            cands, trace = retrieve_for_obligation(
                conn, o, corpus, params, query_vectors.get(o["obligation_id"]), model
            )
            per_obligation[o["obligation_id"]] = cands
            traces[o["obligation_id"]] = trace
            if i % 25 == 0:
                jobs.update_progress(job_id, "retrieval", 5 + int(45 * i / max(1, len(in_scope))))

    shortlist = aggregate_documents(per_obligation, params)
    shortlisted = {d["document_id"] for d in shortlist}
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

    # Engine 2: compare each obligation ↔ clause pair and persist findings.
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

    # Classify every obligation ↔ clause pair, then group per (obligation, document).
    # The LLM budget goes to the strongest retrieval candidates first.
    by_score = sorted(
        range(len(evidence_rows)), key=lambda i: -evidence_rows[i]["candidate"]["score"]
    )
    llm_allowed = set(by_score[:max_llm_pairs]) if use_llm else set()

    def compare_pair(i: int) -> dict:
        ev = evidence_rows[i]
        return classify(
            ev["obligation"],
            ev["obligation"]["clause_text"],
            ev["clause"],
            {"span": ev["span"], "shared_terms": ev["candidate"]["shared_terms"]},
            ev["context"],
            i in llm_allowed,
        )

    results: list[dict | None] = [None] * len(evidence_rows)
    workers = max(1, get_settings().llm_concurrency) if llm_allowed else 1
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ria-compare") as pool:
        futures = {pool.submit(compare_pair, i): i for i in range(len(evidence_rows))}
        for done, future in enumerate(as_completed(futures), start=1):
            results[futures[future]] = future.result()
            if done % 10 == 0:
                jobs.update_progress(
                    job_id, "comparison", 55 + int(40 * done / max(1, len(evidence_rows)))
                )
    llm_calls = len(llm_allowed)

    pairs_by_group: dict[tuple[str, str], list[tuple[dict, dict]]] = {}
    for ev, result in zip(evidence_rows, results, strict=True):
        key = (ev["obligation"]["obligation_id"], ev["clause"]["document_id"])
        pairs_by_group.setdefault(key, []).append((ev, result))

    finding_rows = []
    for pairs in pairs_by_group.values():
        pairs.sort(key=lambda p: _CATEGORY_RANK[p[1]["category"]])
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
        "retrieval_methods": ["sparse"] + (["dense"] if model else []),
        "embedding_version": model or "none",
        "llm_model": llm.llm_model() if use_llm else None,
        "llm_calls": llm_calls,
        "obligations": {
            "total": len(obligations),
            "analyzed": len(in_scope),
            "skipped": dict(skipped),
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
        "warnings": warnings,
    }


jobs.register("analyze", run_analysis)
