"""Typed shapes for every LLM output and for the agent's response. Backend copies `ImpactOut`."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ChangeKind = Literal["added", "amended", "repealed"]
ImpactType = Literal["conflict", "outdated_reference", "new_obligation"]
Severity = Literal["high", "medium", "low"]


class Change(BaseModel):
    clause: str = Field(description="Vị trí trong VBPL mới, ví dụ 'Khoản 2 Điều 9'")
    kind: ChangeKind = Field(description="added: quy định mới; amended: sửa đổi; repealed: bãi bỏ")
    text: str = Field(description="Nội dung quy định, trích nguyên văn hoặc tóm tắt sát nghĩa")


class ChangeList(BaseModel):
    changes: list[Change]


class Candidate(BaseModel):
    """An internal-document passage that may be affected by a change (retriever output)."""

    chunk_id: str
    doc_id: str
    location: str
    # Null / empty until PDF ingestion (HUY-02) provides page and box coordinates.
    page: int | None = None
    bboxes: list[list[float]] = []
    text: str


class ImpactJudgement(BaseModel):
    affected: bool = Field(description="true nếu đoạn văn bản nội bộ phải sửa vì thay đổi này")
    type: ImpactType = Field(
        description="conflict: mâu thuẫn; outdated_reference: dẫn chiếu văn bản cũ; "
        "new_obligation: phát sinh nghĩa vụ mới chưa có"
    )
    severity: Severity
    reasoning: str = Field(description="Giải thích ngắn gọn bằng tiếng Việt")
    citation: str = Field(description="Điều / khoản của VBPL mới làm căn cứ")


class Amendment(BaseModel):
    suggested_text: str = Field(description="Toàn bộ đoạn văn bản nội bộ sau khi sửa")


class ImpactOut(BaseModel):
    """One affected passage with the suggested edit, as returned by POST /invoke."""

    chunk_id: str
    doc_id: str
    location: str
    page: int | None
    bboxes: list[list[float]]
    affected_text: str
    change_clause: str
    type: ImpactType
    severity: Severity
    reasoning: str
    citation: str
    suggested_text: str


# --- POST /draft: one RIA finding in, one minimal verified patch out (AmendmentProposal v1). ---

PatchOperation = Literal["REPLACE", "INSERT", "DELETE"]
CheckStatus = Literal["pass", "fail", "warn", "skipped"]


class Span(BaseModel):
    text: str
    start: int
    end: int


class DraftObligation(BaseModel):
    clause_id: str
    text: str


class DraftClause(BaseModel):
    clause_id: str
    numbering: str
    text: str


class RelatedFinding(BaseModel):
    """Another finding on the same internal clause: the one patch must satisfy it too."""

    finding_id: str
    category: str
    rationale: str
    obligation: DraftObligation


class DraftRequest(BaseModel):
    finding_id: str
    category: str
    rationale: str
    obligation: DraftObligation
    source_span: Span | None = None
    clause: DraftClause
    # Offsets into `clause.text`: the part RIA found in conflict. Null when RIA had no span.
    target_span: Span | None = None
    citations: list[str] = []
    # Other findings on `clause`; empty when only one obligation affects it.
    related_findings: list[RelatedFinding] = []

    @model_validator(mode="after")
    def target_span_matches_clause(self) -> "DraftRequest":
        span, text = self.target_span, self.clause.text
        if span is not None and not (
            0 <= span.start <= span.end <= len(text) and text[span.start : span.end] == span.text
        ):
            raise ValueError("target_span must be clause.text[start:end]")
        return self


class PatchDraft(BaseModel):
    operation: PatchOperation = Field(
        description="REPLACE: thay old_text bằng new_text; INSERT: thêm new_text; "
        "DELETE: xoá old_text"
    )
    old_text: str = Field(
        description="Đoạn chép nguyên văn từ điều khoản nội bộ, ngắn nhất có thể; "
        "để trống khi INSERT"
    )
    new_text: str = Field(description="Nội dung mới; để trống khi DELETE")
    rationale: str = Field(description="Lý do sửa, ngắn gọn bằng tiếng Việt")


class Verdict(BaseModel):
    satisfies_obligation: bool = Field(description="Điều khoản sau khi sửa đáp ứng nghĩa vụ mới")
    preserves_other_content: bool = Field(description="Các nội dung không liên quan giữ nguyên")
    adds_no_exception: bool = Field(
        description="Không thêm ngoại lệ, điều kiện hay nghĩa vụ mà VBPL không yêu cầu"
    )
    comment: str = Field(description="Nhận xét ngắn bằng tiếng Việt")


class Check(BaseModel):
    check: str
    status: CheckStatus
    detail: str | None = None


class Verification(BaseModel):
    # Never "approved": a human decides. failed = no usable patch, see `reason`.
    status: Literal["review_required", "failed"]
    reason: str | None = None
    checks: list[Check]


class AmendmentProposal(BaseModel):
    finding_id: str
    clause_id: str
    operation: PatchOperation | None
    # Offsets into the request's clause text; old_text == clause_text[start:end]. Null when failed.
    start: int | None
    end: int | None
    old_text: str | None
    new_text: str | None
    rationale: str
    legal_evidence_ids: list[str]
    verification: Verification
    model: str
    prompt_version: str
