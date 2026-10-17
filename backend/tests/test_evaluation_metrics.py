"""Known-answer tests: every expected number is computed by hand in the comment above it."""

import pytest

from app.evaluation.metrics import (
    DEFAULT_K,
    ItemOutcome,
    evaluate,
    extraction_scores,
    impact_scores,
    pair_items,
    retrieval_scores,
    system_scores,
)
from app.evaluation.schema import (
    DatasetItem,
    ExpectedChange,
    ExpectedImpact,
    PipelineOutput,
    PredictedChange,
    PredictedImpact,
    PredictedRetrieval,
)


def _expected_change(path: str) -> ExpectedChange:
    return ExpectedChange(article_path=path, kind="amended")


def _predicted_change(path: str) -> PredictedChange:
    return PredictedChange(article_path=path, kind="amended")


def _expected_impact(
    change_path: str,
    chunk_id: str,
    impact_type: str = "conflict",
    severity: str = "high",
) -> ExpectedImpact:
    return ExpectedImpact(
        change_path=change_path,
        document_id="doc-1",
        chunk_id=chunk_id,
        type=impact_type,
        severity=severity,
    )


def _predicted_impact(
    change_path: str,
    chunk_id: str,
    impact_type: str = "conflict",
    severity: str = "high",
) -> PredictedImpact:
    return PredictedImpact(
        change_path=change_path,
        document_id="doc-1",
        chunk_id=chunk_id,
        type=impact_type,
        severity=severity,
    )


def _outcome(
    item_id: str = "item-1",
    *,
    expected_changes: list[ExpectedChange] | None = None,
    predicted_changes: list[PredictedChange] | None = None,
    expected_impacts: list[ExpectedImpact] | None = None,
    predicted_impacts: list[PredictedImpact] | None = None,
    retrieval: list[PredictedRetrieval] | None = None,
    latency_seconds: float | None = None,
    cost_usd: float | None = None,
) -> ItemOutcome:
    return ItemOutcome(
        expected=DatasetItem(
            item_id=item_id,
            vbpl_id="vbpl-1",
            changes=expected_changes or [],
            impacts=expected_impacts or [],
        ),
        predicted=PipelineOutput(
            item_id=item_id,
            changes=predicted_changes or [],
            impacts=predicted_impacts or [],
            retrieval=retrieval or [],
            latency_seconds=latency_seconds,
            cost_usd=cost_usd,
        ),
    )


def test_default_k_matches_the_dashboard_label() -> None:
    # evaluation-page.tsx renders the literal label "Recall@5"; a different k would make it lie.
    assert DEFAULT_K == 5


# Expected {3.1, 3.2, 5}, predicted {3.1, 3.2, 7} written with different spellings.
# TP 2, predicted 3, expected 3 -> P = R = F1 = 2/3.
def test_extraction_precision_recall() -> None:
    outcome = _outcome(
        expected_changes=[
            _expected_change("Điều 3 khoản 1"),
            _expected_change("Điều 3 khoản 2"),
            _expected_change("Điều 5"),
        ],
        predicted_changes=[
            _predicted_change("Điều 3, khoản 1"),
            _predicted_change("điều 3 khoản 2"),
            _predicted_change("Điều 7"),
        ],
    )

    scores = extraction_scores([outcome])

    assert (scores.true_positives, scores.predicted, scores.expected) == (2, 3, 3)
    assert scores.precision == pytest.approx(2 / 3)
    assert scores.recall == pytest.approx(2 / 3)
    assert scores.f1 == pytest.approx(2 / 3)


# The same clause reported twice counts once: predicted 1, not 2.
def test_extraction_collapses_repeated_clauses() -> None:
    outcome = _outcome(
        expected_changes=[_expected_change("Điều 3 khoản 1")],
        predicted_changes=[
            _predicted_change("Điều 3 khoản 1"),
            _predicted_change("Điều 3, khoản 1"),
        ],
    )

    scores = extraction_scores([outcome])

    assert (scores.true_positives, scores.predicted) == (1, 1)
    assert scores.precision == pytest.approx(1.0)


# Item A: 1 expected, 1 correct. Item B: 3 expected, 3 predicted, 1 correct.
# Micro: TP 2 / predicted 4 = 0.5. A macro average would give (1 + 1/3) / 2 = 0.667.
def test_extraction_is_micro_averaged_across_items() -> None:
    item_a = _outcome(
        "item-a",
        expected_changes=[_expected_change("Điều 1")],
        predicted_changes=[_predicted_change("Điều 1")],
    )
    item_b = _outcome(
        "item-b",
        expected_changes=[
            _expected_change("Điều 2"),
            _expected_change("Điều 3"),
            _expected_change("Điều 4"),
        ],
        predicted_changes=[
            _predicted_change("Điều 2"),
            _predicted_change("Điều 8"),
            _predicted_change("Điều 9"),
        ],
    )

    scores = extraction_scores([item_a, item_b])

    assert (scores.true_positives, scores.predicted, scores.expected) == (2, 4, 4)
    assert scores.precision == pytest.approx(0.5)
    assert scores.recall == pytest.approx(0.5)


def _ranked_outcome() -> ItemOutcome:
    """Relevant chunks {c1, c2}; retriever returned [c3, c1, c4, c2, c5]."""
    return _outcome(
        expected_impacts=[
            _expected_impact("Điều 3 khoản 1", "c1"),
            _expected_impact("Điều 3 khoản 1", "c2"),
        ],
        retrieval=[
            PredictedRetrieval(
                change_path="Điều 3, khoản 1",
                chunk_ids=["c3", "c1", "c4", "c2", "c5"],
            )
        ],
    )


@pytest.mark.parametrize(
    ("k", "recall", "mrr"),
    [
        # top-5 = [c3, c1, c4, c2, c5]: both relevant found -> 2/2. First hit at rank 2 -> 1/2.
        (5, 1.0, 0.5),
        # top-2 = [c3, c1]: one of two found -> 1/2. First hit still at rank 2 -> 1/2.
        (2, 0.5, 0.5),
        # top-1 = [c3]: nothing relevant -> 0 and 0.
        (1, 0.0, 0.0),
    ],
)
def test_retrieval_recall_at_k_and_mrr(k: int, recall: float, mrr: float) -> None:
    scores = retrieval_scores([_ranked_outcome()], k=k)

    assert scores.k == k
    assert scores.changes_scored == 1
    assert scores.recall_at_k == pytest.approx(recall)
    assert scores.mrr == pytest.approx(mrr)


# A change the pipeline never retrieved for must score 0, not be skipped: otherwise a pipeline
# that extracts nothing reports perfect retrieval.
def test_change_with_no_retrieval_at_all_scores_zero() -> None:
    outcome = _outcome(
        expected_impacts=[_expected_impact("Điều 3 khoản 1", "c1")],
        retrieval=[],
    )

    scores = retrieval_scores([outcome])

    assert scores.changes_scored == 1
    assert scores.recall_at_k == pytest.approx(0.0)
    assert scores.mrr == pytest.approx(0.0)


# Nothing is expected for this change, so there is nothing retrieval could have found.
def test_change_without_expected_impacts_is_not_scored() -> None:
    outcome = _outcome(
        expected_changes=[_expected_change("Điều 3 khoản 1")],
        retrieval=[PredictedRetrieval(change_path="Điều 3 khoản 1", chunk_ids=["c9"])],
    )

    scores = retrieval_scores([outcome])

    assert scores.changes_scored == 0
    assert scores.recall_at_k == pytest.approx(0.0)


# Expected: (3.1, c1, conflict/high), (3.2, c2, new_obligation/medium).
# Predicted: (3.1, c1) correct; (3.2, c2) matched but typed conflict instead of new_obligation;
# (5, c9) is a false positive.
# TP 2, predicted 3, expected 2 -> P = 2/3, R = 1.0, F1 = 2 * (2/3) / (2/3 + 1) = 0.8.
# Labels over the 2 matched: type 1/2, severity 2/2.
def test_impact_detection_and_label_accuracy() -> None:
    outcome = _outcome(
        expected_impacts=[
            _expected_impact("Điều 3 khoản 1", "c1", "conflict", "high"),
            _expected_impact("Điều 3 khoản 2", "c2", "new_obligation", "medium"),
        ],
        predicted_impacts=[
            _predicted_impact("Điều 3, khoản 1", "c1", "conflict", "high"),
            _predicted_impact("Điều 3, khoản 2", "c2", "conflict", "medium"),
            _predicted_impact("Điều 5", "c9", "conflict", "low"),
        ],
    )

    scores = impact_scores([outcome])

    assert scores.matched == 2
    assert scores.detection.precision == pytest.approx(2 / 3)
    # The mislabelled impact was still detected: labelling never costs detection recall.
    assert scores.detection.recall == pytest.approx(1.0)
    assert scores.detection.f1 == pytest.approx(0.8)
    assert scores.type_accuracy == pytest.approx(0.5)
    assert scores.severity_accuracy == pytest.approx(1.0)


# Accuracy over zero matched impacts is unknown, not 0.0.
def test_label_accuracy_is_none_when_nothing_matched() -> None:
    outcome = _outcome(
        expected_impacts=[_expected_impact("Điều 3 khoản 1", "c1")],
        predicted_impacts=[_predicted_impact("Điều 9", "c9")],
    )

    scores = impact_scores([outcome])

    assert scores.matched == 0
    assert scores.detection.recall == pytest.approx(0.0)
    assert scores.type_accuracy is None
    assert scores.severity_accuracy is None


# Latencies 10 and 20 -> 15. Only one run reported a cost -> that cost stands.
def test_system_scores_average_only_the_runs_that_reported() -> None:
    scores = system_scores(
        [
            _outcome("item-a", latency_seconds=10.0, cost_usd=0.1),
            _outcome("item-b", latency_seconds=20.0),
        ]
    )

    assert scores.latency_seconds == pytest.approx(15.0)
    assert scores.cost_usd_per_document == pytest.approx(0.1)


# Nothing measures latency or cost yet, so an unmeasured run must stay visibly unmeasured.
def test_system_scores_are_none_when_nothing_reported() -> None:
    scores = system_scores([_outcome()])

    assert scores.latency_seconds is None
    assert scores.cost_usd_per_document is None


def test_pair_items_keeps_dataset_order_and_matches_by_id() -> None:
    dataset = [
        DatasetItem(item_id="item-a", vbpl_id="v1"),
        DatasetItem(item_id="item-b", vbpl_id="v1"),
    ]
    outputs = [PipelineOutput(item_id="item-b"), PipelineOutput(item_id="item-a")]

    outcomes = pair_items(dataset, outputs)

    assert [o.expected.item_id for o in outcomes] == ["item-a", "item-b"]
    assert [o.predicted.item_id for o in outcomes] == ["item-a", "item-b"]


def test_pair_items_rejects_a_dataset_item_with_no_output() -> None:
    dataset = [DatasetItem(item_id="item-a", vbpl_id="v1")]

    with pytest.raises(ValueError, match="item-a"):
        pair_items(dataset, [])


def test_evaluate_on_an_empty_dataset_does_not_divide_by_zero() -> None:
    scores = evaluate([])

    assert scores.dataset_size == 0
    assert scores.extraction.precision == pytest.approx(0.0)
    assert scores.retrieval.changes_scored == 0
    assert scores.impact.type_accuracy is None
    assert scores.system.latency_seconds is None
