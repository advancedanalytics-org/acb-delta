"""Review packages built from RIA analyze jobs (docs/amendment-review-contract.md).

POST /api/analyses/{job_id}/review  analyze job → vbpls + impacts with drafted patches (202)
"""

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from app import review_bridge
from app.ria.schema import ensure_schema

router = APIRouter(prefix="/analyses", tags=["analyses"])


class ReviewStarted(BaseModel):
    vbpl_id: str
    review_job_id: str


@router.post("/{job_id}/review", status_code=status.HTTP_202_ACCEPTED)
def start_review(job_id: str, response: Response) -> ReviewStarted:
    """202 when a review job starts; 200 with the existing package when one is running or done."""
    try:
        ensure_schema()
        body, started = review_bridge.start_review(job_id)
    except review_bridge.ReviewError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except OperationalError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    if not started:
        response.status_code = status.HTTP_200_OK
    return ReviewStarted(**body)
