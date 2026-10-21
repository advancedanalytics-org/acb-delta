"""Reading and writing evaluation runs."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.evaluation import models


def init_tables() -> None:
    """Create the evaluation tables if they are missing. Safe to run on every start."""
    models.EvalBase.metadata.create_all(get_engine())


def list_runs(session: Session) -> list[models.EvalRun]:
    """Runs oldest first.

    The order is load-bearing, not cosmetic: `frontend/src/features/evaluation/evaluation-page.tsx`
    selects `data[data.length - 1]` as the current run and `data[runIndex - 1]` as its baseline. Any
    other order makes the "Trước và sau phản hồi" chart compare the wrong way round, and nothing in
    the UI would report an error. `id` breaks ties so equal timestamps still have a fixed order.
    """
    return list(
        session.scalars(
            select(models.EvalRun).order_by(models.EvalRun.created_at, models.EvalRun.id)
        )
    )


def clear_runs(session: Session) -> int:
    """Delete every run. Returns how many were removed.

    Only the demo seeder's `--replace` uses this, to swap a stale single run for the demo set;
    nothing in the normal flow ever drops measured runs.
    """
    removed = session.query(models.EvalRun).delete()
    session.commit()
    return removed


def save_run(
    session: Session,
    *,
    label: str,
    dataset_size: int,
    note: str,
    metrics: dict,
    params: dict,
    created_at: datetime | None = None,
) -> models.EvalRun:
    """`created_at` defaults to now; pass the run's own time when recording a finished job."""
    run = models.EvalRun(
        label=label,
        dataset_size=dataset_size,
        note=note,
        metrics=metrics,
        params=params,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run
