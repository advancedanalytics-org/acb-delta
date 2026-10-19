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
# Optional FalkorDB for the knowledge-graph tests, e.g. redis://127.0.0.1:56379.
GRAPH_URL = os.environ.get("RIA_TEST_FALKORDB_URL", "")
pytestmark = pytest.mark.skipif(not DB_URL, reason="RIA_TEST_DATABASE_URL not set")
DOC_102 = Path(__file__).resolve().parents[2] / "db" / "DOC-102.parsed.json"


def _reset_caches():
    from app.config import get_settings
    from app.db import get_engine
    from app.ria import graph, schema, storage

    graph.reset_client()
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
    for name in (
        "EMBEDDING_BASE_URL",
        "OPENAI_BASE_URL",
        "LLM_MODEL",
        "RERANK_BASE_URL",
        "RERANK_MODEL",
        "JEV_BASE_URL",
        "JEV_MODEL",
    ):
        patch.setenv(name, "")
    patch.setenv("RERANK_BACKEND", "rerank")
    patch.setenv("FALKORDB_URL", GRAPH_URL)
    patch.setenv("FALKORDB_GRAPH", "ria_test")
    _reset_caches()
    if GRAPH_URL:
        from app.ria import graph

        try:  # the test database is fresh: so must the test graph be
            graph._graph().delete()
        except Exception:
            pass
        graph.reset_client()
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
    assert stats["article_views"] > 0  # DICE: one mean vector per multi-clause article

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
    assert any("article" in m for m in methods)
    with get_engine().connect() as conn:
        article_ranks = conn.execute(
            text(
                "SELECT count(*) FROM evidence WHERE job_id = :j "
                "AND details->'ranks' ? 'article:legal_text'"
            ),
            {"j": job["job_id"]},
        ).scalar()
    assert article_ranks > 0


def _fake_llm(system, user, timeout=120):
    """Deterministic stand-in for the LLM: quotes are copied from the payload, so they ground."""
    import json as _json

    from app.ria import applicability, compare

    payload = _json.loads(user)
    if system == applicability.SYSTEM:
        return {"items": [{"id": o["id"], "applies": "yes", "reason": "test"} for o in payload]}
    assert system == compare.SYSTEM
    source = payload["nghia_vu_nguon"]["trich_dan"]
    clauses = payload["dieu_khoan_noi_bo"]
    return {
        "best": clauses[0]["ma"],
        "results": [
            {
                "ma": c["ma"],
                "classification": "INDIRECT_IMPACT",
                "rationale": "test",
                "source_quote": source[:12],
                "target_quote": c["noi_dung"][:12],
                "confidence": 0.5,
            }
            for c in clauses
        ],
    }


def test_rerank_group_llm_and_cache(client, monkeypatch):
    from app.db import get_engine
    from app.ria import llm, rerank

    monkeypatch.setattr(rerank, "rerank_model", lambda: "fake-reranker")
    monkeypatch.setattr(
        rerank,
        "rerank",
        lambda q, docs, timeout=60: [0.9 if "rà soát" in d else 0.05 for d in docs],
    )
    monkeypatch.setattr(llm, "llm_model", lambda: "fake-llm")
    monkeypatch.setattr(llm, "chat_json", _fake_llm)

    body = _upload(client, ria_001_pdf()).json()
    assert _wait(client, body["job_id"])["status"] == "succeeded"
    options = {"refresh_llm_cache": True}
    first = _wait(
        client,
        client.post(f"/api/regulations/{body['regulation_id']}/analyze", json=options).json()[
            "job_id"
        ],
    )
    assert first["status"] == "succeeded", first["error"]
    r1 = first["result"]
    assert r1["retrieval_methods"][-1] == "rerank" and r1["rerank_model"] == "fake-reranker"
    groups = r1["obligations"]["with_evidence"]
    assert groups > 0 and r1["llm_calls"] == groups and r1["llm_cache_hits"] == 0
    assert r1["evidence"] >= groups  # several clauses per obligation, one call each

    second = _wait(
        client,
        client.post(f"/api/regulations/{body['regulation_id']}/analyze", json={}).json()["job_id"],
    )
    r2 = second["result"]
    assert r2["llm_calls"] == 0 and r2["llm_cache_hits"] == groups

    with get_engine().connect() as conn:
        stored = dict(
            conn.execute(
                text(
                    "SELECT o.applicability, count(*) FROM obligation o JOIN clause c "
                    "ON c.clause_id = o.source_clause_id WHERE c.version_id = :v GROUP BY 1"
                ),
                {"v": body["version_id"]},
            ).all()
        )
        methods = set(
            conn.execute(
                text("SELECT retrieval_method FROM evidence WHERE job_id = :j"),
                {"j": first["job_id"]},
            ).scalars()
        )
    assert stored == {"yes": 3}  # "Tổ chức tín dụng" duties: decided by rule, stored
    # Retrieved evidence is reranked; clauses added by the knowledge graph are marked as such.
    assert all(m.endswith("+rerank") or m == "graph:refers_to" for m in methods)


def _analyze(client, regulation_id: str, body: dict | None = None) -> dict:
    started = client.post(f"/api/regulations/{regulation_id}/analyze", json=body or {})
    assert started.status_code in (200, 202), started.text
    job = _wait(client, started.json()["job_id"])
    assert job["status"] == "succeeded", job["error"]
    return job


def _regulation(client) -> dict:
    body = _upload(client, ria_001_pdf()).json()
    if body["job_id"]:
        assert _wait(client, body["job_id"])["status"] == "succeeded"
    return body


def test_findings_list_filters_and_evidence_pack(client):
    reg = _regulation(client)
    job = _analyze(client, reg["regulation_id"])
    listed = client.get("/api/findings", params={"job_id": job["job_id"]}).json()
    assert listed["total"] == len(listed["items"]) > 0
    assert listed["items"][0]["priority"] == "high"  # most severe first
    value = next(f for f in listed["items"] if f["category"] == "VALUE_CHANGE")
    only = client.get(
        "/api/findings", params={"job_id": job["job_id"], "category": "VALUE_CHANGE"}
    ).json()
    assert {f["category"] for f in only["items"]} == {"VALUE_CHANGE"}
    by_regulation = client.get(
        "/api/findings", params={"regulation_id": reg["regulation_id"], "limit": 1}
    ).json()
    assert by_regulation["total"] >= listed["total"] and len(by_regulation["items"]) == 1

    pack = client.get(f"/api/findings/{value['finding_id']}/evidence").json()
    assert pack["obligation"]["text"].startswith("Tổ chức tín dụng phải rà soát")
    assert pack["internal_clause"]["clause_id"] == "DOC-102@v4#5.2"
    assert pack["evidence"][0]["evidence_id"] == value["evidence_id"]
    assert (
        client.get(f"/api/findings/{value['finding_id']}").json()["finding_id"]
        == value["finding_id"]
    )
    assert client.get("/api/findings/RIA-missing").status_code == 404


@pytest.mark.skipif(not GRAPH_URL, reason="RIA_TEST_FALKORDB_URL not set")
def test_knowledge_graph_links_citing_documents_and_dependent_clauses(client, tmp_path):
    import json

    from app.ria.seed import seed_file

    # A mock internal procedure that cites the regulation by number but shares no wording with it.
    mock = {
        "document": {
            "document_id": "DOC-901",
            "title": "Quy trình báo cáo định kỳ",
            "doc_type": "internal",
            "owner": "Khối Vận hành",
        },
        "document_version": {
            "version_id": "DOC-901@v1",
            "document_id": "DOC-901",
            "version_label": "v1",
            "status": "effective",
            "valid_from": "2026-07-01",
            "checksum": "sha256:test-doc-901",
        },
        "clause": [
            {
                "clause_id": "DOC-901@v1#1",
                "version_id": "DOC-901@v1",
                "parent_id": None,
                "numbering": "1",
                "text": "Căn cứ",
                "char_start": 0,
                "char_end": 6,
            },
            {
                "clause_id": "DOC-901@v1#1.1",
                "version_id": "DOC-901@v1",
                "parent_id": "DOC-901@v1#1",
                "numbering": "1.1",
                "text": "Quy trình này thực hiện Thông tư số 99/2026/TT-NHNN.",
                "char_start": 7,
                "char_end": 59,
            },
        ],
    }
    path = tmp_path / "DOC-901.parsed.json"
    path.write_text(json.dumps(mock, ensure_ascii=False), encoding="utf-8")
    seeded = seed_file(path)
    assert seeded["graph"]["cites"] >= 1

    reg = _regulation(client)
    job = _analyze(client, reg["regulation_id"])
    graph_info = job["result"]["graph"]
    assert graph_info["enabled"] and not graph_info.get("error")
    links = {(lk["document_id"], lk["relation"]) for lk in graph_info["linked_documents"]}
    assert ("DOC-901", "cites_regulation") in links
    # Same law in both preambles ("Căn cứ Luật Các tổ chức tín dụng").
    assert ("DOC-102", "shared_legal_basis") in links
    # DOC-102 Điều 12.2 refers to Điều 5 ("thời hạn tại Điều 5"): pulled in next to 5.2.
    assert graph_info["dependent_clauses_added"] > 0
    graph_findings = client.get(
        "/api/findings", params={"job_id": job["job_id"], "method": "graph"}
    ).json()["items"]
    doc901 = [f for f in graph_findings if f["impacted_document_id"] == "DOC-901"]
    assert doc901 and doc901[0]["priority"] == "high" and doc901[0]["obligation_id"] is None
    assert doc901[0]["internal_clause_id"] == "DOC-901@v1#1.1"


def _version_rows(version_id: str) -> dict:
    from app.db import get_engine

    counts = {
        "version": "SELECT count(*) FROM document_version WHERE version_id = :v",
        "clause": "SELECT count(*) FROM clause WHERE version_id = :v",
        "job": "SELECT count(*) FROM job WHERE version_id = :v",
        "finding": "SELECT count(*) FROM impact_finding WHERE regulation_version_id = :v",
    }
    with get_engine().connect() as conn:
        return {k: conn.execute(text(q), {"v": version_id}).scalar() for k, q in counts.items()}


def test_delete_failed_regulation_removes_everything_and_allows_reupload(client):
    from app.db import get_engine
    from tests.ria_fixtures import RIA_001_HTML, html_pdf

    # Own document number, so the other tests' regulation is untouched.
    pdf = html_pdf(RIA_001_HTML.replace("99/2026", "98/2026"))
    body = _upload(client, pdf).json()
    assert body["regulation_id"] == "REG-98-2026-TT-NHNN"
    version_id = body["version_id"]
    assert _wait(client, body["job_id"])["status"] == "succeeded"

    # Only failed documents can be deleted.
    response = client.delete(f"/api/regulations/{version_id}")
    assert response.status_code == 409, response.text

    job = _analyze(client, body["regulation_id"])
    assert _version_rows(version_id)["finding"] > 0
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE job SET status = 'failed' WHERE job_id = :j"), {"j": job["job_id"]}
        )
    row = next(r for r in client.get("/api/regulations").json() if r["version_id"] == version_id)
    assert row["status"] == "failed"

    response = client.delete(f"/api/regulations/{version_id}")
    assert response.status_code == 200, response.text
    assert response.json()["document_removed"] is True
    assert response.json()["warnings"] == []
    if GRAPH_URL:
        from app.ria import graph

        left = graph.query(
            "MATCH (n) WHERE n.id = $v OR n.version = $v OR n.id = $d RETURN count(n)",
            {"v": version_id, "d": body["regulation_id"]},
        )
        assert left[0][0] == 0
    assert _version_rows(version_id) == {"version": 0, "clause": 0, "job": 0, "finding": 0}
    assert all(r["version_id"] != version_id for r in client.get("/api/regulations").json())
    assert client.delete(f"/api/regulations/{version_id}").status_code == 404

    # Same bytes again: a fresh upload, not a duplicate of the deleted version.
    again = _upload(client, pdf)
    assert again.status_code == 202 and again.json()["duplicate"] is False
    # Let the parse finish: a job still running at shutdown is marked failed on the next start.
    assert _wait(client, again.json()["job_id"])["status"] == "succeeded"


def test_delete_regulation_whose_parse_failed(client):
    from app.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO document (document_id, title, doc_type, owner) VALUES "
                "('REG-BROKEN-TEST', 'broken', 'regulation', 'test')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO document_version (version_id, document_id, version_label, status, "
                "checksum, processing_status) VALUES ('REG-BROKEN-TEST@v1', 'REG-BROKEN-TEST', "
                "'v1', 'pending', 'sha256:broken-test', 'DRAFT')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO job (job_id, job_type, document_id, version_id, status) VALUES "
                "('JOB-broken-test', 'parse', 'REG-BROKEN-TEST', 'REG-BROKEN-TEST@v1', 'running')"
            )
        )
    # A job still running blocks the delete; the row is not failed yet either.
    assert client.delete("/api/regulations/REG-BROKEN-TEST@v1").status_code == 409
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE job SET status = 'failed' WHERE job_id = 'JOB-broken-test'"))
    row = next(
        r for r in client.get("/api/regulations").json() if r["version_id"] == "REG-BROKEN-TEST@v1"
    )
    assert (row["status"], row["error"]) == ("failed", "Đọc văn bản thất bại")

    assert client.delete("/api/regulations/REG-BROKEN-TEST@v1").status_code == 200
    assert _version_rows("REG-BROKEN-TEST@v1")["version"] == 0
