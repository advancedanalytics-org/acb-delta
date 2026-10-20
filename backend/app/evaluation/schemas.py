"""Wire shapes for the evaluation API.

These mirror `EvalMetrics` and `EvalRun` in `frontend/src/api/types.ts` field for field: the
dashboard reads every leaf unconditionally, so a missing group is a crash, not a blank cell.
`CamelModel` is reused from the HITL schemas so the whole API keeps one wire convention.
"""

from datetime import datetime
from typing import Literal

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
    # `None` means not measured, which is not zero: the judge needs an LLM, and the accept rate
    # needs someone to have reviewed that run. A 0 here would read as "measured and bad".
    judge_score: float | None = None
    hitl_accept_rate: float | None = None


class SystemMetrics(CamelModel):
    latency_seconds: float
    # No token accounting on the RIA path yet (app/ria/llm.py calls the endpoint directly and
    # job.result records llm_calls but no usage), so this stays unmeasured rather than guessed.
    cost_usd_per_document: float | None = None


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
    # When the run actually happened. Scoring is a second pass over a finished job (the accept rate
    # only exists once people have reviewed it), so the insert time is not the run time, and the
    # dashboard orders runs by this.
    created_at: datetime | None = None
    metrics: EvalMetricsOut
    # Settings behind these numbers, e.g. {"maxChanges": 10, "retrieveK": 5, "llmModel": "..."}.
    params: dict = Field(default_factory=dict)


class FeedbackExample(CamelModel):
    """One reviewer decision, shaped as a few-shot example (KHOA-02)."""

    impact_id: str
    category: str | None
    reason_tags: list[str]
    affected_text: str
    # The text the reviewer wants, and the AI text they did not take. Either can be null: an
    # accept has nothing rejected, and a failed draft has no AI text at all.
    chosen: str | None
    rejected: str | None
    # Why RIA raised the finding. A negative judge example is only useful with this.
    rationale: str | None


class ExampleSet(CamelModel):
    task: Literal["draft", "judge"]
    positive: list[FeedbackExample]
    negative: list[FeedbackExample]
    # How many decisions were read and how many qualified, so a thin prompt is visibly thin
    # rather than looking like there was no feedback.
    counts: dict[str, int]


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
