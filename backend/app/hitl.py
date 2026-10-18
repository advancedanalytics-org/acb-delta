"""Derived HITL state: an impact's decision is its latest decision that is not undone."""

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.db import get_engine, get_sessionmaker
from app.models import hitl as models
from app.models import hitl_schemas as schemas


def init_tables() -> None:
    """Create missing HITL tables and seed the mock reviewers. Safe to run on every start."""
    models.HitlBase.metadata.create_all(get_engine())
    with get_sessionmaker()() as session:
        for reviewer in models.SEED_REVIEWERS:
            session.merge(models.Reviewer(**reviewer))
        session.commit()


STATUS_BY_ACTION = {"accept": "accepted", "edit": "accepted", "reject": "rejected"}


def has_active_decision():
    """SQL condition: the impact (correlated `models.Impact`) has a decision that is not undone."""
    return exists().where(
        models.Decision.impact_id == models.Impact.id, models.Decision.undone_at.is_(None)
    )


def vbpl_rows(session: Session, vbpl_id: str | None = None) -> list[schemas.VbplOut]:
    """VBPLs newest first, with impact and pending counts computed in the query."""
    impact_count = (
        select(func.count())
        .where(models.Impact.vbpl_id == models.Vbpl.id)
        .correlate(models.Vbpl)
        .scalar_subquery()
    )
    pending_count = (
        select(func.count())
        .where(models.Impact.vbpl_id == models.Vbpl.id, ~has_active_decision())
        .correlate(models.Vbpl)
        .scalar_subquery()
    )
    query = select(models.Vbpl, impact_count, pending_count).order_by(
        models.Vbpl.received_at.desc(), models.Vbpl.id
    )
    if vbpl_id is not None:
        query = query.where(models.Vbpl.id == vbpl_id)
    out = []
    for vbpl, impacts, pending in session.execute(query):
        status = vbpl.status
        if status == "awaiting_review" and pending == 0:
            status = "done"
        out.append(
            schemas.VbplOut.model_validate(
                {
                    **{c: getattr(vbpl, c) for c in schemas.VbplCreate.model_fields if c != "text"},
                    "id": vbpl.id,
                    "received_at": vbpl.received_at,
                    "status": status,
                    "error": vbpl.error,
                    "impact_count": impacts,
                    "pending_count": pending,
                }
            )
        )
    return out


def decision_out(decision: models.Decision) -> schemas.DecisionOut:
    impact = decision.impact
    return schemas.DecisionOut(
        id=decision.id,
        impact_id=impact.id,
        vbpl_id=impact.vbpl_id,
        document_id=impact.document_id,
        action=decision.action,
        edited_text=decision.edited_text,
        reason_tags=decision.reason_tags,
        reviewer=schemas.ReviewerOut.model_validate(decision.reviewer),
        at=decision.at,
    )


def impact_rows(session: Session, vbpl_id: str) -> list[schemas.ImpactOut]:
    impacts = session.scalars(
        select(models.Impact)
        .where(models.Impact.vbpl_id == vbpl_id)
        .order_by(models.Impact.position)
    ).all()
    # Latest active decision per impact: DISTINCT ON keeps the first row of each impact_id.
    latest = {
        d.impact_id: d
        for d in session.scalars(
            select(models.Decision)
            .join(models.Impact)
            .where(models.Impact.vbpl_id == vbpl_id, models.Decision.undone_at.is_(None))
            .order_by(models.Decision.impact_id, models.Decision.at.desc())
            .ext(distinct_on(models.Decision.impact_id))
        )
    }
    out = []
    for impact in impacts:
        decision = latest.get(impact.id)
        final_text = None
        if decision is not None:
            final_text = {"accept": impact.suggested_text, "edit": decision.edited_text}.get(
                decision.action
            )
        out.append(
            schemas.ImpactOut(
                id=impact.id,
                vbpl_id=impact.vbpl_id,
                document_id=impact.document_id,
                location=impact.location,
                change_clause=impact.change_clause,
                citation=impact.citation,
                affected_text=impact.affected_text,
                page=impact.page,
                bboxes=impact.bboxes,
                type=impact.type,
                severity=impact.severity,
                reasoning=impact.reasoning,
                suggested_text=impact.suggested_text,
                status=STATUS_BY_ACTION[decision.action] if decision else "pending",
                final_text=final_text,
                decision=decision_out(decision) if decision else None,
            )
        )
    return out
