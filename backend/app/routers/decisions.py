"""Reviewer decisions on impacts (accept / edit / reject / undo) and the audit trail."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import joinedload

from app import hitl
from app.db import SessionDep
from app.models import hitl as models
from app.models import hitl_schemas as schemas

router = APIRouter(tags=["decisions"])


@router.post("/decisions", status_code=status.HTTP_201_CREATED)
def decide(body: schemas.DecisionCreate, session: SessionDep) -> schemas.DecisionOut:
    """Append a decision; the newest one that is not undone is the impact's decision."""
    impact = session.get(models.Impact, body.impact_id)
    if impact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Impact not found")
    if body.action == "accept" and impact.draft_status in ("failed", "skipped"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "No AI proposal to accept: edit or reject"
        )
    if session.get(models.Reviewer, body.reviewer_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reviewer not found")
    decision = models.Decision(**body.model_dump())
    session.add(decision)
    session.commit()
    session.refresh(decision)
    return hitl.decision_out(decision)


@router.delete("/decisions/{decision_id}", status_code=status.HTTP_204_NO_CONTENT)
def undo_decision(decision_id: str, session: SessionDep) -> Response:
    """Mark a decision undone. The row stays for the audit / feedback data."""
    decision = session.get(models.Decision, decision_id)
    if decision is None or decision.undone_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active decision with this id")
    decision.undone_at = datetime.now(UTC)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/audit")
def list_audit_trail(session: SessionDep) -> list[schemas.AuditEntryOut]:
    """Decisions that are not undone, newest first, with what the reviewer saw."""
    decisions = session.scalars(
        select(models.Decision)
        .where(models.Decision.undone_at.is_(None))
        .options(joinedload(models.Decision.impact).joinedload(models.Impact.vbpl))
        .order_by(models.Decision.at.desc())
    ).all()
    return [
        schemas.AuditEntryOut(
            **hitl.decision_out(d).model_dump(),
            vbpl_number=d.impact.vbpl.number,
            # No documents table yet (MINH-01 / HUY-02); the UI falls back to the id too.
            document_code=d.impact.document_id,
            location=d.impact.location,
            original_text=d.impact.affected_text,
            suggested_text=d.impact.suggested_text,
            finding_id=d.impact.finding_id,
            category=d.impact.category,
        )
        for d in decisions
    ]


def to_labels(
    action: str, affected: str, suggested: str, edited: str | None, has_ai_text: bool
) -> tuple[str | None, str | None]:
    """(chosen, rejected) per docs/evaluation-data-contract.md. A failed or skipped draft has no
    AI text, so nothing is `rejected` and an accept chose nothing."""
    ai_text = suggested if has_ai_text else None
    if action == "edit":
        return edited, ai_text
    if action == "reject":
        return affected, ai_text
    return ai_text, None


@router.get("/feedback")
def list_feedback(
    session: SessionDep,
    since: datetime | None = None,
    vbpl_id: Annotated[str | None, Query(alias="vbplId")] = None,
) -> list[schemas.FeedbackRow]:
    """The active decision of every decided impact. Undone decisions stay only in the audit."""
    query = (
        select(models.Decision, models.Impact)
        .join(models.Impact)
        .where(
            models.Decision.undone_at.is_(None),
            # Rows made from a raw RIA finding by an earlier decide() carry the regulation's own
            # text as suggested_text and no model output: not AI proposals, so not labels.
            text("impacts.model_output <> '{}'::jsonb"),
        )
        .order_by(models.Decision.impact_id, models.Decision.at.desc())
        .ext(distinct_on(models.Decision.impact_id))
    )
    if since is not None:
        query = query.where(models.Decision.at >= since)
    if vbpl_id is not None:
        query = query.where(models.Impact.vbpl_id == vbpl_id)
    rows = []
    for decision, impact in session.execute(query):
        chosen, rejected = to_labels(
            decision.action,
            impact.affected_text,
            impact.suggested_text,
            decision.edited_text,
            has_ai_text=impact.draft_status not in ("failed", "skipped"),
        )
        rows.append(
            schemas.FeedbackRow(
                impact_id=impact.id,
                vbpl_id=impact.vbpl_id,
                finding_id=impact.finding_id,
                category=impact.category,
                action=decision.action,
                reason_tags=decision.reason_tags,
                reviewer_id=decision.reviewer_id,
                decided_at=decision.at,
                affected_text=impact.affected_text,
                suggested_text=impact.suggested_text,
                edited_text=decision.edited_text,
                patch=impact.patch,
                draft_status=impact.draft_status,
                model_output=impact.model_output,
                chosen=chosen,
                rejected=rejected,
            )
        )
    return sorted(rows, key=lambda r: r.decided_at)


@router.get("/reviewers")
def list_reviewers(session: SessionDep) -> list[schemas.ReviewerOut]:
    reviewers = session.scalars(select(models.Reviewer).order_by(models.Reviewer.id))
    return [schemas.ReviewerOut.model_validate(r) for r in reviewers]
