"""Run one experiment over the RIA path and score it (KHOA-01).

Drives the endpoints the UI uses (`docs/amendment-review-contract.md` §3), so the numbers describe
the production path and not a test harness:

    POST /api/regulations                  upload the regulation  -> parse job
    POST /api/regulations/{id}/analyze     RIA finds findings     -> analyze job
    POST /api/regulations/{id}/review      agent drafts patches   -> review job
    GET  /api/vbpls/{vbpl_id}/impacts      the review package

Three things are not on the API and are read from the RIA tables of that same `job_id`: the
obligations RIA extracted, the retrieval ranks in `evidence`, and the exact
(obligation, internal clause) pair behind each finding. Matching on those ids is exact; matching on
`citation` text would not be.

Scoring goes through `app.evaluation.metrics` unchanged -- this module only adapts RIA shapes into
`DatasetItem` / `PipelineOutput`, which is the adapter boundary `docs/evaluation-data-contract.md`
describes. It never invents a number: a run is posted only when all five metric groups were
measured, because the dashboard reads every leaf without a null check.
"""

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

from app.evaluation.metrics import DEFAULT_K, ItemOutcome, evaluate, pair_items
from app.evaluation.schema import (
    DatasetItem,
    ExpectedChange,
    ExpectedImpact,
    PipelineOutput,
    PredictedChange,
    PredictedImpact,
    PredictedRetrieval,
    RiaDatasetItem,
    load_ria_dataset,
)

# RetrievalParams keeps only the top 5 evidence rows per obligation by default
# (app/ria/retrieval.py); 20 keeps Recall@5 from being capped by that cut rather than the ranking.
ANALYZE_PARAMS = {"evidence_per_obligation": 20, "candidates_per_query": 20}
JOB_POLL_SECONDS = 3
JOB_TIMEOUT_SECONDS = 1800

# docs/amendment-review-contract.md §2, "Category → type của UI".
TYPE_BY_CATEGORY = {
    "VALUE_CHANGE": "conflict",
    "CONTRADICTION": "conflict",
    "SCOPE_CHANGE": "conflict",
    "ADDITION": "new_obligation",
    "INDIRECT_IMPACT": "outdated_reference",
}

JUDGE_SYSTEM = (
    "Bạn là chuyên gia pháp chế ngân hàng, chấm điểm một bản sửa do AI đề xuất so với bản sửa "
    "tham chiếu đúng. Chấm 1-5 theo ba tiêu chí: đúng nội dung, sửa tối thiểu (chỉ đổi phần cần "
    'đổi), nhất quán pháp lý. Trả về JSON {"score": <1-5>, "reason": "<ngắn gọn>"}.'
)


class RunnerError(RuntimeError):
    pass


@dataclass
class RunArtifacts:
    """What one pipeline run produced, keyed the way the labels are keyed."""

    regulation_id: str
    analyze_job_id: str
    vbpl_id: str
    impacts: list[dict]
    obligations: set[str] = field(default_factory=set)
    retrieval: dict[str, list[str]] = field(default_factory=dict)
    # (finding id, obligation numbering, internal clause id, category, priority). The finding id is
    # the only key the review package shares with these rows: it carries no internal clause id.
    findings: list[tuple[str, str, str, str, str]] = field(default_factory=list)
    latency_seconds: float = 0.0
    # When the analysis ran. Only set when scoring a finished job, where "now" is not the run time.
    started_at: str | None = None


def numbering(clause_id: str) -> str:
    """`REG-88-2026-TT-NHNN@v1#2.1` -> `2.1`. Ids differ per document, the numbering does not."""
    return clause_id.split("#", 1)[1] if "#" in clause_id else clause_id


# --- driving the pipeline -----------------------------------------------------------------------


def _wait_for_job(client: httpx.Client, job_id: str, stage: str) -> dict:
    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    while True:
        job = client.get(f"/api/jobs/{job_id}").raise_for_status().json()
        status = job.get("status")
        if status == "succeeded":
            return job
        if status == "failed":
            raise RunnerError(f"{stage} job {job_id} failed: {job.get('error')}")
        if time.monotonic() > deadline:
            raise RunnerError(f"{stage} job {job_id} still {status} after {JOB_TIMEOUT_SECONDS}s")
        print(f"  {stage}: {status} {job.get('stage') or ''}".rstrip())
        time.sleep(JOB_POLL_SECONDS)


def _read_ria_tables(database_url: str, job_id: str) -> tuple[set[str], dict, list]:
    engine = create_engine(database_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as conn:
            obligations = set(
                conn.execute(
                    text(
                        "SELECT DISTINCT split_part(source_clause_id, '#', 2) FROM obligation "
                        "WHERE obligation_id IN "
                        "(SELECT obligation_id FROM evidence WHERE job_id = :job "
                        " UNION SELECT obligation_id FROM impact_finding WHERE job_id = :job)"
                    ),
                    {"job": job_id},
                ).scalars()
            )
            ranked: dict[str, list[str]] = {}
            # Ordered by score: that is the ranking RRF produced, so position == rank.
            for number, clause_id in conn.execute(
                text(
                    "SELECT split_part(o.source_clause_id, '#', 2), e.internal_clause_id "
                    "FROM evidence e JOIN obligation o ON o.obligation_id = e.obligation_id "
                    "WHERE e.job_id = :job ORDER BY o.source_clause_id, e.score DESC"
                ),
                {"job": job_id},
            ):
                ranked.setdefault(number, []).append(clause_id)
            findings = [
                (finding_id, number, clause_id, category, priority)
                for finding_id, number, clause_id, category, priority in conn.execute(
                    text(
                        "SELECT f.finding_id, split_part(o.source_clause_id, '#', 2), "
                        "f.internal_clause_id, f.category, f.priority FROM impact_finding f "
                        "JOIN obligation o ON o.obligation_id = f.obligation_id "
                        "WHERE f.job_id = :job"
                    ),
                    {"job": job_id},
                )
            ]
            return obligations, ranked, findings
    finally:
        engine.dispose()


def _job_timings(database_url: str, job_id: str) -> tuple[str, float, str | None]:
    """The review package of an analyze job, and how long that analysis plus its review took.

    `vbpls.ria_job_id` is unique per analyze job (contract §2), so the package is reachable from
    the job id alone. Latency comes from the job rows rather than a wall clock, which is both more
    accurate and the only option when scoring a run that finished earlier.
    """
    engine = create_engine(database_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as conn:
            vbpl_id = conn.execute(
                text("SELECT id FROM vbpls WHERE ria_job_id = :job"), {"job": job_id}
            ).scalar()
            if vbpl_id is None:
                raise RunnerError(f"No review package for analyze job {job_id}")
            seconds = conn.execute(
                text(
                    "SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (finished_at - started_at))), 0) "
                    # Only this analysis's own review jobs: matching on version_id also summed
                    # the reviews of every earlier analysis of the same regulation version.
                    "FROM job WHERE job_id = :job "
                    "OR (job_type = 'review' AND params->>'analyze_job_id' = :job)"
                ),
                {"job": job_id},
            ).scalar()
            started = conn.execute(
                text("SELECT started_at FROM job WHERE job_id = :job"), {"job": job_id}
            ).scalar()
            return vbpl_id, float(seconds or 0.0), started.isoformat() if started else None
    finally:
        engine.dispose()


def score_existing_job(client: httpx.Client, job_id: str, database_url: str) -> RunArtifacts:
    """Build artifacts for an analyze job that already ran, without touching the pipeline.

    `hitlAcceptRate` only exists once people have reviewed a run's output, so a freshly finished
    run can never carry it. Scoring is therefore a second pass over an earlier job.
    """
    vbpl_id, latency, started_at = _job_timings(database_url, job_id)
    impacts = client.get(f"/api/vbpls/{vbpl_id}/impacts").raise_for_status().json()
    obligations, ranked, findings = _read_ria_tables(database_url, job_id)
    return RunArtifacts(
        regulation_id="",
        analyze_job_id=job_id,
        vbpl_id=vbpl_id,
        impacts=impacts,
        obligations=obligations,
        retrieval=ranked,
        findings=findings,
        latency_seconds=latency,
        started_at=started_at,
    )


def run_pipeline(client: httpx.Client, pdf_path: Path, database_url: str) -> RunArtifacts:
    started = time.monotonic()
    print("1/4 upload")
    body = (
        client.post(
            "/api/regulations",
            files={"file": (pdf_path.name, pdf_path.read_bytes(), "application/pdf")},
        )
        .raise_for_status()
        .json()
    )
    regulation_id = body["regulation_id"]
    if body.get("duplicate"):
        print(f"  already ingested: {regulation_id}")
    _wait_for_job(client, body["job_id"], "parse")

    print("2/4 analyze")
    analyze_job = (
        client.post(f"/api/regulations/{regulation_id}/analyze", json=ANALYZE_PARAMS)
        .raise_for_status()
        .json()["job_id"]
    )
    _wait_for_job(client, analyze_job, "analyze")

    print("3/4 review (agent drafts the patches)")
    review = client.post(f"/api/regulations/{regulation_id}/review").raise_for_status().json()
    _wait_for_job(client, review["review_job_id"], "review")

    print("4/4 read the review package")
    impacts = client.get(f"/api/vbpls/{review['vbpl_id']}/impacts").raise_for_status().json()
    latency = time.monotonic() - started

    obligations, ranked, findings = _read_ria_tables(database_url, analyze_job)
    return RunArtifacts(
        regulation_id=regulation_id,
        analyze_job_id=analyze_job,
        vbpl_id=review["vbpl_id"],
        impacts=impacts,
        obligations=obligations,
        retrieval=ranked,
        findings=findings,
        latency_seconds=latency,
    )


# --- adapter: RIA shapes -> the shapes metrics.py already scores --------------------------------


def to_outcome(item: RiaDatasetItem, run: RunArtifacts) -> ItemOutcome:
    """Map labels and run onto `DatasetItem` / `PipelineOutput` so `evaluate()` can score them.

    An obligation plays the role of a "change"; an internal clause the role of a "chunk".
    `EQUIVALENT` labels are left out of the expected set on purpose: the pipeline must not report
    them, so they only ever appear as false positives, which is how Precision sees them.
    """
    expected = DatasetItem(
        item_id=item.item_id,
        vbpl_id=item.regulation_number,
        changes=[
            ExpectedChange(article_path=numbering(o.clause_id), kind="amended")
            for o in item.obligations
        ],
        impacts=[
            ExpectedImpact(
                change_path=numbering(f.obligation_clause_id),
                document_id=f.internal_clause_id.split("@", 1)[0],
                chunk_id=f.internal_clause_id,
                type=TYPE_BY_CATEGORY.get(f.category, "conflict"),
                severity=f.priority,
                reference_amendment=f.reference_patch.new_text if f.reference_patch else None,
            )
            for f in item.expected_findings
        ],
    )
    predicted = PipelineOutput(
        item_id=item.item_id,
        changes=[PredictedChange(article_path=n, kind="amended") for n in sorted(run.obligations)],
        retrieval=[
            PredictedRetrieval(change_path=n, chunk_ids=ids) for n, ids in run.retrieval.items()
        ],
        impacts=[
            PredictedImpact(
                change_path=number,
                document_id=clause_id.split("@", 1)[0],
                chunk_id=clause_id,
                type=TYPE_BY_CATEGORY.get(category, "conflict"),
                # impact_finding.priority is RIA's severity (contract §2), so severity accuracy
                # compares two real labels rather than a placeholder.
                severity=priority if priority in ("high", "medium", "low") else "medium",
            )
            for _, number, clause_id, category, priority in run.findings
            if category != "EQUIVALENT"
        ],
        latency_seconds=run.latency_seconds,
    )
    return pair_items([expected], [predicted])[0]


# --- the two metrics that need more than the labels ---------------------------------------------


def hitl_accept_rate(client: httpx.Client, vbpl_id: str) -> float | None:
    """Share of decided impacts the reviewer took as written. `None` when nobody has reviewed yet.

    `accept` only, not `accept` + `edit`. `PLAN.md` asks for the accept rate, and as a measure of
    suggestion quality an edit says the draft was not good enough to use: the reviewer had to
    rewrite it. That differs from the UI's `status`, which calls an edited impact `accepted`
    because the workflow step is finished -- a different question from whether the AI was right.
    """
    rows = client.get("/api/feedback", params={"vbplId": vbpl_id}).raise_for_status().json()
    if not rows:
        return None
    return sum(1 for r in rows if r["action"] == "accept") / len(rows)


def judge_score(item: RiaDatasetItem, run: RunArtifacts) -> float | None:
    """Mean LLM-judge score (1-5) of the drafted patches against the reference patches.

    `None` when no LLM is configured or no label has a reference patch -- never a stand-in number.
    """
    from app.ria.llm import chat_json, llm_model

    if llm_model() is None:
        return None
    reference = {
        f.internal_clause_id: f.reference_patch for f in item.expected_findings if f.reference_patch
    }
    # GET /api/vbpls/{id}/impacts carries `findingId` but no internal clause id, so the labels are
    # reached through the finding rows read from the same job.
    clause_of_finding = {finding_id: clause_id for finding_id, _, clause_id, _, _ in run.findings}
    scores = []
    for impact in run.impacts:
        clause_id = clause_of_finding.get(impact.get("findingId"))
        patch, want = impact.get("patch"), reference.get(clause_id)
        if not patch or want is None or impact.get("draftStatus") != "review_required":
            continue
        answer = chat_json(
            JUDGE_SYSTEM,
            json.dumps(
                {
                    "ban_sua_ai": {
                        "operation": patch.get("operation"),
                        "old_text": patch.get("oldText"),
                        "new_text": patch.get("newText"),
                    },
                    "ban_sua_tham_chieu": want.model_dump(),
                    "van_ban_noi_bo": impact.get("affectedText"),
                },
                ensure_ascii=False,
            ),
        )
        score = answer.get("score")
        if isinstance(score, int | float) and 1 <= score <= 5:
            scores.append(float(score))
    return sum(scores) / len(scores) if scores else None


# --- CLI ----------------------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run and score one RIA experiment.")
    parser.add_argument("--dataset", type=Path, default=Path("../data/eval/dataset.json"))
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--database-url", required=True, help="Postgres URL reachable from here")
    parser.add_argument("--label", required=True, help="Shown in the dashboard's run picker")
    parser.add_argument("--note", default="", help="Where the numbers come from")
    # Cost is not on this run's API surface: Langfuse records it per generation (agent/agent/llm.py
    # propagates the callback). Read it there and pass it in rather than letting the runner guess.
    parser.add_argument(
        "--cost-usd", type=float, default=None, help="Cost per document, read from Langfuse"
    )
    parser.add_argument("--post", action="store_true", help="Save via POST /api/eval/runs")
    # The POST body written to disk is a seed for `app.evaluation.seed`, so the demo dashboard can
    # be restored from a real measured run after a fresh deploy. Works with or without --post.
    parser.add_argument(
        "--save", type=Path, default=None, help="Write the POST body to this JSON file (a seed)"
    )
    # hitlAcceptRate only exists after people review a run, so recording a run is a second pass.
    parser.add_argument(
        "--job", default=None, help="Score an analyze job that already ran, instead of running one"
    )
    args = parser.parse_args()

    items = load_ria_dataset(args.dataset)
    if len(items) != 1:
        raise RunnerError(f"Expected exactly one dataset item, got {len(items)}")
    item = items[0]
    pdf_path = args.dataset.parent / item.regulation_pdf
    if not args.job and not pdf_path.is_file():
        raise RunnerError(f"{pdf_path} missing; run `python -m app.evaluation.ground_truth` first")

    with httpx.Client(base_url=args.api, timeout=180) as client:
        if args.job:
            run = score_existing_job(client, args.job, args.database_url)
        else:
            run = run_pipeline(client, pdf_path, args.database_url)
        stages = evaluate([to_outcome(item, run)], k=DEFAULT_K)
        accept_rate = hitl_accept_rate(client, run.vbpl_id)
        judge = judge_score(item, run)

        print()
        print(stages.model_dump_json(indent=2))
        print(f"\nhitlAcceptRate: {accept_rate}   judgeScore: {judge}")
        print(
            f"nhãn: {len(item.expected_findings)} finding phải báo, "
            f"{len(item.findings) - len(item.expected_findings)} equivalent (đo false positive); "
            f"pipeline báo {len(run.impacts)} impact"
        )

        unmeasured = [
            name
            for name, value in (
                ("amendment.judgeScore", judge),
                ("amendment.hitlAcceptRate", accept_rate),
                ("system.costUsdPerDocument (--cost-usd)", args.cost_usd),
            )
            if value is None
        ]
        if unmeasured:
            # Saved as null, not 0: the dashboard shows a dash for these.
            print("\nLưu dạng chưa đo (null): " + ", ".join(unmeasured))

        body = {
            "label": args.label,
            "datasetSize": len(item.findings),
            "note": args.note,
            "metrics": {
                "extraction": {
                    "precision": stages.extraction.precision,
                    "recall": stages.extraction.recall,
                },
                "retrieval": {
                    "recallAtK": stages.retrieval.recall_at_k,
                    "k": stages.retrieval.k,
                    "mrr": stages.retrieval.mrr,
                },
                "impact": {
                    "precision": stages.impact.detection.precision,
                    "recall": stages.impact.detection.recall,
                    "f1": stages.impact.detection.f1,
                },
                "amendment": {"judgeScore": judge, "hitlAcceptRate": accept_rate},
                "system": {
                    "latencySeconds": run.latency_seconds,
                    "costUsdPerDocument": args.cost_usd,
                },
            },
            "params": {**ANALYZE_PARAMS, "analyzeJobId": run.analyze_job_id},
            **({"createdAt": run.started_at} if run.started_at else {}),
        }

        if args.save:
            args.save.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\nđã ghi seed: {args.save}")

        if not args.post:
            print("\n--post không bật: chưa lưu run nào.")
            return

        saved = client.post("/api/eval/runs", json=body).raise_for_status().json()
        print(f"\nđã lưu run {saved['id']}")


if __name__ == "__main__":
    main()
