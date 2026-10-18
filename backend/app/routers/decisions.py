"""Reviewer decisions on impacts (accept / edit / reject / undo) and the audit trail."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import hitl
from app.db import SessionDep
from app.models import hitl as models
from app.models import hitl_schemas as schemas

router = APIRouter(tags=["decisions"])


@router.post("/decisions", status_code=status.HTTP_201_CREATED)
def decide(body: schemas.DecisionCreate, session: SessionDep) -> schemas.DecisionOut:
    """Append a decision; the newest one that is not undone is the impact's decision."""
    if session.get(models.Impact, body.impact_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Impact not found")
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
        )
        for d in decisions
    ]


@router.get("/reviewers")
def list_reviewers(session: SessionDep) -> list[schemas.ReviewerOut]:
    reviewers = session.scalars(select(models.Reviewer).order_by(models.Reviewer.id))
    return [schemas.ReviewerOut.model_validate(r) for r in reviewers]
