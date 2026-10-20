"""The DPO long loop runs on its own once enough feedback exists (KHOA-02, vòng dài).

Readiness is counted from the same decisions the few-shot examples use, and a dataset is only
written past the threshold: a half-empty preference set is worse than none.
"""

import json

import pytest

from app.db import get_sessionmaker
from app.evaluation import dpo_pipeline
from tests.conftest import agent_impact
from tests.test_decisions import decide


@pytest.fixture
def four(client, create_vbpl):
    vbpl = create_vbpl([agent_impact(chunk_id=f"doc-cv-01:{n}:1") for n in range(4)])
    return vbpl["id"], client.get(f"/api/vbpls/{vbpl['id']}/impacts").json()


@pytest.fixture
def reviewed(client, four):
    """accept + edit + reject, so each branch of the chosen/rejected mapping has a row."""
    vbpl_id, impacts = four
    accepted, edited, rejected, _ = impacts
    decide(client, accepted["id"], "accept")
    decide(client, edited["id"], "edit", editedText="Tối đa 12 tháng.", reasonTags=["Sai số liệu"])
    decide(client, rejected["id"], "reject", reasonTags=["Không liên quan"])
    return vbpl_id


def status_for(vbpl_id, min_pairs):
    with get_sessionmaker()() as session:
        return dpo_pipeline.feedback_status(session, min_pairs=min_pairs, vbpl_id=vbpl_id)


def test_status_counts_only_two_text_pairs(reviewed):
    status = status_for(reviewed, min_pairs=2)

    assert status.decisions_read == 3
    assert status.by_action == {"accept": 1, "edit": 1, "reject": 1}
    # edit and reject each contrast two texts; accept took the AI text, so no rejected side.
    assert status.pairs_usable == 2
    assert status.draft_failures == 0


def test_ready_flips_at_the_threshold(reviewed):
    assert status_for(reviewed, min_pairs=2).ready is True
    assert status_for(reviewed, min_pairs=3).ready is False


def test_status_example_counts_match_the_served_examples(client, reviewed):
    status = status_for(reviewed, min_pairs=2)

    draft = client.get("/api/eval/examples", params={"task": "draft", "vbplId": reviewed}).json()
    judge = client.get("/api/eval/examples", params={"task": "judge", "vbplId": reviewed}).json()

    assert status.draft_examples.positive_available == draft["counts"]["positive_available"]
    assert status.draft_examples.negative_available == draft["counts"]["negative_available"]
    assert status.judge_examples.positive_available == judge["counts"]["positive_available"]
    assert status.judge_examples.negative_available == judge["counts"]["negative_available"]


def test_endpoint_serves_status_in_camel_case(client, reviewed):
    body = client.get("/api/eval/feedback-status", params={"vbplId": reviewed})

    assert body.status_code == 200, body.text
    data = body.json()
    assert data["pairsUsable"] == 2
    assert data["byAction"] == {"accept": 1, "edit": 1, "reject": 1}
    assert set(data["draftExamples"]) == {"positiveAvailable", "negativeAvailable"}
    assert "ready" in data and "minPairs" in data


def test_build_writes_nothing_below_threshold(reviewed, tmp_path):
    with get_sessionmaker()() as session:
        result = dpo_pipeline.build_dataset(
            session, out_dir=tmp_path, min_pairs=5, vbpl_id=reviewed
        )

    assert result.built is False
    assert result.pairs == 2
    # A half-empty set must not be written: the directory stays untouched.
    assert list(tmp_path.iterdir()) == []


def test_build_writes_dataset_and_manifest_when_ready(reviewed, tmp_path):
    with get_sessionmaker()() as session:
        result = dpo_pipeline.build_dataset(
            session, out_dir=tmp_path, min_pairs=2, vbpl_id=reviewed
        )

    assert result.built is True
    assert result.dataset_path.exists() and result.manifest_path.exists()

    lines = [json.loads(line) for line in result.dataset_path.read_text("utf-8").splitlines()]
    assert len(lines) == result.pairs == 2
    assert all(line["chosen"] and line["rejected"] for line in lines)

    manifest = json.loads(result.manifest_path.read_text("utf-8"))
    assert manifest["pairs"] == 2
    assert manifest["min_pairs"] == 2
    assert manifest["vbpl_id"] == reviewed
    # The prompt framing is recorded so a reader knows how a pair was posed to the model.
    assert manifest["prompt_template"]


def test_force_builds_below_threshold(reviewed, tmp_path):
    with get_sessionmaker()() as session:
        result = dpo_pipeline.build_dataset(
            session, out_dir=tmp_path, min_pairs=99, force=True, vbpl_id=reviewed
        )

    assert result.built is True and result.forced is True
    # Forced, not actually ready: the manifest must not claim the threshold was met.
    assert result.ready is False
    assert result.pairs == 2
    assert json.loads(result.manifest_path.read_text("utf-8"))["ready"] is False


def test_filenames_are_versioned(reviewed, tmp_path):
    with get_sessionmaker()() as session:
        result = dpo_pipeline.build_dataset(
            session, out_dir=tmp_path, min_pairs=1, vbpl_id=reviewed
        )

    assert result.dataset_path.name.startswith("dpo-") and result.dataset_path.suffix == ".jsonl"
    assert result.manifest_path.name.endswith(".manifest.json")


def test_train_is_a_roadmap_stub():
    with pytest.raises(NotImplementedError, match="roadmap"):
        dpo_pipeline.train("whatever.jsonl")
