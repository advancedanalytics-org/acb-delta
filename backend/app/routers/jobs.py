"""GET /api/jobs/{id}: progress, result and error of parse / analyze jobs."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import OperationalError

from app.ria import jobs
from app.ria.schema import ensure_schema

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        ensure_schema()
        job = jobs.get_job(job_id)
    except OperationalError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job {job_id} not found")
    return job
