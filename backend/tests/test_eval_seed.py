"""Tests for the baseline seed (KHOA-01).

The seed exists so the demo dashboard is never empty on a fresh database, without ever
fabricating numbers or clobbering a real run. These pin the three behaviours the deploy hook
relies on: it fills an empty table, it leaves a non-empty one alone, and a missing file is a
skip rather than a crash.
"""

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import get_engine
from app.evaluation import seed


def _body(label: str, *, dataset_size: int = 48, created_at: str | None = None) -> dict:
    """A complete `POST /api/eval/runs` body, exactly what `ria_runner --save` writes."""
    body = {
        "label": label,
        "datasetSize": dataset_size,
        "note": "Baseline đo thật, dùng làm seed.",
        "metrics": {
            "extraction": {"precision": 0.874, "recall": 0.812},
            "retrieval": {"recallAtK": 0.781, "k": 5, "mrr": 0.643},
            "impact": {"precision": 0.716, "recall": 0.842, "f1": 0.774},
            "amendment": {"judgeScore": 3.41, "hitlAcceptRate": None},
            "system": {"latencySeconds": 46.8, "costUsdPerDocument": None},
        },
        "params": {"evidence_per_obligation": 20, "analyzeJobId": "job-1"},
    }
    if created_at is not None:
        body["createdAt"] = created_at
    return body


@pytest.fixture
def seed_client(client):
    """The shared `client` fixture truncates the HITL tables but not ours: start from empty."""
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM eval_runs"))
    return client


def _write(tmp_path: Path, name: str, body: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


def test_seeds_a_run_into_an_empty_table(seed_client, tmp_path):
    inserted = seed.seed([_write(tmp_path, "baseline.json", _body("Baseline"))])

    assert inserted == 1
    runs = seed_client.get("/api/eval/runs").json()
    assert [r["label"] for r in runs] == ["Baseline"]
    # The camelCase JSONB survives the round trip, so a seeded run reads like a posted one.
    assert runs[0]["metrics"]["retrieval"]["recallAtK"] == pytest.approx(0.781)
    assert runs[0]["metrics"]["amendment"]["hitlAcceptRate"] is None


def test_does_not_overwrite_a_real_run(seed_client, tmp_path):
    seed_client.post("/api/eval/runs", json=_body("Run thật")).raise_for_status()

    inserted = seed.seed([_write(tmp_path, "baseline.json", _body("Seed"))])

    # A real run outranks the seed: nothing is inserted, nothing is replaced.
    assert inserted == 0
    runs = seed_client.get("/api/eval/runs").json()
    assert [r["label"] for r in runs] == ["Run thật"]


def test_missing_file_is_skipped_not_an_error(seed_client, tmp_path):
    inserted = seed.seed([tmp_path / "does-not-exist.json"])

    # The deploy hook runs before a baseline is committed; that must not fail the deploy.
    assert inserted == 0
    assert seed_client.get("/api/eval/runs").json() == []


def test_seeds_a_pair_oldest_first(seed_client, tmp_path):
    inserted = seed.seed(
        [
            _write(tmp_path, "a.json", _body("Baseline", created_at="2026-01-01T00:00:00Z")),
            _write(tmp_path, "b.json", _body("Sau phản hồi", created_at="2026-02-01T00:00:00Z")),
        ]
    )

    assert inserted == 2
    # evaluation-page.tsx treats the last element as the current run and the one before it as the
    # baseline, so the order the seed produces is the order the before/after chart compares.
    runs = seed_client.get("/api/eval/runs").json()
    assert [r["label"] for r in runs] == ["Baseline", "Sau phản hồi"]
