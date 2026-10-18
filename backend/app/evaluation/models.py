"""Stored experiment results (KHOA-01).

One row per evaluation run. The dashboard reads these oldest first and treats two adjacent rows as
the "before / after feedback" pair, so a run has to outlive the process that produced it.

`metrics` and `params` are JSONB on purpose: the metric shape is still settling (`PLAN.md` records
the evaluate data flow as `_chưa chốt_`), and a new metric must not need a migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid.uuid4())


class EvalBase(DeclarativeBase):
    """Own metadata, like `HitlBase`: this table needs neither pgvector nor the HITL tables."""


class EvalRun(EvalBase):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    # Shown in the dashboard's run picker, e.g. "Baseline", "Sau phản hồi vòng 1".
    label: Mapped[str] = mapped_column(Text)
    # The sort key the dashboard depends on. clock_timestamp, not now(), so two runs written inside
    # one transaction still order correctly.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    dataset_size: Mapped[int] = mapped_column(Integer)
    # Prose the dashboard renders verbatim: say where the feedback came from.
    note: Mapped[str] = mapped_column(Text, default="")
    # `EvalMetrics` from frontend/src/api/types.ts, camelCase keys as sent on the wire.
    metrics: Mapped[dict] = mapped_column(JSONB)
    # Settings that produced these numbers. `max_changes` caps extraction Recall by configuration
    # rather than by model quality (see docs/evaluation-data-contract.md), so a run is only
    # interpretable next to the parameters it ran with.
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
