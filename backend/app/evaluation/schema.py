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

ChangeKind = Literal["added", "amended", "repealed"]
ImpactType = Literal["conflict", "outdated_reference", "new_obligation"]
Severity = Literal["high", "medium", "low"]

# The RIA path (engine A, PLAN.md 2026-10-18) labels work on obligations, not on extracted changes.
RiaCategory = Literal[
    "VALUE_CHANGE",
    "CONTRADICTION",
    "SCOPE_CHANGE",
    "ADDITION",
    "INDIRECT_IMPACT",
    "EQUIVALENT",
]
PatchOperation = Literal["REPLACE", "INSERT", "DELETE"]


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


# --- RIA path (engine A) ------------------------------------------------------------------------
# The shapes above model the older `/invoke` path and stay until it is retired. Below is the same
# idea for the RIA path: the unit is an obligation rather than an extracted change, and clauses are
# keyed by `clause_id` (`DOC-102@v4#5.2`) instead of a free-text article path.


class ReferencePatch(BaseModel):
    """The edit a correct amendment would make, for the LLM judge to compare against."""

    operation: PatchOperation
    old_text: str = ""
    new_text: str = ""


class ExpectedObligation(BaseModel):
    """One atomic duty the regulation imposes, as RIA's `obligation` table models it."""

    clause_id: str = Field(description='In the regulation, e.g. "REG-99-2026-TT-NHNN@v1#2.1".')
    text: str
    modality: Literal["must", "must_not", "may"]


class ExpectedFinding(BaseModel):
    """One obligation judged against one internal clause.

    `category == "EQUIVALENT"` means the internal clause already satisfies the obligation, so the
    pipeline must **not** report it. Those rows are the only way to measure false positives: a
    dataset of conflicts alone makes Precision look perfect no matter how the pipeline behaves.
    """

    obligation_clause_id: str
    internal_clause_id: str
    category: RiaCategory
    priority: Severity
    # Substring of the internal clause the edit should land on; `None` when the clause only anchors
    # an insertion.
    target_span_text: str | None = None
    reference_patch: ReferencePatch | None = None


class RiaDatasetItem(BaseModel):
    """Ground truth for one regulation on the RIA path."""

    item_id: str
    regulation_number: str
    # File name of the regulation PDF the generator writes next to this dataset. The PDF is
    # regenerated rather than committed (AGENTS.md: raw files stay out of git).
    regulation_pdf: str
    obligations: list[ExpectedObligation] = Field(default_factory=list)
    findings: list[ExpectedFinding] = Field(default_factory=list)

    @property
    def expected_findings(self) -> list[ExpectedFinding]:
        """Findings the pipeline should report: everything that is not already satisfied."""
        return [f for f in self.findings if f.category != "EQUIVALENT"]


def load_ria_dataset(path: Path) -> list[RiaDatasetItem]:
    """Read a RIA ground-truth dataset. The file is a JSON object with an `items` array."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [RiaDatasetItem.model_validate(item) for item in raw["items"]]
