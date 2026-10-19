from tests.conftest import VBPL, agent_impact


def test_create_runs_agent_and_stores_pending_impacts(client, agent, create_vbpl):
    created = create_vbpl([agent_impact(), agent_impact(chunk_id="doc-cv-01:4:1", page=2)])

    assert created["status"] == "processing"
    assert created["number"] == VBPL["number"]
    assert agent.requests[0].read().decode().count("Điều 9") == 1

    [vbpl] = client.get("/api/vbpls").json()
    assert vbpl["id"] == created["id"]
    assert (vbpl["status"], vbpl["impactCount"], vbpl["pendingCount"]) == ("awaiting_review", 2, 2)
    assert set(vbpl) == {
        "id", "number", "title", "issuer", "issuedDate", "effectiveDate", "receivedAt", "summary",
        "status", "impactCount", "pendingCount",
    }  # fmt: skip

    impacts = client.get(f"/api/vbpls/{created['id']}/impacts").json()
    assert [i["status"] for i in impacts] == ["pending", "pending"]
    first = impacts[0]
    assert set(first) == {
        "id", "vbplId", "documentId", "location", "changeClause", "citation", "affectedText",
        "page", "bboxes", "type", "severity", "reasoning", "suggestedText", "status",
    }  # fmt: skip
    assert first["documentId"] == "doc-cv-01"
    assert first["page"] is None and first["bboxes"] == []
    assert impacts[1]["page"] == 2


def test_no_impacts_means_not_found(client, create_vbpl):
    create_vbpl([])

    [vbpl] = client.get("/api/vbpls").json()
    assert (vbpl["status"], vbpl["impactCount"]) == ("not_found", 0)


def test_agent_error_marks_vbpl_failed(client, agent, create_vbpl):
    agent.status_code = 503

    created = create_vbpl()

    [vbpl] = client.get("/api/vbpls").json()
    assert vbpl["status"] == "failed"
    assert vbpl["error"].startswith("Agent HTTP 503")
    assert client.get(f"/api/vbpls/{created['id']}/impacts").json() == []


def test_create_requires_text(client):
    assert client.post("/api/vbpls", json=VBPL | {"text": ""}).status_code == 422


def test_unknown_vbpl_impacts_is_404(client):
    assert client.get("/api/vbpls/nope/impacts").status_code == 404
