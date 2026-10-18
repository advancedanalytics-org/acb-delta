"""End-to-end: POST /api/regulations → parse job → POST /analyze → findings, on real Postgres.

Needs a disposable Postgres + pgvector, e.g.
  docker run --rm -d -p 127.0.0.1:55432:5432 -e POSTGRES_USER=acb -e POSTGRES_PASSWORD=test \
    -e POSTGRES_DB=acb_delta pgvector/pgvector:pg16
  RIA_TEST_DATABASE_URL=postgresql+psycopg://acb:test@127.0.0.1:55432/acb_delta uv run pytest
"""

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.ria_fixtures import ria_001_pdf

DB_URL = os.environ.get("RIA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="RIA_TEST_DATABASE_URL not set")
DOC_102 = Path(__file__).resolve().parents[2] / "db" / "DOC-102.parsed.json"


def _reset_caches():
    from app.config import get_settings
    from app.db import get_engine
    from app.ria import schema, storage

    get_settings.cache_clear()
    get_engine.cache_clear()
    storage.get_storage.cache_clear()
    schema._ready = False


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", DB_URL)
    patch.setenv("STORAGE_BACKEND", "local")
    patch.setenv("STORAGE_LOCAL_DIR", str(tmp_path_factory.mktemp("storage")))
    for name in ("EMBEDDING_BASE_URL", "OPENAI_BASE_URL", "LLM_MODEL"):
        patch.setenv(name, "")
    _reset_caches()
    from app.main import create_app
    from app.ria.schema import ensure_schema
    from app.ria.seed import seed_file

    ensure_schema()
    seed_file(DOC_102)
    with TestClient(create_app()) as test_client:
        yield test_client
    patch.undo()
    _reset_caches()


def _wait(client, job_id: str, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.3)
    raise TimeoutError(job_id)


def _upload(client, data: bytes, name: str = "tt-99-2026.pdf"):
    return client.post("/api/regulations", files={"file": (name, data, "application/pdf")})


def test_rejects_non_pdf(client):
    response = client.post("/api/regulations", files={"file": ("x.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_analyze_unknown_regulation(client):
    assert client.post("/api/regulations/REG-NOPE/analyze").status_code == 404
    assert client.get("/api/jobs/JOB-nope").status_code == 404


def test_ingest_parse_analyze_finds_value_change(client):
    response = _upload(client, ria_001_pdf())
    assert response.status_code in (200, 202)
    body = response.json()
    assert body["regulation_id"] == "REG-99-2026-TT-NHNN"
    parse = _wait(client, body["job_id"])
    assert parse["status"] == "succeeded", parse["error"]
    if body["duplicate"] is False:
        assert parse["result"]["metadata"]["doc_number"] == "99/2026/TT-NHNN"
        assert parse["result"]["obligations"] == 3
        assert parse["result"]["legal_status"] == "effective"

    # Same bytes again: no new version, existing state returned.
    again = _upload(client, ria_001_pdf())
    assert again.status_code == 200 and again.json()["duplicate"] is True

    started = client.post(f"/api/regulations/{body['regulation_id']}/analyze", json={})
    assert started.status_code == 202, started.text
    job = _wait(client, started.json()["job_id"])
    assert job["status"] == "succeeded", job["error"]
    result = job["result"]
    assert result["status"] == "AI_PROPOSED"
    assert result["retrieval_methods"] == ["sparse"]
    assert result["documents"][0]["document_id"] == "DOC-102"

    from app.db import get_engine

    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT f.*, e.span_text FROM impact_finding f "
                "JOIN evidence e ON e.evidence_id = f.evidence_id WHERE f.job_id = :j"
            ),
            {"j": job["job_id"]},
        ).mappings()
        findings = {(r["internal_clause_id"], r["category"]): dict(r) for r in rows}
        status = conn.execute(
            text("SELECT processing_status FROM document_version WHERE version_id = :v"),
            {"v": body["version_id"]},
        ).scalar()
    assert status == "AI_PROPOSED"

    value_change = findings[("DOC-102@v4#5.2", "VALUE_CHANGE")]
    assert value_change["target_span"]["text"] == "24 tháng"
    assert "12 tháng" in value_change["source_span"]["text"]
    assert value_change["priority"] == "high"
    assert value_change["verification"]["status"] == "NEEDS_HUMAN_REVIEW"
    # Primary clause first, then the other evidence clauses grouped into the same finding.
    assert value_change["citations"][:2] == ["REG-99-2026-TT-NHNN@v1#2.1", "DOC-102@v4#5.2"]
    assert value_change["evidence_ids"][0] == value_change["evidence_id"]
    assert len(value_change["evidence_ids"]) == len(value_change["citations"]) - 1
    # 5.5 already sets 12 months for high-risk customers: compliant, no edit proposed.
    equivalent = findings.get(("DOC-102@v4#5.5", "EQUIVALENT"))
    if equivalent:
        assert equivalent["status"] == "NO_ACTION_PROPOSED"


def test_analyze_requires_parsed_version(client):
    from app.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO document (document_id, title, doc_type, owner) VALUES "
                "('REG-DRAFT-TEST', 'draft', 'regulation', 'test') ON CONFLICT DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO document_version (version_id, document_id, version_label, status, "
                "checksum, processing_status) VALUES ('REG-DRAFT-TEST@v1', 'REG-DRAFT-TEST', "
                "'v1', 'pending', 'sha256:draft-test', 'DRAFT') ON CONFLICT DO NOTHING"
            )
        )
    response = client.post("/api/regulations/REG-DRAFT-TEST/analyze")
    assert response.status_code == 409


def _fake_vectors(texts: list[str]) -> list[list[float]]:
    """Deterministic bag-of-bigrams vectors: enough to exercise pgvector storage and search."""
    import hashlib
    import math

    from app.ria.textutil import content_bigrams

    out = []
    for t in texts:
        v = [0.0] * 1024
        for g in content_bigrams(t):
            v[int(hashlib.md5(g.encode()).hexdigest(), 16) % 1024] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / norm for x in v])
    return out


def test_dense_retrieval_path(client, monkeypatch):
    from app.db import get_engine
    from app.ria import embeddings
    from app.ria.indexing import build_index_views

    monkeypatch.setattr(embeddings, "embedding_version", lambda: "fake-bow@test")
    monkeypatch.setattr(embeddings, "embed", lambda texts, batch_size=32: _fake_vectors(texts))
    with get_engine().begin() as conn:
        stats = build_index_views(conn, "DOC-102@v4", with_embeddings=True)
    assert stats["embedding_version"] == "fake-bow@test"

    body = _upload(client, ria_001_pdf()).json()
    assert _wait(client, body["job_id"])["status"] == "succeeded"
    started = client.post(f"/api/regulations/{body['regulation_id']}/analyze", json={})
    job = _wait(client, started.json()["job_id"])
    assert job["status"] == "succeeded", job["error"]
    assert job["result"]["retrieval_methods"] == ["sparse", "dense"]
    assert job["result"]["embedding_version"] == "fake-bow@test"
    with get_engine().connect() as conn:
        methods = set(
            conn.execute(
                text("SELECT retrieval_method FROM evidence WHERE job_id = :j"),
                {"j": job["job_id"]},
            ).scalars()
        )
    assert any("dense" in m for m in methods)
