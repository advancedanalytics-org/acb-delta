"""Contract tests for the evaluation API.

The dashboard derives its baseline from array position and reads every metric leaf without a null
check, so the order of the list and the exact camelCase keys are part of the contract, not
implementation detail.
"""

import pytest
from sqlalchemy import text

from app.db import get_engine


def _metrics() -> dict:
    """One complete `EvalMetrics` payload, shaped like frontend/src/api/types.ts."""
    return {
        "extraction": {"precision": 0.874, "recall": 0.812},
        "retrieval": {"recallAtK": 0.781, "k": 5, "mrr": 0.643},
        "impact": {"precision": 0.716, "recall": 0.842, "f1": 0.774},
        "amendment": {"judgeScore": 3.41, "hitlAcceptRate": 0.537},
        "system": {"latencySeconds": 46.8, "costUsdPerDocument": 0.214},
    }


@pytest.fixture
def eval_client(client):
    """The shared `client` fixture truncates the HITL tables but not ours: start from empty."""
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM eval_runs"))
    return client


def test_no_runs_yet_returns_an_empty_array(eval_client):
    response = eval_client.get("/api/eval/runs")

    # The screen shows "Chưa có lượt đánh giá nào" for this; it is not an error.
    assert response.status_code == 200
    assert response.json() == []


def test_created_run_comes_back_with_the_keys_the_ui_declares(eval_client):
    created = eval_client.post(
        "/api/eval/runs",
        json={
            "label": "Baseline",
            "datasetSize": 48,
            "note": "Prompt gốc, chưa dùng phản hồi HITL.",
            "metrics": _metrics(),
            "params": {"maxChanges": 10, "retrieveK": 5},
        },
    )
    assert created.status_code == 201, created.text

    runs = eval_client.get("/api/eval/runs").json()

    assert len(runs) == 1
    run = runs[0]
    assert {"id", "label", "createdAt", "datasetSize", "note", "metrics"} <= set(run)
    assert run["label"] == "Baseline"
    assert run["datasetSize"] == 48
    assert run["note"] == "Prompt gốc, chưa dùng phản hồi HITL."
    # The camelCase leaves the dashboard reads by name.
    assert run["metrics"]["retrieval"]["recallAtK"] == pytest.approx(0.781)
    assert run["metrics"]["impact"]["f1"] == pytest.approx(0.774)
    assert run["metrics"]["amendment"]["hitlAcceptRate"] == pytest.approx(0.537)
    assert run["metrics"]["system"]["costUsdPerDocument"] == pytest.approx(0.214)
    assert run["params"] == {"maxChanges": 10, "retrieveK": 5}


def test_runs_are_returned_oldest_first(eval_client):
    for label, size in (("Baseline", 48), ("Sau phản hồi vòng 1", 61)):
        response = eval_client.post(
            "/api/eval/runs",
            json={"label": label, "datasetSize": size, "note": "", "metrics": _metrics()},
        )
        assert response.status_code == 201, response.text

    runs = eval_client.get("/api/eval/runs").json()

    # evaluation-page.tsx takes data[data.length - 1] as the current run and data[runIndex - 1] as
    # its baseline. Reversed, the "Trước và sau phản hồi" chart compares the wrong way round and
    # nothing in the UI reports it.
    assert [r["label"] for r in runs] == ["Baseline", "Sau phản hồi vòng 1"]
    assert runs[-1]["datasetSize"] == 61
    assert runs[-2]["label"] == "Baseline"


def test_retrieval_k_defaults_to_the_value_the_label_hardcodes(eval_client):
    metrics = _metrics()
    del metrics["retrieval"]["k"]

    created = eval_client.post(
        "/api/eval/runs",
        json={"label": "Không gửi k", "datasetSize": 1, "metrics": metrics},
    )
    assert created.status_code == 201, created.text

    # The dashboard renders the literal string "Recall@5" and never reads k, so 5 is the only
    # default that keeps the screen honest.
    assert created.json()["metrics"]["retrieval"]["k"] == 5


def test_a_run_missing_a_metric_group_is_rejected(eval_client):
    incomplete = _metrics()
    del incomplete["amendment"]

    response = eval_client.post(
        "/api/eval/runs",
        json={"label": "Thiếu metric", "datasetSize": 1, "metrics": incomplete},
    )

    # A partial run must never be stored: the dashboard would crash reading the missing group.
    assert response.status_code == 422
    assert eval_client.get("/api/eval/runs").json() == []
