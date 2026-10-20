from pathlib import Path

import pytest

from app.ria.legal_parser import ParseError, parse_pdf
from app.ria.obligations import ClauseInput, extract_obligations
from tests.ria_fixtures import html_pdf, ria_001_pdf

DATA = Path(__file__).resolve().parents[2] / "data"


def _parse_fixture():
    return parse_pdf(ria_001_pdf(), min_chars_per_page=50)


def test_structure_offsets_and_metadata():
    parsed = _parse_fixture()
    by_num = {c.numbering: c for c in parsed.clauses}
    assert parsed.metadata["doc_number"] == "99/2026/TT-NHNN"
    assert parsed.metadata["legal_form"] == "THÔNG TƯ"
    assert parsed.metadata["valid_from"] == "2026-07-01"
    assert parsed.metadata["issued_date"] == "2026-06-01"
    assert by_num["2"].level == "article" and by_num["2"].parent == "II"
    assert by_num["2.1"].parent == "2" and by_num["2.2.b"].parent == "2.2"
    assert by_num["2.1"].text.startswith("Tổ chức tín dụng phải")
    assert by_num["END"].level == "closing"
    for clause in parsed.clauses:
        # Offsets point into the canonical text; no clause swallows the next marker.
        assert parsed.text[clause.start : clause.end] == clause.text
        assert not clause.text.rstrip().endswith(("a)", "b)", "2.", "3."))
        assert clause.page == 1 and clause.bbox


def test_obligations_inherit_lead_in_and_skip_delegation():
    parsed = _parse_fixture()
    obligations = extract_obligations(
        [ClauseInput(c.numbering, c.level, c.text, c.parent, c.heading) for c in parsed.clauses]
    )
    assert obligations["2.1"][0].modality == "must"
    assert (
        "tối đa" in obligations["2.1"][0].deadline and "12 tháng" in obligations["2.1"][0].deadline
    )
    assert obligations["2.2.a"][0].modality == "must"
    assert obligations["2.2.a"][0].subject == "Tổ chức tín dụng"
    assert obligations["2.2.b"][0].modality == "must_not"
    assert "2.3" not in obligations  # "Ngân hàng Nhà nước hướng dẫn…" delegates, binds nobody
    assert "1" not in obligations  # scope article
    clause_text = {c.numbering: c.text for c in parsed.clauses}
    for numbering, items in obligations.items():
        for o in items:
            assert clause_text[numbering][o.span_start : o.span_end] == o.text


def test_point_labels_are_not_subject_or_action():
    clauses = [
        ClauseInput("4", "article", "Điều 4. Quyền và nghĩa vụ", None, "Điều 4. Quyền và nghĩa vụ"),
        ClauseInput("4.1", "clause", "Bên kiểm soát dữ liệu có trách nhiệm sau đây:", "4"),
        ClauseInput("4.1.a", "point", "a) Lưu trữ nhật ký xử lý dữ liệu cá nhân;", "4.1"),
        ClauseInput("4.1.b", "point", "b) Không được chuyển dữ liệu cá nhân ra nước ngoài;", "4.1"),
    ]
    obligations = extract_obligations(clauses)
    a, b = obligations["4.1.a"][0], obligations["4.1.b"][0]
    assert (a.subject, a.action) == ("Bên kiểm soát dữ liệu", "lưu trữ")
    assert (b.subject, b.modality, b.action) == ("Bên kiểm soát dữ liệu", "must_not", "chuyển dữ")
    assert a.text == "Lưu trữ nhật ký xử lý dữ liệu cá nhân;"
    assert clauses[2].text[a.span_start : a.span_end] == a.text


def test_scanned_or_empty_pdf_fails_closed():
    with pytest.raises(ParseError):
        parse_pdf(html_pdf("<p>.</p>"))
    with pytest.raises(ParseError):
        parse_pdf(b"%PDF-1.4 not really a pdf")


@pytest.mark.skipif(not (DATA / "91.pdf").exists(), reason="NHNN corpus not downloaded")
def test_real_law_91_2025():
    parsed = parse_pdf((DATA / "91.pdf").read_bytes())
    articles = [c for c in parsed.clauses if c.level == "article"]
    assert parsed.metadata["doc_number"] == "91/2025/QH15"
    assert parsed.metadata["valid_from"] == "2026-01-01"
    assert [a.numbering for a in articles] == [str(i) for i in range(1, 40)]
    assert all("about:blank" not in c.text for c in parsed.clauses)
    assert all(parsed.text[c.start : c.end] == c.text for c in parsed.clauses)
