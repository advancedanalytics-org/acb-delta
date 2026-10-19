"""RIA analyze job → review package (vbpls + impacts with drafted patches).

Mapping helpers run everywhere. The flow tests need the disposable Postgres + pgvector of
`test_ria_api.py` (RIA_TEST_DATABASE_URL); HITL tables are created on that same DB at startup.
"""

import json
import os
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import agent_client, review_bridge
from tests.ria_fixtures import ria_001_pdf

DB_URL = os.environ.get("RIA_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB_URL, reason="RIA_TEST_DATABASE_URL not set")
DOC_102 = Path(__file__).resolve().parents[2] / "db" / "DOC-102.parsed.json"


# --- mapping, no DB ---


def test_page_and_boxes_keeps_the_first_page():
    bbox = [[2, 10, 20, 30, 40], [2, 10, 45, 30, 60], [3, 1, 2, 3, 4]]
    assert review_bridge.page_and_boxes(bbox) == (
        2,
        [[10.0, 20.0, 30.0, 40.0], [10.0, 45.0, 30.0, 60.0]],
    )
    assert review_bridge.page_and_boxes(None) == (None, [])


def _finding(**overrides) -> dict:
    clause = "5.2. Hồ sơ được rà soát định kỳ 24 tháng một lần."
    start = clause.index("24 tháng")
    finding = {
        "finding_id": "RIA-1", "job_id": "JOB-1", "obligation_id": "OBL-1", "evidence_id": "EV-1",
        "category": "VALUE_CHANGE", "rationale": "12 tháng thay vì 24 tháng.",
        "status": "AI_PROPOSED", "priority": "high", "confidence": 0.9,
        "source_span": {"text": "tối đa 12 tháng", "start": 0, "end": 15},
        "target_span": {"text": "24 tháng", "start": start, "end": start + 8},
        "verification": {}, "citations": ["REG-1@v1#2.1", "DOC-102@v4#5.2"], "method": "rule",
        "impacted_document_id": "DOC-102", "internal_clause_id": "DOC-102@v4#5.2",
        "obligation_text": "Phải rà soát tối đa 12 tháng.", "source_clause_id": "REG-1@v1#2.1",
        "regulation_numbering": "2.1", "regulation_number": "99/2026/TT-NHNN",
        "clause_numbering": "5.2", "clause_heading": None,
        "parent_heading": "Điều 5. Rà soát định kỳ", "clause_text": clause,
        "clause_bbox": [[1, 50, 100, 500, 112]], "score": 0.8,
    }  # fmt: skip
    return finding | overrides


def _proposal(f: dict, new_text: str = "tối đa 12 tháng", status: str = "review_required"):
    span = f["target_span"]
    return {
        "finding_id": f["finding_id"],
        "operation": "REPLACE",
        "start": span["start"] if status != "failed" else None,
        "end": span["end"] if status != "failed" else None,
        "old_text": span["text"] if status != "failed" else None,
        "new_text": new_text if status != "failed" else None,
        "verification": {
            "status": status,
            "reason": "span_unique: x" if status == "failed" else None,
        },
    }


def test_impact_row_maps_finding_and_patch():
    f = _finding()
    row = review_bridge.impact_row([f], 3, _proposal(f), None)
    assert row["patch"] == {
        "operation": "REPLACE", "start": f["target_span"]["start"], "end": f["target_span"]["end"],
        "old_text": "24 tháng", "new_text": "tối đa 12 tháng",
    }  # fmt: skip
    assert row["suggested_text"] == "5.2. Hồ sơ được rà soát định kỳ tối đa 12 tháng một lần."
    assert row["draft_status"] == "review_required" and row["draft_error"] is None
    assert (row["type"], row["severity"], row["category"]) == ("conflict", "high", "VALUE_CHANGE")
    assert row["location"] == "5.2. Điều 5. Rà soát định kỳ"
    assert row["change_clause"] == "Phải rà soát tối đa 12 tháng."
    assert row["citation"] == "99/2026/TT-NHNN, điều khoản 2.1"
    assert (row["page"], row["bboxes"]) == (1, [[50.0, 100.0, 500.0, 112.0]])
    assert row["model_output"]["finding"]["finding_id"] == "RIA-1"
    assert row["model_output"]["draft"]["new_text"] == "tối đa 12 tháng"


def test_impact_row_failed_and_skipped_drafts_have_no_patch():
    f = _finding()
    failed = review_bridge.impact_row([f], 0, _proposal(f, status="failed"), None)
    assert (failed["draft_status"], failed["draft_error"]) == ("failed", "span_unique: x")
    assert failed["patch"] is None and failed["suggested_text"] == ""
    agent_down = review_bridge.impact_row([f], 0, None, "Agent unreachable: ConnectError")
    assert agent_down["draft_status"] == "failed"
    skipped = review_bridge.impact_row([f], 0, None, review_bridge.SKIPPED + "no target_span")
    assert (skipped["draft_status"], skipped["draft_error"]) == ("skipped", "no target_span")


def test_findings_on_one_clause_become_one_group_led_by_the_first():
    a = _finding()
    b = _finding(finding_id="RIA-2", priority="medium")
    other = _finding(finding_id="RIA-3", internal_clause_id="DOC-102@v4#6.1")
    no_clause = _finding(finding_id="RIA-4", internal_clause_id=None)
    groups = review_bridge.group_by_clause([a, other, b, no_clause])
    assert [[g["finding_id"] for g in group] for group in groups] == [
        ["RIA-1", "RIA-2"], ["RIA-3"], ["RIA-4"],
    ]  # fmt: skip


def test_merged_span_covers_every_target_span():
    a = _finding()
    clause = a["clause_text"]
    start = clause.index("định kỳ")
    b = _finding(
        finding_id="RIA-2", target_span={"text": "định kỳ", "start": start, "end": start + 7}
    )
    assert review_bridge.merged_span([a]) == a["target_span"]
    span = review_bridge.merged_span([a, b])
    assert span["start"] == start and span["end"] == a["target_span"]["end"]
    assert span["text"] == clause[span["start"] : span["end"]] == "định kỳ 24 tháng"
    assert review_bridge.merged_span([_finding(target_span=None)]) is None


def test_draft_request_sends_related_findings():
    a = _finding()
    b = _finding(
        finding_id="RIA-2", category="SCOPE_CHANGE", rationale="Cả khách hàng tổ chức.",
        obligation_text="Áp dụng cho khách hàng tổ chức.", source_clause_id="REG-1@v1#2.3",
        citations=["REG-1@v1#2.3", "DOC-102@v4#5.2"],
    )  # fmt: skip
    request = review_bridge.draft_request([a, b])
    assert request["finding_id"] == "RIA-1"
    assert request["citations"] == ["REG-1@v1#2.1", "DOC-102@v4#5.2", "REG-1@v1#2.3"]
    assert request["related_findings"] == [
        {
            "finding_id": "RIA-2", "category": "SCOPE_CHANGE",
            "rationale": "Cả khách hàng tổ chức.",
            "obligation": {"clause_id": "REG-1@v1#2.3", "text": "Áp dụng cho khách hàng tổ chức."},
        }
    ]  # fmt: skip
    assert review_bridge.draft_request([a])["related_findings"] == []


def test_impact_row_of_a_group_shows_every_obligation():
    a = _finding()
    b = _finding(
        finding_id="RIA-2", priority="medium", rationale="Cả khách hàng tổ chức.",
        obligation_text="Áp dụng cho khách hàng tổ chức.", regulation_numbering="2.3",
    )  # fmt: skip
    row = review_bridge.impact_row([a, b], 0, _proposal(a), None)
    assert row["finding_id"] == "RIA-1" and row["severity"] == "high"
    assert (
        row["change_clause"] == "Phải rà soát tối đa 12 tháng.\n\nÁp dụng cho khách hàng tổ chức."
    )
    assert row["reasoning"] == "12 tháng thay vì 24 tháng.\n\nCả khách hàng tổ chức."
    assert row["citation"] == "99/2026/TT-NHNN, điều khoản 2.1, 2.3"
    assert row["model_output"]["finding"]["finding_id"] == "RIA-1"
    assert [f["finding_id"] for f in row["model_output"]["related_findings"]] == ["RIA-2"]
    assert review_bridge.impact_row([a], 0, None, None)["model_output"]["related_findings"] == []


def test_invalid_proposal():
    f = _finding()
    good = _proposal(f)
    clause = f["clause_text"]
    assert review_bridge.invalid_proposal(clause, good) is None
    assert review_bridge.invalid_proposal(clause, _proposal(f, status="failed")) is None
    assert review_bridge.invalid_proposal(clause, good | {"operation": "replace"})
    assert review_bridge.invalid_proposal(clause, good | {"start": None})
    assert review_bridge.invalid_proposal(clause, good | {"end": 999})
    assert review_bridge.invalid_proposal(clause, good | {"old_text": "36 tháng"})
    assert review_bridge.invalid_proposal(clause, {"operation": "REPLACE"})
    assert review_bridge.invalid_proposal(clause, ["not", "a", "dict"])


def test_category_types():
    assert review_bridge.TYPE_BY_CATEGORY["ADDITION"] == "new_obligation"
    assert review_bridge.TYPE_BY_CATEGORY["INDIRECT_IMPACT"] == "outdated_reference"
    assert "EQUIVALENT" not in review_bridge.TYPE_BY_CATEGORY


# --- full flow on Postgres ---


class FakeDrafter:
    """Agent /draft stand-in: REPLACE target_span with "<span> (mới)"; can fail chosen findings."""

    def __init__(self):
        self.fail_ids: set[str] = set()
        # Findings answered 200 with a patch the backend must refuse.
        self.malformed_ids: set[str] = set()
        self.requests: list[dict] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if body["finding_id"] in self.fail_ids:
            return httpx.Response(500, text="agent exploded")
        span = body["target_span"]
        if body["finding_id"] in self.malformed_ids:
            return httpx.Response(
                200, json={"operation": "replace", "verification": {"status": "review_required"}}
            )
        if "24 tháng" in span["text"]:
            new_text = span["text"].replace("24 tháng", "12 tháng")
        else:
            new_text = span["text"] + " (mới)"
        return httpx.Response(
            200,
            json={
                "finding_id": body["finding_id"],
                "clause_id": body["clause"]["clause_id"],
                "operation": "REPLACE",
                "start": span["start"],
                "end": span["end"],
                "old_text": span["text"],
                "new_text": new_text,
                "rationale": "test",
                "legal_evidence_ids": [body["obligation"]["clause_id"]],
                "verification": {"status": "review_required", "reason": None, "checks": []},
                "model": "fake",
                "prompt_version": "test",
            },
        )


@pytest.fixture
def drafter(monkeypatch) -> FakeDrafter:
    fake = FakeDrafter()
    monkeypatch.setattr(
        agent_client,
        "http_client",
        lambda: httpx.Client(base_url="http://agent", transport=httpx.MockTransport(fake.handle)),
    )
    return fake


def _reset_caches():
    from app.config import get_settings
    from app.db import get_engine, get_sessionmaker
    from app.ria import schema, storage

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    storage.get_storage.cache_clear()
    schema._ready = False


@pytest.fixture(scope="module")
def ria_client(tmp_path_factory):
    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", DB_URL)
    patch.setenv("STORAGE_BACKEND", "local")
    patch.setenv("STORAGE_LOCAL_DIR", str(tmp_path_factory.mktemp("storage")))
    for name in ("EMBEDDING_BASE_URL", "OPENAI_BASE_URL", "LLM_MODEL", "RERANK_BASE_URL"):
        patch.setenv(name, "")
    _reset_caches()
    from app.main import create_app
    from app.ria.schema import ensure_schema
    from app.ria.seed import seed_file

    ensure_schema()
    seed_file(DOC_102)
    with TestClient(create_app()) as client:  # lifespan creates the HITL tables on this DB
        yield client
    from app.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE vbpls, impacts, decisions CASCADE"))
    patch.undo()
    _reset_caches()


def _wait(client, job_id: str, timeout: float = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.2)
    raise TimeoutError(job_id)


def _analyze(client) -> str:
    """A fresh analyze job on the RIA-001 regulation (rules only: no LLM configured)."""
    body = client.post(
        "/api/regulations", files={"file": ("tt-99.pdf", ria_001_pdf(), "application/pdf")}
    ).json()
    assert _wait(client, body["job_id"])["status"] == "succeeded"
    started = client.post(f"/api/regulations/{body['regulation_id']}/analyze", json={})
    job = _wait(client, started.json()["job_id"])
    assert job["status"] == "succeeded", job["error"]
    return job["job_id"]


def _findings(job_id: str) -> list[dict]:
    from app.db import get_engine

    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT finding_id, category, status FROM impact_finding WHERE job_id = :j"),
            {"j": job_id},
        ).mappings()
        return [dict(r) for r in rows]


@needs_db
def test_review_package_from_analyze_job(ria_client, drafter):
    job_id = _analyze(ria_client)
    findings = _findings(job_id)
    proposed = [f for f in findings if f["status"] == "AI_PROPOSED"]

    started = ria_client.post(f"/api/analyses/{job_id}/review")
    assert started.status_code == 202, started.text
    body = started.json()
    review = _wait(ria_client, body["review_job_id"])
    assert review["status"] == "succeeded", review["error"]
    assert review["result"]["findings"] == len(proposed)

    vbpl = next(v for v in ria_client.get("/api/vbpls").json() if v["id"] == body["vbpl_id"])
    assert vbpl["number"] == "99/2026/TT-NHNN"
    assert vbpl["status"] == "awaiting_review" and vbpl["impactCount"] == len(proposed)

    impacts = ria_client.get(f"/api/vbpls/{body['vbpl_id']}/impacts").json()
    # EQUIVALENT findings are NO_ACTION_PROPOSED and not imported.
    assert {i["findingId"] for i in impacts} == {f["finding_id"] for f in proposed}
    assert all(i["category"] != "EQUIVALENT" for i in impacts)
    value_change = next(i for i in impacts if i["category"] == "VALUE_CHANGE")
    patch = value_change["patch"]
    assert patch["operation"] == "REPLACE" and patch["oldText"] == "24 tháng"
    assert value_change["affectedText"][patch["start"] : patch["end"]] == "24 tháng"
    assert "12 tháng" in value_change["suggestedText"]
    assert value_change["draftStatus"] == "review_required"
    assert value_change["status"] == "pending" and value_change["type"] == "conflict"
    # The review decision API works unchanged on these rows.
    decided = ria_client.post(
        "/api/decisions",
        json={"impactId": value_change["id"], "action": "accept", "reviewerId": "rv-anh"},
    )
    assert decided.status_code == 201

    # Second call: same package, no new job, no new drafts.
    sent = len(drafter.requests)
    again = ria_client.post(f"/api/analyses/{job_id}/review")
    assert again.status_code == 200
    assert again.json() == body
    assert len(drafter.requests) == sent


def _second_finding_on_clause_of(job_id: str, lead: dict, other: dict) -> str:
    """Copy `other` (another obligation) onto `lead`'s clause, as RIA does when two obligations
    of the regulation hit one internal clause. Returns the new finding id."""
    from app.db import get_engine

    finding_id = f"RIA-same-{job_id}"
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO impact_finding (finding_id, job_id, regulation_version_id, "
                "impacted_document_id, internal_clause_id, obligation_id, evidence_id, category, "
                "rationale, status, priority, confidence, source_span, target_span, citations, "
                "method) SELECT :id, job_id, regulation_version_id, "
                "l.impacted_document_id, l.internal_clause_id, o.obligation_id, o.evidence_id, "
                "o.category, o.rationale, o.status, 'low', o.confidence, o.source_span, "
                "l.target_span, o.citations, o.method "
                "FROM impact_finding o, (SELECT impacted_document_id, internal_clause_id, "
                "target_span FROM impact_finding WHERE finding_id = :lead) l "
                "WHERE o.finding_id = :other"
            ),
            {"id": finding_id, "lead": lead["finding_id"], "other": other["finding_id"]},
        )
    return finding_id


@needs_db
def test_findings_on_one_clause_become_one_impact(ria_client, drafter):
    job_id = _analyze(ria_client)
    proposed = [f for f in _findings(job_id) if f["status"] == "AI_PROPOSED"]
    lead = next(f for f in proposed if f["category"] == "VALUE_CHANGE")
    other = next(f for f in proposed if f["finding_id"] != lead["finding_id"])
    extra = _second_finding_on_clause_of(job_id, lead, other)

    # Before the package exists the inbox already counts one impact per clause.
    inbox = next(
        r
        for r in ria_client.get("/api/regulations").json()
        if r["document_id"] == "REG-99-2026-TT-NHNN"
    )
    assert inbox["impact_count"] == len(proposed)

    body = ria_client.post(f"/api/analyses/{job_id}/review").json()
    review = _wait(ria_client, body["review_job_id"])
    assert review["status"] == "succeeded", review["error"]
    assert review["result"]["findings"] == len(proposed) + 1
    assert review["result"]["impacts"] == len(proposed)

    impacts = ria_client.get(f"/api/vbpls/{body['vbpl_id']}/impacts").json()
    assert len(impacts) == len(proposed)
    assert extra not in {i["findingId"] for i in impacts}
    merged = next(i for i in impacts if i["findingId"] == lead["finding_id"])
    other_impact = next(i for i in impacts if i["findingId"] == other["finding_id"])
    # Both obligations are on the one impact, and the agent drafted one patch for both.
    assert other_impact["changeClause"] in merged["changeClause"]
    assert merged["changeClause"] != other_impact["changeClause"]
    sent = next(r for r in drafter.requests if r["finding_id"] == lead["finding_id"])
    assert [r["finding_id"] for r in sent["related_findings"]] == [extra]
    assert merged["patch"]["oldText"] == "24 tháng"

    # A rerun finds every finding of the group stored and drafts nothing.
    count = len(drafter.requests)
    assert ria_client.post(f"/api/analyses/{job_id}/review").status_code == 200
    assert len(drafter.requests) == count


@needs_db
def test_one_failed_draft_does_not_fail_the_package(ria_client, drafter):
    job_id = _analyze(ria_client)
    proposed = [f for f in _findings(job_id) if f["status"] == "AI_PROPOSED"]
    broken = next(f for f in proposed if f["category"] == "VALUE_CHANGE")
    drafter.fail_ids = {broken["finding_id"]}

    body = ria_client.post(f"/api/analyses/{job_id}/review").json()
    assert _wait(ria_client, body["review_job_id"])["status"] == "succeeded"

    impacts = {
        i["findingId"]: i for i in ria_client.get(f"/api/vbpls/{body['vbpl_id']}/impacts").json()
    }
    assert len(impacts) == len(proposed)
    failed = impacts[broken["finding_id"]]
    assert failed["draftStatus"] == "failed" and "Agent HTTP 500" in failed["draftError"]
    assert "patch" not in failed and failed["suggestedText"] == ""
    others = [i for fid, i in impacts.items() if fid != broken["finding_id"]]
    assert all(i["draftStatus"] == "review_required" for i in others)
    vbpl = next(v for v in ria_client.get("/api/vbpls").json() if v["id"] == body["vbpl_id"])
    assert vbpl["status"] == "awaiting_review"


@needs_db
def test_rerun_after_failed_review_job_redrafts_only_failed(ria_client, drafter):
    from app.db import get_engine

    job_id = _analyze(ria_client)
    proposed = [f for f in _findings(job_id) if f["status"] == "AI_PROPOSED"]
    broken = proposed[0]["finding_id"]
    drafter.fail_ids = {broken}
    first = ria_client.post(f"/api/analyses/{job_id}/review").json()
    assert _wait(ria_client, first["review_job_id"])["status"] == "succeeded"
    # Simulate a package-level failure (e.g. the API restarted mid-run).
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE job SET status = 'failed' WHERE job_id = :j"),
            {"j": first["review_job_id"]},
        )

    drafter.fail_ids = set()
    sent = len(drafter.requests)
    second = ria_client.post(f"/api/analyses/{job_id}/review")
    assert second.status_code == 202
    assert second.json()["vbpl_id"] == first["vbpl_id"]
    assert _wait(ria_client, second.json()["review_job_id"])["status"] == "succeeded"

    assert [r["finding_id"] for r in drafter.requests[sent:]] == [broken]
    impacts = ria_client.get(f"/api/vbpls/{first['vbpl_id']}/impacts").json()
    assert len(impacts) == len(proposed)
    assert all(i["draftStatus"] == "review_required" for i in impacts)


@needs_db
def test_review_rejects_unknown_and_non_analyze_jobs(ria_client):
    assert ria_client.post("/api/analyses/JOB-nope/review").status_code == 404
    body = ria_client.post(
        "/api/regulations", files={"file": ("tt-99.pdf", ria_001_pdf(), "application/pdf")}
    ).json()
    parse_job = body["job_id"]
    if parse_job:
        assert ria_client.post(f"/api/analyses/{parse_job}/review").status_code == 404


@needs_db
def test_review_of_unfinished_analyze_job_is_409(ria_client):
    from app.db import get_engine

    job_id = _analyze(ria_client)

    def set_status(status: str) -> None:
        with get_engine().begin() as conn:
            conn.execute(
                text("UPDATE job SET status = :s WHERE job_id = :j"), {"s": status, "j": job_id}
            )

    set_status("running")
    try:
        assert ria_client.post(f"/api/analyses/{job_id}/review").status_code == 409
    finally:
        # A 'running' analyze job is reused by the next analyze call on this regulation.
        set_status("succeeded")


@needs_db
def test_malformed_agent_reply_fails_only_that_finding(ria_client, drafter):
    job_id = _analyze(ria_client)
    proposed = [f for f in _findings(job_id) if f["status"] == "AI_PROPOSED"]
    bad = proposed[0]["finding_id"]
    drafter.malformed_ids = {bad}

    body = ria_client.post(f"/api/analyses/{job_id}/review").json()
    assert _wait(ria_client, body["review_job_id"])["status"] == "succeeded"

    response = ria_client.get(f"/api/vbpls/{body['vbpl_id']}/impacts")
    assert response.status_code == 200
    impacts = {i["findingId"]: i for i in response.json()}
    assert impacts[bad]["draftStatus"] == "failed"
    assert impacts[bad]["draftError"].startswith("Agent reply invalid")
    assert sum(i["draftStatus"] == "review_required" for i in impacts.values()) == len(proposed) - 1


@needs_db
def test_rerun_keeps_a_failed_draft_that_was_already_decided(ria_client, drafter):
    from app.db import get_engine

    job_id = _analyze(ria_client)
    broken = next(f for f in _findings(job_id) if f["status"] == "AI_PROPOSED")["finding_id"]
    drafter.fail_ids = {broken}
    first = ria_client.post(f"/api/analyses/{job_id}/review").json()
    assert _wait(ria_client, first["review_job_id"])["status"] == "succeeded"
    impacts = ria_client.get(f"/api/vbpls/{first['vbpl_id']}/impacts").json()
    failed = next(i for i in impacts if i["findingId"] == broken)
    decided = ria_client.post(
        "/api/decisions",
        json={"impactId": failed["id"], "action": "reject", "reviewerId": "rv-anh"},
    )
    assert decided.status_code == 201
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE job SET status = 'failed' WHERE job_id = :j"),
            {"j": first["review_job_id"]},
        )

    drafter.fail_ids = set()
    second = ria_client.post(f"/api/analyses/{job_id}/review").json()
    assert _wait(ria_client, second["review_job_id"])["status"] == "succeeded"

    after = next(
        i
        for i in ria_client.get(f"/api/vbpls/{first['vbpl_id']}/impacts").json()
        if i["findingId"] == broken
    )
    # What the reviewer decided on is kept as it was, decision included.
    assert after["id"] == failed["id"] and after["draftStatus"] == "failed"
    assert after["status"] == "rejected"


@needs_db
def test_infra_failure_fails_the_package_without_leaking_details(ria_client, drafter, monkeypatch):
    job_id = _analyze(ria_client)

    def broken_store(*args, **kwargs):
        raise RuntimeError("INSERT INTO impacts ... secret clause text")

    monkeypatch.setattr(review_bridge, "_store", broken_store)
    body = ria_client.post(f"/api/analyses/{job_id}/review").json()
    job = _wait(ria_client, body["review_job_id"])

    assert job["status"] == "failed"
    assert "secret" not in job["error"] and "INSERT" not in job["error"]
    vbpl = next(v for v in ria_client.get("/api/vbpls").json() if v["id"] == body["vbpl_id"])
    assert vbpl["status"] == "failed" and vbpl["error"] == "Internal error: RuntimeError"


@needs_db
def test_startup_fails_packages_whose_review_job_died(ria_client):
    from app.db import get_engine

    job_id = _analyze(ria_client)
    # A package left processing with no live review job, as after a crash.
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vbpls (id, number, title, issuer, issued_date, effective_date, "
                "summary, text, status, ria_job_id) VALUES ('vbpl-orphan', 'n', 't', 'i', "
                "'2026-01-01', '2026-01-01', '', '', 'processing', :j)"
            ),
            {"j": job_id},
        )

    review_bridge.fail_interrupted_packages()

    vbpl = next(v for v in ria_client.get("/api/vbpls").json() if v["id"] == "vbpl-orphan")
    assert vbpl["status"] == "failed" and vbpl["error"] == "interrupted by API restart"


@needs_db
def test_regulation_review_endpoint_and_inbox_counts(ria_client, drafter):
    job_id = _analyze(ria_client)
    proposed = [f for f in _findings(job_id) if f["status"] == "AI_PROPOSED"]

    started = ria_client.post("/api/regulations/REG-99-2026-TT-NHNN/review")
    assert started.status_code in (200, 202), started.text
    body = started.json()
    assert _wait(ria_client, body["review_job_id"])["status"] == "succeeded"
    # Latest finished analysis → the package of that job.
    assert body == ria_client.post(f"/api/analyses/{job_id}/review").json()

    inbox = next(
        r
        for r in ria_client.get("/api/regulations").json()
        if r["document_id"] == "REG-99-2026-TT-NHNN"
    )
    assert inbox["vbpl_id"] == body["vbpl_id"]
    assert inbox["status"] == "awaiting_review"
    assert inbox["impact_count"] == inbox["pending_count"] == len(proposed)

    impacts = ria_client.get(f"/api/vbpls/{body['vbpl_id']}/impacts").json()
    for impact in impacts:
        decided = ria_client.post(
            "/api/decisions",
            json={"impactId": impact["id"], "action": "reject", "reviewerId": "rv-anh"},
        )
        assert decided.status_code == 201
    inbox = next(
        r
        for r in ria_client.get("/api/regulations").json()
        if r["document_id"] == "REG-99-2026-TT-NHNN"
    )
    assert (inbox["status"], inbox["pending_count"]) == ("done", 0)

    assert ria_client.post("/api/regulations/REG-NOPE/review").status_code == 404


@needs_db
def test_decision_on_a_raw_finding_id_is_404(ria_client):
    job_id = _analyze(ria_client)
    finding = _findings(job_id)[0]["finding_id"]
    response = ria_client.post(
        "/api/decisions",
        json={"impactId": finding, "action": "accept", "reviewerId": "rv-anh"},
    )
    assert response.status_code == 404


@needs_db
def test_auto_start_builds_the_package_after_analysis(ria_client, drafter, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "review_auto_start", True)
    job_id = _analyze(ria_client)
    proposed = [f for f in _findings(job_id) if f["status"] == "AI_PROPOSED"]

    # Already started by the analyze job: the POST finds it.
    again = ria_client.post(f"/api/analyses/{job_id}/review")
    assert again.status_code == 200, again.text
    body = again.json()
    assert _wait(ria_client, body["review_job_id"])["status"] == "succeeded"
    impacts = ria_client.get(f"/api/vbpls/{body['vbpl_id']}/impacts").json()
    assert {i["findingId"] for i in impacts} == {f["finding_id"] for f in proposed}


@needs_db
def test_inbox_and_review_while_analysis_runs_or_fails(ria_client):
    from app.db import get_engine

    job_id = _analyze(ria_client)
    with get_engine().begin() as conn:
        # Newest analyze job of the version: still running, then failed; no package for it.
        conn.execute(
            text(
                "UPDATE job SET status = 'running', created_at = now() + interval '1 day' "
                "WHERE job_id = :j"
            ),
            {"j": job_id},
        )
        conn.execute(text("DELETE FROM vbpls WHERE ria_job_id IS NOT NULL"))
        conn.execute(
            text("UPDATE job SET status = 'failed' WHERE job_type = 'analyze' AND job_id <> :j"),
            {"j": job_id},
        )
    try:
        assert ria_client.post("/api/regulations/REG-99-2026-TT-NHNN/review").status_code == 409
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE job SET status = 'failed' WHERE job_id = :j"), {"j": job_id})
        row = next(
            r
            for r in ria_client.get("/api/regulations").json()
            if r["document_id"] == "REG-99-2026-TT-NHNN"
        )
        assert row["status"] == "failed" and row["error"]
    finally:
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE job SET status = 'succeeded' WHERE job_type = 'analyze'"))
