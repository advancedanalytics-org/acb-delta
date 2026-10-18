import pytest
from sqlalchemy import text

from app.db import get_engine
from app.routers.decisions import to_labels
from tests.conftest import agent_impact
from tests.test_decisions import decide


def test_to_labels():
    assert to_labels("accept", "old", "ai", None, True) == ("ai", None)
    assert to_labels("edit", "old", "ai", "human", True) == ("human", "ai")
    assert to_labels("reject", "old", "ai", None, True) == ("old", "ai")
    # No AI text to learn from when the draft failed.
    assert to_labels("edit", "old", "", "human", False) == ("human", None)
    assert to_labels("reject", "old", "", None, False) == ("old", None)
    assert to_labels("accept", "old", "", None, False) == (None, None)


@pytest.fixture
def four(client, create_vbpl):
    vbpl = create_vbpl([agent_impact(chunk_id=f"doc-cv-01:{n}:1") for n in range(4)])
    return vbpl["id"], client.get(f"/api/vbpls/{vbpl['id']}/impacts").json()


def feedback(client, **params) -> dict[str, dict]:
    response = client.get("/api/feedback", params=params)
    assert response.status_code == 200, response.text
    return {row["impactId"]: row for row in response.json()}


def test_feedback_labels_active_decisions_only(client, four):
    vbpl_id, [accepted, edited, rejected, undecided] = four
    decide(client, accepted["id"], "accept")
    decide(client, edited["id"], "edit", editedText="Tối đa 48 tháng.", reasonTags=["sai số"])
    decide(client, rejected["id"], "reject")

    rows = feedback(client, vbplId=vbpl_id)

    assert set(rows) == {accepted["id"], edited["id"], rejected["id"]}
    a, e, r = rows[accepted["id"]], rows[edited["id"]], rows[rejected["id"]]
    assert (a["action"], a["chosen"], a["rejected"]) == ("accept", accepted["suggestedText"], None)
    assert (e["chosen"], e["rejected"]) == ("Tối đa 48 tháng.", edited["suggestedText"])
    assert e["reasonTags"] == ["sai số"] and e["reviewerId"] == "rv-anh"
    assert (r["chosen"], r["rejected"]) == (rejected["affectedText"], rejected["suggestedText"])
    assert a["modelOutput"]["chunk_id"] == "doc-cv-01:0:1"
    # Rows from the /invoke path have no RIA fields.
    assert a["findingId"] is None and a["patch"] is None and a["draftStatus"] is None


def test_undone_decision_is_replaced_by_the_newer_one(client, four):
    vbpl_id, [impact, *_] = four
    first = decide(client, impact["id"], "accept").json()
    assert client.delete(f"/api/decisions/{first['id']}").status_code == 204
    decide(client, impact["id"], "edit", editedText="Bản người duyệt.")

    rows = feedback(client, vbplId=vbpl_id)

    assert list(rows) == [impact["id"]]
    assert rows[impact["id"]]["action"] == "edit"
    assert rows[impact["id"]]["chosen"] == "Bản người duyệt."


def test_undo_without_new_decision_drops_the_row(client, four):
    vbpl_id, [impact, *_] = four
    first = decide(client, impact["id"], "reject").json()
    client.delete(f"/api/decisions/{first['id']}")

    assert feedback(client, vbplId=vbpl_id) == {}


def test_failed_draft_has_no_rejected_text(client, four):
    vbpl_id, [impact, *_] = four
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE impacts SET draft_status = 'failed', suggested_text = '' WHERE id = :i"),
            {"i": impact["id"]},
        )
    decide(client, impact["id"], "edit", editedText="Bản người duyệt.")

    row = feedback(client, vbplId=vbpl_id)[impact["id"]]

    assert (row["chosen"], row["rejected"], row["draftStatus"]) == (
        "Bản người duyệt.",
        None,
        "failed",
    )


def test_since_filter(client, four):
    vbpl_id, [impact, *_] = four
    decision = decide(client, impact["id"], "accept").json()

    assert impact["id"] in feedback(client, since=decision["at"])
    assert feedback(client, since="2999-01-01T00:00:00Z") == {}


def test_audit_entries_carry_ria_fields_only_when_set(client, four):
    _, [impact, *_] = four
    decide(client, impact["id"], "accept")
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE impacts SET finding_id = 'RIA-1', category = 'VALUE_CHANGE' WHERE id = :i"
            ),
            {"i": impact["id"]},
        )

    entry = next(e for e in client.get("/api/audit").json() if e["impactId"] == impact["id"])

    assert (entry["findingId"], entry["category"]) == ("RIA-1", "VALUE_CHANGE")


def test_accept_without_ai_proposal_is_422(client, four):
    _, [impact, *_] = four
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE impacts SET draft_status = 'failed', suggested_text = '' WHERE id = :i"),
            {"i": impact["id"]},
        )

    assert decide(client, impact["id"], "accept").status_code == 422
    assert decide(client, impact["id"], "edit", editedText="Bản người duyệt.").status_code == 201


def test_rows_without_model_output_are_not_labels(client, four):
    vbpl_id, [impact, *_] = four
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE impacts SET model_output = '{}'::jsonb WHERE id = :i"), {"i": impact["id"]}
        )
    decide(client, impact["id"], "accept")

    assert feedback(client, vbplId=vbpl_id) == {}
