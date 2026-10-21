"""Tests for the demo feedback seed (KHOA-02).

`demo_feedback_seed` fills the RLHF panel on `/evaluation`, which is built from real reviewer
decisions, with an illustrative corpus so it is not empty on a fresh demo. These pin both the corpus
shape the UI relies on and the seeder behaviours the deploy hook and the one-off `--replace` use: it
inserts the corpus when absent, leaves it alone by default once present, and `--replace` swaps it.
"""

from collections import Counter

from app.config import get_settings
from app.evaluation import demo_feedback_seed
from app.models.hitl import SEED_REVIEWERS

CATEGORIES = {"conflict", "outdated_reference", "new_obligation"}
SEVERITIES = {"high", "medium", "low"}
REVIEWER_IDS = {r["id"] for r in SEED_REVIEWERS}
# edit + reject are the only decisions that contrast two texts, so only they make a usable pair.
PAIR_ACTIONS = {"edit", "reject"}


def _impacts() -> list[dict]:
    corpus = demo_feedback_seed.load_corpus()
    return [imp for vbpl in corpus["vbpls"] for imp in vbpl["impacts"]]


# --- corpus integrity (no database needed) ---------------------------------------------------


def test_corpus_is_well_formed():
    impacts = _impacts()
    ids = [imp["id"] for imp in impacts]
    finding_ids = [imp["finding_id"] for imp in impacts]
    assert len(set(ids)) == len(ids), "impact ids must be unique"
    assert len(set(finding_ids)) == len(finding_ids), "finding ids must be unique"

    for imp in impacts:
        assert imp["id"].startswith(demo_feedback_seed.DEMO_PREFIX)
        assert imp["category"] in CATEGORIES
        assert imp["severity"] in SEVERITIES
        for field in ("affected_text", "suggested_text", "rationale", "change_clause"):
            assert imp[field].strip(), f"{imp['id']} missing {field}"
        d = imp["decision"]
        assert d["reviewer_id"] in REVIEWER_IDS
        if d["action"] == "edit":
            assert d.get("edited_text", "").strip(), f"{imp['id']} edit needs edited_text"
        else:
            assert "edited_text" not in d, f"{imp['id']} non-edit must not carry edited_text"


def test_corpus_clears_the_dpo_threshold():
    """The usable pairs (edit + reject) must clear DPO_MIN_PAIRS so the ring reads 'ready'."""
    actions = Counter(imp["decision"]["action"] for imp in _impacts())
    pairs = sum(actions[a] for a in PAIR_ACTIONS)
    assert pairs >= get_settings().dpo_min_pairs
    # A healthy mix: some of each, not all corrections.
    assert actions["accept"] > 0 and actions["edit"] > 0 and actions["reject"] > 0


# --- seeding against a database (skips without a test DB, like the rest of the suite) ---------


def test_seed_populates_the_rlhf_panel(client):
    inserted = demo_feedback_seed.seed_demo(replace=False)
    impacts = _impacts()
    actions = Counter(imp["decision"]["action"] for imp in impacts)
    assert inserted == len(impacts)

    status = client.get("/api/eval/feedback-status").json()
    assert status["decisionsRead"] == len(impacts)
    assert status["byAction"] == {
        "accept": actions["accept"],
        "edit": actions["edit"],
        "reject": actions["reject"],
    }
    assert status["draftFailures"] == 0
    # pairs = edit + reject; the panel's ring shows "ready" once it clears the threshold.
    assert status["pairsUsable"] == actions["edit"] + actions["reject"]
    assert status["ready"] is True

    draft = client.get("/api/eval/examples", params={"task": "draft"}).json()
    # draft positives = accept + edit (kept/rewrote text); negatives = edit (AI text replaced).
    assert draft["counts"]["positive_available"] == actions["accept"] + actions["edit"]
    assert draft["counts"]["negative_available"] == actions["edit"]
    assert draft["positive"] and draft["negative"]

    judge = client.get("/api/eval/examples", params={"task": "judge"}).json()
    # judge negatives = reject (the finding should not have been raised).
    assert judge["counts"]["negative_available"] == actions["reject"]


def test_insert_when_present_is_a_no_op(client):
    demo_feedback_seed.seed_demo(replace=False)

    inserted = demo_feedback_seed.seed_demo(replace=False)

    assert inserted == 0
    status = client.get("/api/eval/feedback-status").json()
    assert status["decisionsRead"] == len(_impacts())  # not duplicated


def test_replace_reseeds(client):
    demo_feedback_seed.seed_demo(replace=False)

    inserted = demo_feedback_seed.seed_demo(replace=True)

    assert inserted == len(_impacts())
    status = client.get("/api/eval/feedback-status").json()
    assert status["decisionsRead"] == len(_impacts())
