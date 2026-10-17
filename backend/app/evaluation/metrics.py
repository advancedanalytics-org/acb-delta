"""Step metrics for the evaluation pipeline (KHOA-01).

Pure functions over (expected, predicted) pairs: nothing here calls the agent, an LLM or the
database, so a score can be reproduced and reviewed on its own.

Coverage against `EvalMetrics` in `frontend/src/api/types.ts`:

* `extraction`, `retrieval`, `impact`, `system` -- computed here.
* `amendment` (LLM-judge score, HITL accept rate) -- **not** computed. The judge needs the Phase 1
  LLM endpoint (TAI-06, `_chưa chốt_`) and the accept rate needs the HITL decision table (TAI-02).
  Both are absent rather than filled with zeros, because a zero would read as a measured failure.

Aggregation: precision and recall are micro-averaged across dataset items (sum the true positives,
divide once), so an item carrying ten impacts weighs ten times an item carrying one. Recall@k and
MRR are macro-averaged over changes, the usual IR convention.
"""

from collections.abc import Sequence
from statistics import fmean

from pydantic import BaseModel

from app.evaluation.matching import impact_key, normalize_article_path
from app.evaluation.schema import DatasetItem, PipelineOutput

# The dashboard hardcodes the label "Recall@5" in
# frontend/src/features/evaluation/evaluation-page.tsx, so k stays 5 until that label is dynamic.
DEFAULT_K = 5


class ItemOutcome(BaseModel):
    """One dataset item together with what the pipeline produced for it."""

    expected: DatasetItem
    predicted: PipelineOutput


class PrecisionRecall(BaseModel):
    """Counts are kept alongside the ratios so a reviewer can recompute them by hand."""

    precision: float
    recall: float
    f1: float
    true_positives: int
    predicted: int
    expected: int


class RetrievalScores(BaseModel):
    recall_at_k: float
    k: int
    mrr: float
    changes_scored: int


class ImpactScores(BaseModel):
    detection: PrecisionRecall
    # Share of correctly detected impacts that also carry the right label. `None` when nothing
    # matched, since an accuracy over zero items is not 0.0, it is unknown.
    type_accuracy: float | None
    severity_accuracy: float | None
    matched: int


class SystemScores(BaseModel):
    latency_seconds: float | None
    cost_usd_per_document: float | None


class StageScores(BaseModel):
    dataset_size: int
    extraction: PrecisionRecall
    retrieval: RetrievalScores
    impact: ImpactScores
    system: SystemScores


def _precision_recall(true_positives: int, predicted: int, expected: int) -> PrecisionRecall:
    precision = true_positives / predicted if predicted else 0.0
    recall = true_positives / expected if expected else 0.0
    denominator = precision + recall
    return PrecisionRecall(
        precision=precision,
        recall=recall,
        f1=2 * precision * recall / denominator if denominator else 0.0,
        true_positives=true_positives,
        predicted=predicted,
        expected=expected,
    )


def pair_items(
    dataset: Sequence[DatasetItem], outputs: Sequence[PipelineOutput]
) -> list[ItemOutcome]:
    """Line up each dataset item with its pipeline output, keeping the dataset order."""
    by_id = {output.item_id: output for output in outputs}
    missing = [item.item_id for item in dataset if item.item_id not in by_id]
    if missing:
        raise ValueError("No pipeline output for dataset items: " + ", ".join(missing))
    return [ItemOutcome(expected=item, predicted=by_id[item.item_id]) for item in dataset]


def extraction_scores(outcomes: Sequence[ItemOutcome]) -> PrecisionRecall:
    """How well `extract_changes` finds the clauses the VBPL actually changed.

    Clause paths are compared as sets, so a pipeline that reports the same clause twice is neither
    rewarded nor punished for the repeat.
    """
    true_positives = predicted = expected = 0
    for outcome in outcomes:
        want = {normalize_article_path(c.article_path) for c in outcome.expected.changes}
        got = {normalize_article_path(c.article_path) for c in outcome.predicted.changes}
        true_positives += len(want & got)
        predicted += len(got)
        expected += len(want)
    return _precision_recall(true_positives, predicted, expected)


def retrieval_scores(outcomes: Sequence[ItemOutcome], k: int = DEFAULT_K) -> RetrievalScores:
    """Recall@k and MRR over the chunks retrieved for each change.

    Scored per expected change, not per retrieved list: a change the pipeline never retrieved for
    counts as recall 0 and reciprocal rank 0. Scoring only what was retrieved would report perfect
    retrieval for a pipeline that extracted nothing.

    Changes with no expected impact are skipped -- there is nothing to find, so they would score 0
    however good the retriever is.
    """
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    for outcome in outcomes:
        relevant_by_change: dict[str, set[str]] = {}
        for impact in outcome.expected.impacts:
            key = normalize_article_path(impact.change_path)
            relevant_by_change.setdefault(key, set()).add(impact.chunk_id.strip())
        ranked_by_change = {
            normalize_article_path(r.change_path): [c.strip() for c in r.chunk_ids]
            for r in outcome.predicted.retrieval
        }
        for change_path, relevant in relevant_by_change.items():
            top_k = ranked_by_change.get(change_path, [])[:k]
            recalls.append(len(relevant & set(top_k)) / len(relevant))
            ranks = (1 / rank for rank, chunk in enumerate(top_k, start=1) if chunk in relevant)
            reciprocal_ranks.append(next(ranks, 0.0))
    return RetrievalScores(
        recall_at_k=fmean(recalls) if recalls else 0.0,
        k=k,
        mrr=fmean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        changes_scored=len(recalls),
    )


def impact_scores(outcomes: Sequence[ItemOutcome]) -> ImpactScores:
    """Detection of impacts, plus how often a detected impact is labelled correctly.

    An impact is identified by `(change, chunk)` -- see `impact_key`. Type and severity are scored
    over matched impacts only, so a labelling mistake does not also cost detection recall.
    """
    true_positives = predicted = expected = 0
    type_hits = severity_hits = matched = 0
    for outcome in outcomes:
        want = {impact_key(i.change_path, i.chunk_id): i for i in outcome.expected.impacts}
        got = {impact_key(i.change_path, i.chunk_id): i for i in outcome.predicted.impacts}
        predicted += len(got)
        expected += len(want)
        for key, prediction in got.items():
            gold = want.get(key)
            if gold is None:
                continue
            true_positives += 1
            matched += 1
            if prediction.type == gold.type:
                type_hits += 1
            if prediction.severity == gold.severity:
                severity_hits += 1
    return ImpactScores(
        detection=_precision_recall(true_positives, predicted, expected),
        type_accuracy=type_hits / matched if matched else None,
        severity_accuracy=severity_hits / matched if matched else None,
        matched=matched,
    )


def system_scores(outcomes: Sequence[ItemOutcome]) -> SystemScores:
    """Mean latency and cost per document, over the runs that reported them."""
    latencies = [
        o.predicted.latency_seconds for o in outcomes if o.predicted.latency_seconds is not None
    ]
    costs = [o.predicted.cost_usd for o in outcomes if o.predicted.cost_usd is not None]
    return SystemScores(
        latency_seconds=fmean(latencies) if latencies else None,
        cost_usd_per_document=fmean(costs) if costs else None,
    )


def evaluate(outcomes: Sequence[ItemOutcome], k: int = DEFAULT_K) -> StageScores:
    """Score every measurable step of one experiment."""
    return StageScores(
        dataset_size=len(outcomes),
        extraction=extraction_scores(outcomes),
        retrieval=retrieval_scores(outcomes, k=k),
        impact=impact_scores(outcomes),
        system=system_scores(outcomes),
    )
