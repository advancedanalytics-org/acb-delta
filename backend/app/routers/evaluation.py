"""Evaluation runs for the dashboard (KHOA-01).

Replaces `listEvalRuns: notYet('KHOA-01')` in `frontend/src/api/live/index.ts`.
"""

from fastapi import APIRouter, status

from app.db import SessionDep
from app.evaluation import schemas, store

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.get("/runs")
def list_eval_runs(session: SessionDep) -> list[schemas.EvalRunOut]:
    """Every run, oldest first. A bare array, and an empty one when nothing has been measured."""
    return [schemas.EvalRunOut.model_validate(run) for run in store.list_runs(session)]


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_eval_run(body: schemas.EvalRunCreate, session: SessionDep) -> schemas.EvalRunOut:
    """Record one experiment. Called by the eval runner, not by the UI."""
    run = store.save_run(
        session,
        label=body.label,
        dataset_size=body.dataset_size,
        note=body.note,
        # Stored with the same camelCase keys the wire uses, so the JSONB mirrors the response.
        metrics=body.metrics.model_dump(by_alias=True),
        params=body.params,
    )
    return schemas.EvalRunOut.model_validate(run)
