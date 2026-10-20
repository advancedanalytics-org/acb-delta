"""Latency of a scored run comes from its own job rows (needs RIA_TEST_DATABASE_URL)."""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from app.evaluation.ria_runner import _job_timings

DB_URL = os.environ.get("RIA_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="RIA_TEST_DATABASE_URL not set")

DOC = "REG-TIMING-TEST"
VERSION = f"{DOC}@v1"


@pytest.fixture
def db():
    from app.config import get_settings
    from app.db import get_engine
    from app.ria.schema import ensure_schema

    patch = pytest.MonkeyPatch()
    patch.setenv("DATABASE_URL", DB_URL)
    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.hitl import init_tables

    ensure_schema()
    init_tables()
    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        _cleanup(conn)
        conn.execute(
            text(
                "INSERT INTO document (document_id, title, doc_type, owner) "
                "VALUES (:d, 'timing test', 'regulation', 'test')"
            ),
            {"d": DOC},
        )
        conn.execute(
            text(
                "INSERT INTO document_version (version_id, document_id, version_label, status, "
                "checksum) VALUES (:v, :d, 'v1', 'effective', 'x')"
            ),
            {"v": VERSION, "d": DOC},
        )
    yield engine
    with engine.begin() as conn:
        _cleanup(conn)
    engine.dispose()
    patch.undo()
    get_settings.cache_clear()
    get_engine.cache_clear()


def _cleanup(conn) -> None:
    conn.execute(text("DELETE FROM vbpls WHERE ria_job_id LIKE 'JOB-TIMING-%'"))
    conn.execute(text("DELETE FROM job WHERE version_id = :v"), {"v": VERSION})
    conn.execute(text("DELETE FROM document_version WHERE version_id = :v"), {"v": VERSION})
    conn.execute(text("DELETE FROM document WHERE document_id = :d"), {"d": DOC})


def _job(conn, job_id: str, job_type: str, seconds: int, params: dict | None = None) -> None:
    start = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
    conn.execute(
        text(
            "INSERT INTO job (job_id, job_type, document_id, version_id, status, params, "
            "started_at, finished_at) VALUES (:id, :t, :d, :v, 'succeeded', "
            "CAST(:p AS jsonb), :s, :f)"
        ),
        {
            "id": job_id,
            "t": job_type,
            "d": DOC,
            "v": VERSION,
            "p": json.dumps(params or {}),
            "s": start,
            "f": start + timedelta(seconds=seconds),
        },
    )


def test_latency_counts_only_the_analysis_and_its_own_review(db):
    with db.begin() as conn:
        # An earlier run of the same regulation version: its jobs must not be counted.
        _job(conn, "JOB-TIMING-OLD", "analyze", 100)
        _job(conn, "JOB-TIMING-OLD-R", "review", 200, {"analyze_job_id": "JOB-TIMING-OLD"})
        _job(conn, "JOB-TIMING-NEW", "analyze", 40)
        _job(conn, "JOB-TIMING-NEW-R", "review", 25, {"analyze_job_id": "JOB-TIMING-NEW"})
        conn.execute(
            text(
                "INSERT INTO vbpls (id, number, title, issuer, issued_date, effective_date, "
                "summary, text, status, ria_job_id, received_at) VALUES ('VB-TIMING', 'x', 'x', "
                "'x', '2026-10-19', '2026-10-19', '', '', 'done', 'JOB-TIMING-NEW', now())"
            )
        )

    vbpl_id, seconds, started = _job_timings(DB_URL, "JOB-TIMING-NEW")

    assert vbpl_id == "VB-TIMING"
    assert seconds == 65.0  # 40 s analysis + 25 s review, not + 200 s of the earlier review
    assert started.startswith("2026-10-19T06:00:00")
