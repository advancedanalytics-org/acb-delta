"""DB-backed jobs for parse / analyze, run on an in-process thread pool.

PLAN.md keeps Phase 1 queue-free, so jobs live in the `job` table and run in this process. The
handler contract (job_id in, result dict out, raise on failure) maps 1:1 to a Celery task if a
queue is added later (design section 17).
"""

import json
import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine

log = logging.getLogger(__name__)

Handler = Callable[[str], dict]
_handlers: dict[str, Handler] = {}
_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def register(job_type: str, handler: Handler) -> None:
    _handlers[job_type] = handler


def new_job_id() -> str:
    return f"JOB-{uuid.uuid4().hex[:12]}"


def create_job(conn, job_type: str, document_id: str, version_id: str, params: dict) -> str:
    job_id = new_job_id()
    conn.execute(
        text(
            "INSERT INTO job (job_id, job_type, document_id, version_id, status, stage, params) "
            "VALUES (:id, :type, :doc, :ver, 'queued', 'queued', CAST(:params AS jsonb))"
        ),
        {
            "id": job_id,
            "type": job_type,
            "doc": document_id,
            "ver": version_id,
            "params": json.dumps(params),
        },
    )
    return job_id


def update_progress(job_id: str, stage: str, progress: int) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE job SET stage = :stage, progress = :p WHERE job_id = :id"),
            {"stage": stage, "p": progress, "id": job_id},
        )


def get_job(job_id: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(text("SELECT * FROM job WHERE job_id = :id"), {"id": job_id}).mappings()
        row = row.first()
    return dict(row) if row else None


def _executor_instance() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=get_settings().job_workers, thread_name_prefix="ria-job"
            )
        return _executor


def submit(job_id: str) -> None:
    _executor_instance().submit(run_job, job_id)


def run_job(job_id: str) -> None:
    # Claim atomically so a job submitted twice still runs once.
    with get_engine().begin() as conn:
        job_type = conn.execute(
            text(
                "UPDATE job SET status = 'running', stage = 'started', started_at = :now "
                "WHERE job_id = :id AND status = 'queued' RETURNING job_type"
            ),
            {"id": job_id, "now": datetime.now(UTC)},
        ).scalar()
    if not job_type:
        return
    try:
        result = _handlers[job_type](job_id)
    except Exception as exc:
        # Fail closed: the error is visible on GET /api/jobs/{id}; workflow state is unchanged.
        log.exception("job %s failed", job_id)
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    "UPDATE job SET status = 'failed', error = :err, finished_at = :now "
                    "WHERE job_id = :id"
                ),
                {"id": job_id, "err": f"{exc.__class__.__name__}: {exc}", "now": datetime.now(UTC)},
            )
        return
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE job SET status = 'succeeded', stage = 'done', progress = 100, "
                "result = CAST(:result AS jsonb), finished_at = :now WHERE job_id = :id"
            ),
            {"id": job_id, "result": json.dumps(result, default=str), "now": datetime.now(UTC)},
        )


def recover_interrupted() -> None:
    """On startup: jobs left 'running' by a dead process fail; 'queued' ones are resubmitted."""
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE job SET status = 'failed', error = 'interrupted by API restart', "
                "finished_at = now() WHERE status = 'running'"
            )
        )
        queued = conn.execute(text("SELECT job_id FROM job WHERE status = 'queued'")).scalars()
        queued = list(queued)
    for job_id in queued:
        submit(job_id)
