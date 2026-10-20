"""Evaluation runs for the dashboard (KHOA-01).

Replaces `listEvalRuns: notYet('KHOA-01')` in `frontend/src/api/live/index.ts`.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.db import SessionDep
from app.evaluation import feedback, schemas, store

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.get("/runs")
def list_eval_runs(session: SessionDep) -> list[schemas.EvalRunOut]:
    """Every run, oldest first. A bare array, and an empty one when nothing has been measured."""
    return [schemas.EvalRunOut.model_validate(run) for run in store.list_runs(session)]


@router.get("/examples")
def list_examples(
    session: SessionDep,
    task: Literal["draft", "judge"] = "draft",
    limit: Annotated[int, Query(ge=1, le=50)] = feedback.DEFAULT_LIMIT,
    vbpl_id: Annotated[str | None, Query(alias="vbplId")] = None,
    since: datetime | None = None,
) -> schemas.ExampleSet:
    """Few-shot examples built from reviewer decisions, newest first (KHOA-02).

    Served rather than injected: the drafter prompt belongs to TAI-01 and the judge prompt to
    MINH-01, so each decides when to pull these in.
    """
    return feedback.example_set(session, task, limit=limit, vbpl_id=vbpl_id, since=since)


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
        created_at=body.created_at,
    )
    return schemas.EvalRunOut.model_validate(run)
