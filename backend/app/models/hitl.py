"""HITL tables. Decisions are append-only: undo sets `undone_at`, nothing is overwritten.

An impact's status is derived from its latest decision that is not undone, never stored.
Tables come from `create_all` at startup (new tables only); move to Alembic before data migrates.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid.uuid4())


class HitlBase(DeclarativeBase):
    """Separate from the documents `Base`: these tables need no pgvector, so the test DB doesn't."""


class Vbpl(HitlBase):
    __tablename__ = "vbpls"
    # Named like the startup ALTER in `app.hitl` so an existing DB gets the same index.
    __table_args__ = (Index("vbpls_ria_job_id", "ria_job_id", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    issuer: Mapped[str] = mapped_column(Text)
    issued_date: Mapped[date] = mapped_column(Date)
    effective_date: Mapped[date] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    # processing → awaiting_review once the agent finished (shown as done when nothing is pending),
    # or failed with `error`.
    status: Mapped[str] = mapped_column(String(32), default="processing")
    error: Mapped[str | None] = mapped_column(Text)
    # RIA analyze job this review package was built from; null for VBPLs posted to /api/vbpls.
    ria_job_id: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Impact(HitlBase):
    """One affected internal passage, copied from the agent output as the reviewer saw it."""

    __tablename__ = "impacts"
    __table_args__ = (Index("impacts_finding_id", "finding_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    vbpl_id: Mapped[str] = mapped_column(ForeignKey("vbpls.id", ondelete="CASCADE"), index=True)
    # Index in the agent's output (change order, then retrieval rank); impacts list in this order.
    position: Mapped[int] = mapped_column(Integer)
    document_id: Mapped[str] = mapped_column(Text)
    chunk_id: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text)
    change_clause: Mapped[str] = mapped_column(Text)
    citation: Mapped[str] = mapped_column(Text)
    affected_text: Mapped[str] = mapped_column(Text)
    # Null / empty until PDF ingestion (HUY-02) gives chunks a page and boxes.
    page: Mapped[int | None] = mapped_column(Integer)
    bboxes: Mapped[list] = mapped_column(JSONB, default=list)
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    reasoning: Mapped[str] = mapped_column(Text)
    suggested_text: Mapped[str] = mapped_column(Text)
    # Raw agent output for this impact, for evaluation (KHOA-01 / KHOA-02).
    model_output: Mapped[dict] = mapped_column(JSONB)
    # RIA review packages only (docs/amendment-review-contract.md); null on /invoke rows.
    finding_id: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    # {operation, start, end, old_text, new_text}: the before/after data for the redline view.
    patch: Mapped[dict | None] = mapped_column(JSONB)
    draft_status: Mapped[str | None] = mapped_column(String(16))
    draft_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vbpl: Mapped[Vbpl] = relationship()


class Reviewer(HitlBase):
    __tablename__ = "reviewers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)


class Decision(HitlBase):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    impact_id: Mapped[str] = mapped_column(ForeignKey("impacts.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(16))
    edited_text: Mapped[str | None] = mapped_column(Text)
    reason_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("reviewers.id"))
    # clock_timestamp, not now(): "latest decision wins" needs a real order, even inside one
    # transaction.
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    impact: Mapped[Impact] = relationship()
    reviewer: Mapped[Reviewer] = relationship(lazy="joined")


# Mock reviewers until auth exists; same ids as the UI's mock fixtures.
# Department heads ("Trưởng phòng …") may delete regulations; specialists may not.
DELETE_ROLE_PREFIX = "Trưởng phòng"


def can_delete(role: str) -> bool:
    return role.startswith(DELETE_ROLE_PREFIX)


SEED_REVIEWERS = [
    {"id": "rv-anh", "name": "Nguyễn Minh Anh", "role": "Chuyên viên pháp chế"},
    {"id": "rv-bao", "name": "Trần Quốc Bảo", "role": "Trưởng phòng tuân thủ"},
]
