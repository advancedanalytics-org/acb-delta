"""Document uploads: PDF header check, size cap, and safe file names."""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.routers.documents import safe_name

client = TestClient(create_app())


def test_safe_name_drops_directories_and_odd_characters():
    assert safe_name("../../app/main.py", "x") == "main.py"
    assert safe_name("..\\..\\evil.pdf", "x") == "evil.pdf"
    assert safe_name("Quy chế tín dụng 2026.pdf", "x") == "Quy_chế_tín_dụng_2026.pdf"
    assert safe_name("..", "fallback.pdf") == "fallback.pdf"
    assert safe_name("", "fallback.pdf") == "fallback.pdf"


def test_upload_without_pdf_header_is_refused():
    files = {"file": ("note.pdf", b"<html>not a pdf</html>", "application/pdf")}
    assert client.post("/api/documents/ingest-internal", files=files).status_code == 415
    assert client.post("/api/documents/upload", files=files).status_code == 415


def test_empty_and_oversized_uploads_are_refused(monkeypatch):
    files = {"file": ("empty.pdf", b"", "application/pdf")}
    assert client.post("/api/documents/ingest-internal", files=files).status_code == 400

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    files = {"file": ("big.pdf", b"%PDF-1.7 tiny", "application/pdf")}
    assert client.post("/api/documents/ingest-internal", files=files).status_code == 413
