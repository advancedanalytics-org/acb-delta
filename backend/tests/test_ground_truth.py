"""The labels must stay anchored to the real corpus, and the regulation must parse as assumed.

Both are silent failure modes: a label whose span drifted, or numbering the parser reports
differently, would score zero for a reason that has nothing to do with pipeline quality.
"""

from pathlib import Path

import pytest

from app.evaluation.ground_truth import REGULATION_NUMBER, build_dataset, regulation_pdf

PARSED = Path(__file__).resolve().parents[2] / "db" / "DOC-102.parsed.json"


@pytest.fixture(scope="module")
def item():
    return build_dataset(PARSED)


def test_every_planted_span_is_in_the_real_internal_text(item):
    # build_dataset raises when a span drifted, so reaching here already proves it. Assert the
    # shape too, so a dataset that silently lost its labels fails as well.
    assert len(item.obligations) == 4
    assert len(item.findings) == 7


def test_labels_include_equivalents_so_false_positives_are_measurable(item):
    positives = item.expected_findings
    equivalents = [f for f in item.findings if f.category == "EQUIVALENT"]

    assert len(positives) == 4
    assert len(equivalents) == 3
    # Without these, Precision looks perfect no matter what the pipeline reports.
    assert {f.internal_clause_id for f in equivalents} == {
        "DOC-102@v4#5.5",
        "DOC-102@v4#4.3",
        "DOC-102@v4#4.2",
    }


def test_positive_labels_cover_three_categories(item):
    assert {f.category for f in item.expected_findings} == {
        "VALUE_CHANGE",
        "CONTRADICTION",
        "ADDITION",
    }


def test_every_positive_label_carries_a_reference_patch(item):
    # The LLM judge compares the drafted patch against this; a label without one cannot be judged.
    assert all(f.reference_patch is not None for f in item.expected_findings)


def test_build_fails_when_a_span_no_longer_matches(tmp_path, monkeypatch):
    from app.evaluation import ground_truth

    broken = tmp_path / "parsed.json"
    broken.write_text(
        '{"clause": [{"clause_id": "DOC-102@v4#5.2", "text": "no span here"}]}', encoding="utf-8"
    )
    monkeypatch.setattr(ground_truth, "_FINDINGS", ground_truth._FINDINGS[:1])

    with pytest.raises(ValueError, match="not in its text"):
        ground_truth.build_dataset(broken)


def test_the_regulation_parses_to_the_numbering_the_labels_assume(item):
    from app.ria.legal_parser import parse_pdf

    parsed = parse_pdf(regulation_pdf())

    assert parsed.metadata["doc_number"] == REGULATION_NUMBER
    numbering = {c.numbering for c in parsed.clauses}
    # Labels key obligations by these; if the parser numbered them differently the extraction
    # metric would read 0 for the wrong reason.
    assert {"2.1", "2.2.a", "2.2.b", "2.3"} <= numbering
