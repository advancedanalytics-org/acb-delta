import pytest

from tests.conftest import agent_impact


@pytest.fixture
def impacts(client, create_vbpl):
    vbpl = create_vbpl([agent_impact(), agent_impact(chunk_id="doc-cv-01:4:1")])
    return vbpl["id"], client.get(f"/api/vbpls/{vbpl['id']}/impacts").json()


def decide(client, impact_id, action, **extra):
    body = {"impactId": impact_id, "action": action, "reasonTags": [], "reviewerId": "rv-anh"}
    return client.post("/api/decisions", json=body | extra)


def impact_by_id(client, vbpl_id, impact_id):
    return next(
        i for i in client.get(f"/api/vbpls/{vbpl_id}/impacts").json() if i["id"] == impact_id
    )


def test_accept_uses_suggested_text(client, impacts):
    vbpl_id, [impact, _] = impacts

    response = decide(client, impact["id"], "accept", reasonTags=["đúng"])

    assert response.status_code == 201
    decision = response.json()
    assert set(decision) == {
        "id", "impactId", "vbplId", "documentId", "action", "reasonTags", "reviewer", "at",
    }  # fmt: skip
    assert decision["reviewer"] == {
        "id": "rv-anh", "name": "Nguyễn Minh Anh", "role": "Chuyên viên pháp chế",
        "canDelete": False,
    }  # fmt: skip
    after = impact_by_id(client, vbpl_id, impact["id"])
    assert after["status"] == "accepted"
    assert after["finalText"] == impact["suggestedText"]
    assert after["decision"]["id"] == decision["id"]


def test_edit_requires_text_and_becomes_final_text(client, impacts):
    vbpl_id, [impact, _] = impacts

    assert decide(client, impact["id"], "edit").status_code == 422
    assert decide(client, impact["id"], "edit", editedText="  ").status_code == 422
    response = decide(client, impact["id"], "edit", editedText="Tối đa 48 tháng.")

    assert response.status_code == 201
    assert response.json()["editedText"] == "Tối đa 48 tháng."
    after = impact_by_id(client, vbpl_id, impact["id"])
    assert (after["status"], after["finalText"]) == ("accepted", "Tối đa 48 tháng.")


def test_reject_has_no_final_text(client, impacts):
    vbpl_id, [impact, _] = impacts

    decide(client, impact["id"], "reject", editedText="ignored", reasonTags=["sai"])

    after = impact_by_id(client, vbpl_id, impact["id"])
    assert after["status"] == "rejected"
    assert "finalText" not in after
    assert "editedText" not in after["decision"]
    assert after["decision"]["reasonTags"] == ["sai"]


def test_latest_decision_wins_and_undo_restores_previous(client, impacts):
    vbpl_id, [impact, _] = impacts
    first = decide(client, impact["id"], "accept").json()
    second = decide(client, impact["id"], "reject").json()

    assert impact_by_id(client, vbpl_id, impact["id"])["decision"]["id"] == second["id"]

    assert client.delete(f"/api/decisions/{second['id']}").status_code == 204
    after = impact_by_id(client, vbpl_id, impact["id"])
    assert (after["status"], after["decision"]["id"]) == ("accepted", first["id"])

    assert client.delete(f"/api/decisions/{second['id']}").status_code == 404
    assert client.delete(f"/api/decisions/{first['id']}").status_code == 204
    after = impact_by_id(client, vbpl_id, impact["id"])
    assert after["status"] == "pending" and "decision" not in after


def test_vbpl_done_when_every_impact_decided(client, impacts):
    _, [one, two] = impacts

    decide(client, one["id"], "accept")
    [vbpl] = client.get("/api/vbpls").json()
    assert (vbpl["status"], vbpl["pendingCount"]) == ("awaiting_review", 1)

    decide(client, two["id"], "reject")
    [vbpl] = client.get("/api/vbpls").json()
    assert (vbpl["status"], vbpl["pendingCount"]) == ("done", 0)


def test_audit_lists_active_decisions_newest_first(client, impacts):
    _, [one, two] = impacts
    first = decide(client, one["id"], "accept").json()
    undone = decide(client, two["id"], "reject").json()
    last = decide(client, two["id"], "edit", editedText="Sửa tay.", reviewerId="rv-bao").json()
    client.delete(f"/api/decisions/{undone['id']}")

    audit = client.get("/api/audit").json()

    assert [e["id"] for e in audit] == [last["id"], first["id"]]
    entry = audit[0]
    assert entry["vbplNumber"] == "31/2026/TT-NHNN"
    assert entry["documentCode"] == "doc-cv-01"
    assert entry["originalText"] == two["affectedText"]
    assert entry["suggestedText"] == two["suggestedText"]
    assert entry["location"] == two["location"]
    assert entry["reviewer"]["id"] == "rv-bao"


def test_unknown_impact_or_reviewer_is_404(client, impacts):
    _, [impact, _] = impacts

    assert decide(client, "nope", "accept").status_code == 404
    assert decide(client, impact["id"], "accept", reviewerId="nobody").status_code == 404
    assert client.delete("/api/decisions/nope").status_code == 404


def test_reviewers_are_seeded(client):
    assert [r["id"] for r in client.get("/api/reviewers").json()] == ["rv-anh", "rv-bao"]
    # Only the department head may delete regulations.
    assert {r["id"]: r["canDelete"] for r in client.get("/api/reviewers").json()} == {
        "rv-anh": False,
        "rv-bao": True,
    }
