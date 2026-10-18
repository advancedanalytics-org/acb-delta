import pytest

from app.services.chunker import extract_metadata


class _Page:
    """Stands in for a PyMuPDF page; real PDFs need a font with Vietnamese glyphs."""

    def __init__(self, text: str):
        self._text = text

    def get_text(self, option: str = "text"):
        return {"blocks": []} if option == "dict" else self._text


@pytest.mark.parametrize(
    ("text", "effective_date"),
    [
        # Day > 12: dd/mm/yyyy is an Invalid Date in the browser and crashed the page
        ("Số hiệu QT-KYC-02 · Hiệu lực từ 15/09/2024", "2024-09-15"),
        # Day <= 12: the browser silently read it as mm/dd
        ("Số hiệu QĐ-CV-01 · Hiệu lực từ 01/03/2025", "2025-03-01"),
        ("Hà Nội, ngày 5 tháng 10 năm 2026", "2026-10-05"),
    ],
)
def test_extract_metadata_returns_iso_effective_date(text, effective_date):
    assert extract_metadata([_Page(text)]).effective_date == effective_date
