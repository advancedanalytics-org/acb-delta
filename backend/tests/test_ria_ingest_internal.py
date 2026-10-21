"""Internal document ingest against Postgres: a parser change re-parses an unchanged PDF.

Requires a throwaway pgvector Postgres, e.g.
  RIA_TEST_DATABASE_URL=postgresql+psycopg://acb:test@127.0.0.1:55432/acb_delta uv run pytest
"""

import os

import pymupdf
import pytest
from sqlalchemy import text

DB_URL = os.environ.get("RIA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="RIA_TEST_DATABASE_URL not set")

FOOTER = "DOC-901 · Phiên bản 1.0 · Trang {n}"


def _internal_pdf() -> bytes:
    """Two-page internal regulation with the DOCX → PDF page footer on every page."""
    doc = pymupdf.open()
    bodies = [
        "<p>Mã tài liệu: DOC-901</p><p>Phiên bản: 1.0</p><p>Điều 1. Nhật ký xử lý dữ liệu</p>"
        "<p>Đơn vị phải lưu nhật ký xử lý dữ liệu quan trọng trong 03 tháng.</p>",
        "<p>Điều 2. Báo cáo</p><p>Đơn vị báo cáo Khối Tuân thủ hằng quý về kết quả lưu trữ.</p>",
    ]
    for n, body in enumerate(bodies, start=1):
        page = doc.new_page()
        page.insert_htmlbox(pymupdf.Rect(72, 72, 520, 400), body)
        h = page.rect.height
        page.insert_htmlbox(pymupdf.Rect(150, h - 40, 450, h - 20), FOOTER.format(n=n))
    return doc.tobytes()


@pytest.fixture
def ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    for name in ("EMBEDDING_BASE_URL", "S3_ENDPOINT_URL"):
        monkeypatch.setenv(name, "")
    from app.config import get_settings
    from app.db import get_engine
    from app.ria import ingest_internal, schema

    get_settings.cache_clear()
    get_engine.cache_clear()
    schema._ready = False
    schema.ensure_schema()
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM index_view WHERE clause_id LIKE 'DOC-901@%'"))
        conn.execute(text("DELETE FROM obligation_clause WHERE clause_id LIKE 'DOC-901@%'"))
        conn.execute(text("DELETE FROM obligation WHERE source_clause_id LIKE 'DOC-901@%'"))
        conn.execute(text("DELETE FROM clause WHERE version_id LIKE 'DOC-901@%'"))
        conn.execute(text("DELETE FROM document_version WHERE document_id = 'DOC-901'"))
    path = tmp_path / "DOC-901.pdf"
    path.write_bytes(_internal_pdf())
    yield lambda: ingest_internal._do_ingest_internal_pdf(path), ingest_internal.PARSER_VERSION
    get_settings.cache_clear()
    get_engine.cache_clear()


def _clause_texts() -> list[str]:
    from app.db import get_engine

    with get_engine().connect() as conn:
        return list(
            conn.execute(text("SELECT text FROM clause WHERE version_id = 'DOC-901@v1'")).scalars()
        )


def test_parser_change_reparses_an_unchanged_pdf(ingest):
    from app.db import get_engine

    run, parser_version = ingest
    first = run()
    assert first.get("unchanged") is not True and first["clauses"] > 0
    assert not any("Trang 1" in t for t in _clause_texts())

    # Same file again, same parser: skipped.
    assert run()["unchanged"] is True

    # A version ingested by older parser code (footer still in its clauses, no fingerprint).
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE clause SET text = text || :f WHERE version_id = 'DOC-901@v1' "
                "AND numbering = '1'"
            ),
            {"f": "\n" + FOOTER.format(n=1)},
        )
        conn.execute(
            text(
                "UPDATE document_version SET parser_version = NULL WHERE version_id = 'DOC-901@v1'"
            )
        )
    assert any("Trang 1" in t for t in _clause_texts())

    again = run()
    assert again.get("unchanged") is not True
    assert not any("Trang 1" in t for t in _clause_texts())
    with get_engine().connect() as conn:
        stored = conn.execute(
            text("SELECT parser_version FROM document_version WHERE version_id = 'DOC-901@v1'")
        ).scalar()
    assert stored == parser_version
