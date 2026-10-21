"""Wire shapes. Field names follow `frontend/src/api/types.ts` (camelCase on the wire)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from pydantic.alias_generators import to_camel

from app.models.hitl import can_delete

DecisionAction = Literal["accept", "edit", "reject"]
VbplStatus = Literal["processing", "awaiting_review", "done", "failed", "not_found"]
ImpactStatus = Literal["pending", "accepted", "rejected"]


def _omit_none(value: object) -> bool:
    return value is None


# Longest VBPL text the agent is asked to analyse (a long circular is ~150k characters).
MAX_VBPL_TEXT_CHARS = 300_000


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class VbplCreate(CamelModel):
    number: str
    title: str
    issuer: str
    issued_date: date
    effective_date: date
    summary: str
    text: str = Field(min_length=1, max_length=MAX_VBPL_TEXT_CHARS)


class VbplOut(CamelModel):
    id: str
    number: str
    title: str
    issuer: str
    issued_date: date
    effective_date: date
    received_at: datetime
    summary: str
    status: VbplStatus
    error: str | None = Field(default=None, exclude_if=_omit_none)
    impact_count: int
    pending_count: int


class ReviewerOut(CamelModel):
    id: str
    name: str
    role: str

    @computed_field(alias="canDelete")
    @property
    def can_delete(self) -> bool:
        """Whether this reviewer may delete a regulation (department heads only)."""
        return can_delete(self.role)


class DecisionOut(CamelModel):
    id: str
    impact_id: str
    vbpl_id: str
    document_id: str
    action: DecisionAction
    edited_text: str | None = Field(default=None, exclude_if=_omit_none)
    reason_tags: list[str]
    reviewer: ReviewerOut
    at: datetime


class AuditEntryOut(DecisionOut):
    vbpl_number: str
    document_code: str
    location: str
    original_text: str
    suggested_text: str
    # RIA review packages only.
    finding_id: str | None = Field(default=None, exclude_if=_omit_none)
    category: str | None = Field(default=None, exclude_if=_omit_none)


class PatchOut(CamelModel):
    """Before/after on the exact span of `affectedText`: replace [start, end) with newText."""

    operation: Literal["REPLACE", "INSERT", "DELETE"]
    start: int
    end: int
    old_text: str
    new_text: str


class ImpactOut(CamelModel):
    id: str
    vbpl_id: str
    document_id: str
    location: str
    change_clause: str
    citation: str
    affected_text: str
    page: int | None
    bboxes: list[list[float]]
    type: str
    severity: str
    reasoning: str
    suggested_text: str
    # RIA review packages only; left out of the JSON for impacts from /invoke.
    finding_id: str | None = Field(default=None, exclude_if=_omit_none)
    category: str | None = Field(default=None, exclude_if=_omit_none)
    patch: PatchOut | None = Field(default=None, exclude_if=_omit_none)
    draft_status: str | None = Field(default=None, exclude_if=_omit_none)
    draft_error: str | None = Field(default=None, exclude_if=_omit_none)
    status: ImpactStatus
    final_text: str | None = Field(default=None, exclude_if=_omit_none)
    decision: DecisionOut | None = Field(default=None, exclude_if=_omit_none)


class DecisionCreate(CamelModel):
    impact_id: str
    action: DecisionAction
    edited_text: str | None = None
    reason_tags: list[str] = []
    reviewer_id: str

    @model_validator(mode="after")
    def edit_needs_text(self) -> "DecisionCreate":
        if self.action == "edit" and not (self.edited_text and self.edited_text.strip()):
            raise ValueError("editedText is required for an edit")
        if self.action != "edit":
            self.edited_text = None
        return self


class VbplClauseGroup(CamelModel):
    """One impact's cited VBPL clauses, grouped by their article (Điều) for the review popup."""

    article_numbering: str
    article_title: str | None
    clauses: list[str]


class FeedbackRow(CamelModel):
    """One decided impact as a label for KHOA-02 (docs/amendment-review-contract.md §4)."""

    impact_id: str
    vbpl_id: str
    finding_id: str | None
    category: str | None
    action: DecisionAction
    reason_tags: list[str]
    reviewer_id: str
    decided_at: datetime
    affected_text: str
    suggested_text: str
    edited_text: str | None
    patch: PatchOut | None
    draft_status: str | None
    model_output: dict
    # Preference pair: what the human wants vs. the AI text they did not take (null if none).
    chosen: str | None
    rejected: str | None
