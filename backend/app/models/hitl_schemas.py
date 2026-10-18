"""Wire shapes. Field names follow `frontend/src/api/types.ts` (camelCase on the wire)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

DecisionAction = Literal["accept", "edit", "reject"]
VbplStatus = Literal["processing", "awaiting_review", "done", "failed", "not_found"]
ImpactStatus = Literal["pending", "accepted", "rejected"]


def _omit_none(value: object) -> bool:
    return value is None


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class VbplCreate(CamelModel):
    number: str
    title: str
    issuer: str
    issued_date: date
    effective_date: date
    summary: str
    text: str = Field(min_length=1)


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
