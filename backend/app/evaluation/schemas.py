"""Wire shapes for the evaluation API.

These mirror `EvalMetrics` and `EvalRun` in `frontend/src/api/types.ts` field for field: the
dashboard reads every leaf unconditionally, so a missing group is a crash, not a blank cell.
`CamelModel` is reused from the HITL schemas so the whole API keeps one wire convention.
"""

from datetime import datetime

from pydantic import Field

from app.models.hitl_schemas import CamelModel


class ExtractionMetrics(CamelModel):
    precision: float
    recall: float


class RetrievalMetrics(CamelModel):
    recall_at_k: float
    # The dashboard hardcodes the label "Recall@5" and never renders this, so sending anything but
    # 5 would make the screen lie.
    k: int = 5
    mrr: float


class ImpactMetrics(CamelModel):
    precision: float
    recall: float
    f1: float


class AmendmentMetrics(CamelModel):
    judge_score: float
    hitl_accept_rate: float


class SystemMetrics(CamelModel):
    latency_seconds: float
    cost_usd_per_document: float


class EvalMetricsOut(CamelModel):
    extraction: ExtractionMetrics
    retrieval: RetrievalMetrics
    impact: ImpactMetrics
    amendment: AmendmentMetrics
    system: SystemMetrics


class EvalRunCreate(CamelModel):
    label: str = Field(min_length=1)
    dataset_size: int = Field(ge=0)
    note: str = ""
    metrics: EvalMetricsOut
    # Settings behind these numbers, e.g. {"maxChanges": 10, "retrieveK": 5, "llmModel": "..."}.
    params: dict = Field(default_factory=dict)


class EvalRunOut(CamelModel):
    id: str
    label: str
    created_at: datetime
    dataset_size: int
    note: str
    metrics: EvalMetricsOut
    # Not declared in types.ts: the dashboard ignores it, but anyone reading the API needs to see
    # which settings produced a run before comparing two of them.
    params: dict
