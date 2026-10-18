"""Which reviewer decision teaches which step, and what a DPO pair may contain.

The mapping is the substance of KHOA-02: an `edit` corrects the drafter, a `reject` corrects the
judge. Getting it backwards would train each step on the other's mistakes, and nothing downstream
would notice.
"""

import json

import pytest

from app.evaluation import dpo, feedback
from tests.conftest import agent_impact
from tests.test_decisions import decide


@pytest.fixture
def four(client, create_vbpl):
    vbpl = create_vbpl([agent_impact(chunk_id=f"doc-cv-01:{n}:1") for n in range(4)])
    return vbpl["id"], client.get(f"/api/vbpls/{vbpl['id']}/impacts").json()


@pytest.fixture
def reviewed(client, four):
    """One of each verdict, so every branch of the mapping has a row."""
    vbpl_id, impacts = four
    accepted, edited, rejected, _ = impacts
    decide(client, accepted["id"], "accept")
    decide(client, edited["id"], "edit", editedText="Tối đa 12 tháng.", reasonTags=["Sai số liệu"])
    decide(client, rejected["id"], "reject", reasonTags=["Không liên quan"])
    return vbpl_id, {"accept": accepted, "edit": edited, "reject": rejected}


def test_draft_examples_learn_from_text_verdicts_only(client, reviewed):
    vbpl_id, by_action = reviewed

    body = client.get("/api/eval/examples", params={"task": "draft", "vbplId": vbpl_id})
    assert body.status_code == 200, body.text
    data = body.json()

    positive = {e["impactId"] for e in data["positive"]}
    negative = {e["impactId"] for e in data["negative"]}
    # Accept and edit both say what the text should be.
    assert positive == {by_action["accept"]["id"], by_action["edit"]["id"]}
    # Only the edit shows a draft the reviewer had to fix. A reject is not a drafter error: the
    # text was fine to draft, the finding behind it was wrong.
    assert negative == {by_action["edit"]["id"]}


def test_judge_examples_learn_from_whether_the_finding_was_real(client, reviewed):
    vbpl_id, by_action = reviewed

    data = client.get("/api/eval/examples", params={"task": "judge", "vbplId": vbpl_id}).json()

    positive = {e["impactId"] for e in data["positive"]}
    negative = {e["impactId"] for e in data["negative"]}
    assert positive == {by_action["accept"]["id"], by_action["edit"]["id"]}
    # The reject is the judge's mistake, and only the judge's.
    assert negative == {by_action["reject"]["id"]}


def test_a_failed_draft_teaches_the_judge_but_not_the_drafter(client, create_vbpl):
    vbpl = create_vbpl([agent_impact(chunk_id="doc-cv-01:9:1", suggested_text="")])
    impact = client.get(f"/api/vbpls/{vbpl['id']}/impacts").json()[0]
    with_engine_draft_status(impact["id"], "failed")
    decide(client, impact["id"], "reject", reasonTags=["Không liên quan"])

    draft = client.get("/api/eval/examples", params={"task": "draft"}).json()
    judge = client.get("/api/eval/examples", params={"task": "judge"}).json()

    # No AI text exists, so there is nothing for the drafter to imitate or avoid.
    assert impact["id"] not in {e["impactId"] for e in draft["positive"] + draft["negative"]}
    # The finding still existed and the reviewer rejected it: that is a judge label.
    assert impact["id"] in {e["impactId"] for e in judge["negative"]}


def with_engine_draft_status(impact_id: str, value: str) -> None:
    """The fake agent cannot fail a draft, so set the column the way review_bridge would."""
    from sqlalchemy import text

    from app.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE impacts SET draft_status = :v WHERE id = :i"),
            {"v": value, "i": impact_id},
        )


def test_newest_decisions_come_first(client, four):
    vbpl_id, impacts = four
    for impact in impacts[:3]:
        decide(client, impact["id"], "accept")

    data = client.get(
        "/api/eval/examples", params={"task": "draft", "vbplId": vbpl_id, "limit": 2}
    ).json()

    # A dynamic few-shot prompt should carry the latest corrections, not the first ever made.
    assert [e["impactId"] for e in data["positive"]] == [impacts[2]["id"], impacts[1]["id"]]
    assert data["counts"]["positive_available"] == 3


def test_counts_make_a_thin_prompt_visible(client, four):
    vbpl_id, _ = four

    data = client.get("/api/eval/examples", params={"vbplId": vbpl_id}).json()

    assert data["positive"] == [] and data["negative"] == []
    # Zero decisions read is different from decisions read that did not qualify.
    assert data["counts"] == {
        "decisions_read": 0,
        "positive_available": 0,
        "negative_available": 0,
    }


def test_unknown_task_is_rejected(client):
    assert client.get("/api/eval/examples", params={"task": "nope"}).status_code == 422


def test_dpo_export_keeps_only_pairs_that_contrast_two_texts(client, reviewed, tmp_path):
    from app.db import get_sessionmaker

    vbpl_id, by_action = reviewed
    out = tmp_path / "pairs.jsonl"

    with get_sessionmaker()() as session:
        written = dpo.write_jsonl(session, out, vbpl_id=vbpl_id)

    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert written == 2
    # The accept is absent: the reviewer took the AI text, so no alternative was rejected.
    assert {line["meta"]["impact_id"] for line in lines} == {
        by_action["edit"]["id"],
        by_action["reject"]["id"],
    }
    assert all(line["chosen"] and line["rejected"] for line in lines)
    edit_pair = next(line for line in lines if line["meta"]["impact_id"] == by_action["edit"]["id"])
    assert edit_pair["chosen"] == "Tối đa 12 tháng."
    assert edit_pair["meta"]["reason_tags"] == ["Sai số liệu"]


def test_example_set_rejects_an_unknown_task_in_python_too():
    with pytest.raises(ValueError, match="Unknown task"):
        feedback.example_set(None, "translate")
