"""Data shapes for the evaluation pipeline (KHOA-01).

PROPOSED, not agreed yet: "Luồng dữ liệu Evaluate + enrich test set" is still `_chưa chốt_` in
PLAN.md. Per AGENTS.md these models are the named adapter boundary -- the runner that drives the
agent converts whatever the agent returns into a `PipelineOutput`, so agreeing a different wire
format later changes that converter, not the metrics.

`ImpactType` and `Severity` mirror `frontend/src/api/types.ts` so ground truth, the agent and the
dashboard share one taxonomy. `ChangeKind` mirrors the three cases `extract_changes` must produce
per PLAN.md TAI-01 (điều khoản mới / sửa đổi / bãi bỏ).
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ChangeKind = Literal["new", "amended", "repealed"]
ImpactType = Literal["conflict", "outdated_reference", "new_obligation"]
Severity = Literal["high", "medium", "low"]


class ExpectedChange(BaseModel):
    """A clause the new VBPL adds, amends or repeals."""

    article_path: str = Field(description='As written in the VBPL, e.g. "Điều 3 khoản 1".')
    kind: ChangeKind


class ExpectedImpact(BaseModel):
    """An internal-document chunk a change is expected to affect."""

    change_path: str = Field(description="article_path of the change that causes this impact.")
    document_id: str
    chunk_id: str
    type: ImpactType
    severity: Severity
    # Gold rewritten text. Only the LLM-as-judge step reads this, which is not built yet
    # (needs the Phase 1 LLM endpoint, TAI-06).
    reference_amendment: str | None = None


class DatasetItem(BaseModel):
    """Ground truth for one VBPL: every change in it and every impact it should cause.

    Produced by TAI-03, which plants the conflicts deliberately and records them.
    """

    item_id: str
    vbpl_id: str
    changes: list[ExpectedChange] = Field(default_factory=list)
    impacts: list[ExpectedImpact] = Field(default_factory=list)


class PredictedChange(BaseModel):
    article_path: str
    kind: ChangeKind


class PredictedRetrieval(BaseModel):
    """Chunks the retriever returned for one change, best first."""

    change_path: str
    chunk_ids: list[str] = Field(default_factory=list)


class PredictedImpact(BaseModel):
    change_path: str
    document_id: str
    chunk_id: str
    type: ImpactType
    severity: Severity
    suggested_text: str | None = None


class PipelineOutput(BaseModel):
    """What one agent run produced for one dataset item.

    `latency_seconds` and `cost_usd` are optional because nothing measures them yet: the agent's
    `/invoke` returns neither. They stay `None` rather than 0 so an unmeasured run is visibly
    unmeasured.
    """

    item_id: str
    changes: list[PredictedChange] = Field(default_factory=list)
    retrieval: list[PredictedRetrieval] = Field(default_factory=list)
    impacts: list[PredictedImpact] = Field(default_factory=list)
    latency_seconds: float | None = None
    cost_usd: float | None = None


def load_dataset(path: Path) -> list[DatasetItem]:
    """Read a ground-truth dataset from a JSON array of `DatasetItem` objects."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [DatasetItem.model_validate(item) for item in raw]
