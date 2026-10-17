import pytest

from app.evaluation.matching import impact_key, normalize_article_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Điều 3 khoản 1", "3.1"),
        ("Điều 3, khoản 1, điểm a", "3.1.a"),
        ("điều 3 khoản 1 điểm a", "3.1.a"),
        ("ĐIỀU 12", "12"),
        ("Điều 7 khoản 10", "7.10"),
        # Already normalized, or a label with no level this knows: kept comparable to itself.
        ("3.1", "3.1"),
        ("  Phụ lục   II ", "phụ lục ii"),
    ],
)
def test_normalize_article_path(raw: str, expected: str) -> None:
    assert normalize_article_path(raw) == expected


def test_spelling_differences_normalize_to_the_same_path() -> None:
    assert normalize_article_path("Điều 3, khoản 1") == normalize_article_path("điều 3 khoản 1")


def test_impact_key_drops_the_label_and_trims_the_chunk_id() -> None:
    assert impact_key("Điều 3, khoản 1", " chunk-7 ") == ("3.1", "chunk-7")
