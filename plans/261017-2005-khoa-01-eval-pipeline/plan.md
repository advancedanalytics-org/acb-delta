---
title: "Evaluation Pipeline and Feedback Loop"
description: "Measure every step of the impact-analysis agent against ground truth, then feed HITL decisions back into it."
status: in-progress
priority: P1
effort: "2-3d"
tags: [eval, rlhf, KHOA-01, KHOA-02]
created: 2026-10-17
branch: khoa-01-eval-pipeline
---

## Overview

`KHOA-01` measures how well the agent finds and fixes impacts; `KHOA-02` feeds reviewer decisions
back in and measures whether that helped. Both need one thing first: a definition of what "correct"
means for each pipeline step, and functions that compute it.

The input side of evaluation is blocked on three other tasks — ground truth (`TAI-03`), the real
agent nodes (`TAI-01`), the chunk schema and retriever (`MINH-01`) — and `PLAN.md` still records
both of this plan's data flows as `_chưa chốt_`. The metric layer is not blocked by any of them,
because metrics are pure functions over (expected, predicted) pairs. So phase 1 builds that layer
and, in doing so, states the data contract the other tasks have to meet. The schema *is* the
proposal to take to the team meeting.

`EvalMetrics` and `EvalRun` in `frontend/src/api/types.ts` are already committed and assigned to
`KHOA-01`, so the output shape is not an open question — only how the numbers get produced.

## Goals

| # | Goal | Priority |
|---|---|---|
| 1 | Define the ground-truth and pipeline-output shapes as a named adapter boundary | P1 |
| 2 | Compute `extraction`, `retrieval`, `impact` and `system` metrics with hand-checkable tests | P1 |
| 3 | Run the real agent over a dataset and record a reproducible `EvalRun` | P1 |
| 4 | Serve `GET /api/eval/runs` so the Evaluation dashboard stops showing "Chưa có API (KHOA-01)" | P2 |
| 5 | Turn HITL accept / edit decisions into dynamic few-shot examples, and measure before / after | P2 |
| 6 | Export (chosen, rejected) preference pairs for DPO | P3 (roadmap per `PLAN.md`) |

## Non-goals

- Inventing the mock-document format, the chunk schema, or the HITL API — those belong to
  `MINH-02`, `MINH-01` and `TAI-02`.
- Fabricating ground truth. `TAI-03` plants the conflicts and records them; this plan only defines
  the file shape and validates it.
- Fine-tuning or training. "RLHF" here is dynamic few-shot plus a preference-pair export, as
  `PLAN.md` scopes it.
- Self-hosting Langfuse.

## Architecture

```text
 TAI-03 ground truth                     agent: TAI-01 nodes + MINH-01 retriever
   dataset JSON                                    POST /invoke :8080
        |                                                  |
        v                                                  v
   DatasetItem[]                                   raw graph output
        |                                                  |
        |                                    runner + adapter (phase 2)
        |                                                  |
        +------------------> pair_items() <----------------+
                                  |
                                  v
                        metrics.evaluate() -> StageScores
                                  |
     extraction P/R · retrieval Recall@5 + MRR · impact P/R/F1 + label accuracy · latency/cost
                                  |
                                  v
                            EvalRun (phase 3)
                                  |
                                  v
                    GET /api/eval/runs -> Evaluation dashboard (HUY-01)
                                  ^
                                  |
   TAI-02 HITL decisions ---------+------> hitlAcceptRate, LLM-judge rubric (phase 4)
        |
        +------> dynamic few-shot + preference pairs (phase 5, KHOA-02)
```

Two runs sitting next to each other in the `GET /api/eval/runs` array *are* the "before / after
feedback" comparison: `evaluation-page.tsx` derives the baseline from array position, so the
endpoint must return runs oldest first.

## Phases

| # | Phase | Status | Blocked by |
|---|---|---|---|
| 1 | Metric core: schema, matching rules, step metrics, tests | completed | — |
| 2 | Runner: drive the agent over a dataset, convert output, time and cost it | not started | `TAI-01` nodes are stubs; `/invoke` drops `candidates` and `amendments` |
| 3 | Persist an `EvalRun` and serve `GET /api/eval/runs` | not started | storage source of truth undecided |
| 4 | LLM-as-judge rubric + `hitlAcceptRate` | not started | Phase 1 LLM endpoint (`TAI-06`), HITL table (`TAI-02`) |
| 5 | `KHOA-02`: few-shot from decisions, before/after run, DPO export | not started | `TAI-02`, phase 3 |

Phase docs are written when a phase starts, not up front.

## Success Criteria

- [x] Every metric has a test whose expected value is computed by hand in a comment
- [x] `./scripts/run.sh test` passes with the new tests
- [ ] One experiment runs end to end over the `TAI-03` dataset and produces an `EvalRun`
- [ ] The Evaluation dashboard renders real numbers in `VITE_API_MODE=live`
- [ ] A measured before / after pair exists for the demo, with the feedback source written in `note`

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Clause matching | Exact match on the normalized `Điều / Khoản / Điểm` path (`"Điều 3, khoản 1"` → `3.1`) | Legal structure gives a natural key; fuzzy text similarity makes two runs of the same pipeline disagree |
| Impact identity | The `(change, chunk)` pair. `type` and `severity` scored separately over matched impacts | `PLAN.md` prioritises detection Recall — a missed impact is the expensive error, a mislabelled one is cheap to fix in review and should be visible on its own |
| Unmeasured stages | Absent (`None`), never `0` | `AGENTS.md` forbids fake results, and `0` reads as a measured failure. Consequence: `EvalMetrics` in `types.ts` needs nullable leaves before phase 3 |
| Aggregation | Micro-average precision/recall across items; macro-average Recall@k and MRR over changes | An item carrying ten impacts should weigh ten times one carrying a single impact; Recall@k/MRR per query is the IR convention |
| `k` | 5, fixed | `evaluation-page.tsx` hardcodes the label `"Recall@5"` |
| Retrieval blind spot | A change with no retrieval at all scores recall 0, not "skipped" | Otherwise a pipeline that extracts nothing reports perfect retrieval |
| Code location | `backend/app/evaluation/` | Phase 1 needs no DB, LLM or Langfuse, so no compose or `run.sh` change; `backend/` is already in the test gate and the eval endpoint lands here anyway |

## Open Questions

1. **Storage source of truth** (`PLAN.md`: `_chưa chốt_`). Postgres with Langfuse as optional
   tracing, Langfuse datasets as primary, or JSON in the repo? Langfuse Cloud Hobby keeps data 30
   days, which would delete the demo baseline before the presentation.
2. **Ground truth shape** — can `TAI-03` produce `DatasetItem` as defined in
   `backend/app/evaluation/schema.py`, in particular a `chunk_id` per expected impact?
3. **`chunk_id` provenance** (`MINH-01`) — retrieval metrics are only meaningful if chunk ids are
   stable across a re-index. If re-embedding renumbers them, ground truth rots.
4. **`/invoke` contract** (`TAI-01`) — it currently returns `changes` and `impacts` only. Retrieval,
   amendment and system metrics need `candidates`, `amendments`, latency and token usage.
5. **`EvalMetrics` nullability** (`HUY-01`) — the dashboard reads every leaf unconditionally and
   would crash on a missing group. `KHOA-01` owns `EvalRun`, but Huy has to adapt the screen.
6. **Enrich-test-set mechanics** — a reject or edit becomes a new dataset item, but who assigns its
   `item_id` and ground truth, and does an edited text become the new gold `reference_amendment`?
