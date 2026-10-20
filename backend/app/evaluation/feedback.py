"""Turn reviewer decisions into learning signal (KHOA-02).

Input is `GET /api/feedback`, the format `PLAN.md` records as agreed (Tài, 2026-10-18) and
`docs/amendment-review-contract.md` §4 defines. The query is reused from
`app.routers.decisions.list_feedback` rather than re-written, so this module cannot drift from the
contract.

Which decision teaches which step follows the contract's own note -- *"`edit` ≈ lỗi drafter,
`reject` ≈ lỗi judge của RIA"*:

| task | positive | negative | why |
|---|---|---|---|
| `draft` | `accept`, `edit` | `edit` | the reviewer kept or rewrote the patch: the signal is text |
| `judge` | `accept`, `edit` | `reject` | a reject says the finding should never have been raised |

A `reject` is not a drafter error: the text was fine to draft, the finding behind it was wrong. And
a draft that `failed` or was `skipped` carries no AI text at all, so it can teach the judge (the
finding still existed) but never the drafter.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.evaluation.schemas import ExampleSet, FeedbackExample
from app.routers.decisions import list_feedback

TASKS = ("draft", "judge")
# A dynamic few-shot prompt has to stay small; the caller can ask for more.
DEFAULT_LIMIT = 5


def _rationale(row) -> str | None:
    """Why RIA thought this was an impact, from `model_output.finding` (contract §2)."""
    finding = (row.model_output or {}).get("finding") or {}
    rationale = finding.get("rationale")
    return rationale if isinstance(rationale, str) else None


def _example(row) -> FeedbackExample:
    return FeedbackExample(
        impact_id=row.impact_id,
        category=row.category,
        reason_tags=row.reason_tags,
        affected_text=row.affected_text,
        chosen=row.chosen,
        rejected=row.rejected,
        rationale=_rationale(row),
    )


def _has_ai_text(row) -> bool:
    return row.draft_status not in ("failed", "skipped")


def split_examples(rows: list, task: str) -> tuple[list, list]:
    """Split feedback rows (expected newest-first) into (positive, negative) for one step.

    Pure over the rows, so both the few-shot endpoint and the DPO readiness status can share one
    `list_feedback` read instead of querying twice.
    """
    if task not in TASKS:
        raise ValueError(f"Unknown task {task!r}; expected one of {TASKS}")

    positive, negative = [], []
    for row in rows:
        if task == "draft":
            # Only rows that carry both an AI draft and a human verdict on its text.
            if not _has_ai_text(row):
                continue
            if row.action in ("accept", "edit") and row.chosen:
                positive.append(row)
            if row.action == "edit" and row.rejected:
                negative.append(row)
        else:
            if row.action in ("accept", "edit"):
                positive.append(row)
            elif row.action == "reject":
                negative.append(row)
    return positive, negative


def example_set(
    session: Session,
    task: str,
    limit: int = DEFAULT_LIMIT,
    vbpl_id: str | None = None,
    since: datetime | None = None,
) -> ExampleSet:
    """Positive and negative examples for one step, newest decision first.

    Newest first because this feeds a dynamic few-shot prompt: the point of the loop is that the
    latest corrections reach the model, not the first ones ever made.
    """
    if task not in TASKS:
        raise ValueError(f"Unknown task {task!r}; expected one of {TASKS}")

    rows = list(reversed(list_feedback(session, since=since, vbpl_id=vbpl_id)))
    positive, negative = split_examples(rows, task)

    return ExampleSet(
        task=task,
        positive=[_example(r) for r in positive[:limit]],
        negative=[_example(r) for r in negative[:limit]],
        counts={
            "decisions_read": len(rows),
            "positive_available": len(positive),
            "negative_available": len(negative),
        },
    )


def preference_rows(
    session: Session, vbpl_id: str | None = None, since: datetime | None = None
) -> list[FeedbackExample]:
    """Decisions that contrast two texts, i.e. the ones a preference pair can be built from.

    `accept` never qualifies: the reviewer took the AI text, so there is no rejected alternative.
    """
    rows = list_feedback(session, since=since, vbpl_id=vbpl_id)
    return [_example(r) for r in rows if r.chosen and r.rejected]
