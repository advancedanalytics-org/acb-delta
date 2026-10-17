"""Typed shapes for every LLM output and for the agent's response. Backend copies `ImpactOut`."""

from typing import Literal

from pydantic import BaseModel, Field

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
