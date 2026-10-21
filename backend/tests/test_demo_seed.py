"""Tests for the demo eval seed (KHOA-01).

`demo_seed` populates the dashboard with the illustrative demo runs in `demo_runs/`. These pin the
behaviours the deploy hook and the one-off `--replace` rely on: it fills an empty table with the
three runs oldest-first, it leaves a non-empty table alone by default, and `--replace` swaps
whatever is there for exactly the demo set.
"""

import pytest
from sqlalchemy import text

from app.db import get_engine
from app.evaluation import demo_seed

DEMO_LABELS = ["Baseline", "+ Few-shot", "+ DPO"]


@pytest.fixture
def seed_client(client):
    """The shared `client` fixture truncates the HITL tables but not ours: start from empty."""
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM eval_runs"))
    return client


def test_seeds_demo_runs_oldest_first(seed_client):
    inserted = demo_seed.seed_demo(replace=False)

    assert inserted == 3
    runs = seed_client.get("/api/eval/runs").json()
    # evaluation-page.tsx treats the last element as the current run, so order carries the story.
    assert [r["label"] for r in runs] == DEMO_LABELS
    last = runs[-1]
    assert last["metrics"]["amendment"]["judgeScore"] == pytest.approx(3.75)
    # f1 is consistent with precision/recall of the final run (2PR/(P+R)).
    p, r = 0.85, 0.80
    assert last["metrics"]["impact"]["f1"] == pytest.approx(2 * p * r / (p + r))


def test_insert_when_empty_skips_a_populated_table(seed_client):
    demo_seed.seed_demo(replace=False)

    # A second plain run must not duplicate or append.
    inserted = demo_seed.seed_demo(replace=False)

    assert inserted == 0
    runs = seed_client.get("/api/eval/runs").json()
    assert [r["label"] for r in runs] == DEMO_LABELS


def test_replace_overwrites_existing_runs(seed_client):
    seed_client.post(
        "/api/eval/runs",
        json={
            "label": "Run cũ",
            "datasetSize": 7,
            "metrics": {
                "extraction": {"precision": 1.0, "recall": 1.0},
                "retrieval": {"recallAtK": 0.33, "k": 5, "mrr": 0.16},
                "impact": {"precision": 1.0, "recall": 0.75, "f1": 0.857},
                "amendment": {"judgeScore": 2.33, "hitlAcceptRate": None},
                "system": {"latencySeconds": 69.0, "costUsdPerDocument": None},
            },
        },
    ).raise_for_status()

    inserted = demo_seed.seed_demo(replace=True)

    assert inserted == 3
    runs = seed_client.get("/api/eval/runs").json()
    # The stale run is gone; only the demo set remains, oldest first.
    assert [r["label"] for r in runs] == DEMO_LABELS
