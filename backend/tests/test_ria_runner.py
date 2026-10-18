"""The adapter from RIA shapes to the scored shapes, with every number computed by hand.

The run below is a constructed case, not a recording of the pipeline: it misses one obligation,
invents another, and reports one clause the labels mark `EQUIVALENT`. Those are the three ways the
arithmetic can go wrong, so they belong in a unit test rather than in a live run.
"""

from pathlib import Path

import pytest

from app.evaluation.ground_truth import build_dataset
from app.evaluation.metrics import evaluate
from app.evaluation.ria_runner import RunArtifacts, to_outcome

PARSED = Path(__file__).resolve().parents[2] / "db" / "DOC-102.parsed.json"


@pytest.fixture(scope="module")
def item():
    return build_dataset(PARSED)


@pytest.fixture
def run():
    return RunArtifacts(
        regulation_id="REG-88-2026-TT-NHNN",
        analyze_job_id="JOB-test",
        vbpl_id="vbpl-test",
        impacts=[],
        # Three of the four labelled obligations, plus one the labels do not have: one miss and
        # one spurious extraction, so precision and recall are both exercised.
        obligations={"2.1", "2.2", "2.2.b", "2.3"},
        retrieval={
            # Relevant for 2.1 are #5.2 and #5.3; both inside the top 5, first hit at rank 2.
            "2.1": [
                "DOC-102@v4#5.5",
                "DOC-102@v4#5.2",
                "DOC-102@v4#4.1",
                "DOC-102@v4#5.3",
                "DOC-102@v4#9.1",
            ],
            # Relevant for 2.2.b is #4.1, at rank 2.
            "2.2.b": ["DOC-102@v4#4.2", "DOC-102@v4#4.1"],
            # 2.3 retrieved nothing: its one relevant clause is missed.
            "2.3": [],
        },
        findings=[
            ("2.1", "DOC-102@v4#5.2", "VALUE_CHANGE", "high"),
            # False positive: #5.5 is labelled EQUIVALENT, it must not be reported.
            ("2.1", "DOC-102@v4#5.5", "VALUE_CHANGE", "medium"),
            ("2.2.b", "DOC-102@v4#4.1", "CONTRADICTION", "high"),
            # Dropped by the adapter: EQUIVALENT is never an expected report.
            ("2.2.a", "DOC-102@v4#4.3", "EQUIVALENT", "low"),
        ],
        latency_seconds=42.5,
    )


# Expected obligations {2.1, 2.2.a, 2.2.b, 2.3}; found {2.1, 2.2, 2.2.b, 2.3}.
# TP 3, predicted 4, expected 4 -> P = R = 0.75.
def test_extraction_scores_one_miss_and_one_spurious_obligation(item, run):
    scores = evaluate([to_outcome(item, run)])

    assert scores.extraction.true_positives == 3
    assert scores.extraction.precision == pytest.approx(0.75)
    assert scores.extraction.recall == pytest.approx(0.75)


# Per obligation: 2.1 -> 2 of 2 relevant in top 5, first at rank 2; 2.2.b -> 1 of 1, rank 2;
# 2.3 -> nothing retrieved. Recall@5 = (1 + 1 + 0) / 3; MRR = (1/2 + 1/2 + 0) / 3.
def test_retrieval_averages_over_obligations_including_the_one_that_found_nothing(item, run):
    scores = evaluate([to_outcome(item, run)])

    assert scores.retrieval.changes_scored == 3
    assert scores.retrieval.recall_at_k == pytest.approx(2 / 3)
    assert scores.retrieval.mrr == pytest.approx(1 / 3)


# Expected pairs: (2.1,#5.2), (2.1,#5.3), (2.2.b,#4.1), (2.3,#11.1) = 4.
# Reported pairs after dropping EQUIVALENT: (2.1,#5.2), (2.1,#5.5), (2.2.b,#4.1) = 3, of which 2
# match. P = 2/3, R = 2/4, F1 = 2PR/(P+R) = 4/7.
def test_impact_detection_counts_a_reported_equivalent_as_a_false_positive(item, run):
    scores = evaluate([to_outcome(item, run)])

    assert scores.impact.detection.true_positives == 2
    assert scores.impact.detection.predicted == 3
    assert scores.impact.detection.expected == 4
    assert scores.impact.detection.precision == pytest.approx(2 / 3)
    assert scores.impact.detection.recall == pytest.approx(0.5)
    assert scores.impact.detection.f1 == pytest.approx(4 / 7)


def test_equivalent_findings_are_not_scored_as_predictions(item, run):
    outcome = to_outcome(item, run)

    reported = {(i.change_path, i.chunk_id) for i in outcome.predicted.impacts}
    assert ("2.2.a", "DOC-102@v4#4.3") not in reported
    assert len(outcome.predicted.impacts) == 3


def test_severity_comes_from_the_finding_not_a_placeholder(item, run):
    outcome = to_outcome(item, run)

    by_clause = {i.chunk_id: i.severity for i in outcome.predicted.impacts}
    assert by_clause["DOC-102@v4#5.2"] == "high"
    assert by_clause["DOC-102@v4#5.5"] == "medium"


def test_latency_is_carried_through_and_cost_stays_unmeasured(item, run):
    scores = evaluate([to_outcome(item, run)])

    assert scores.system.latency_seconds == pytest.approx(42.5)
    assert scores.system.cost_usd_per_document is None
