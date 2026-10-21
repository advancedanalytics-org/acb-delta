"""Seed a baseline EvalRun so the dashboard is never empty on a fresh database (KHOA-01).

The evaluation dashboard shows "Chưa có lượt đánh giá nào" until `GET /api/eval/runs` returns a
run. A real run posted by the runner already survives every deploy (the Postgres volume is kept),
but a freshly created VM -- or one whose data was reset -- starts empty. This seed restores a
previously measured run so the demo always has a dashboard to show.

Idempotent and non-destructive: it inserts only when `eval_runs` is empty, so a real run already in
the table is never duplicated or overwritten. A missing seed file is skipped, not an error, so the
deploy hook (`scripts/gcp.sh`) is safe to run before any baseline has been recorded.

The seed files are exactly what `app.evaluation.ria_runner --save` writes: the `POST /api/eval/runs`
body of a real measured run. Numbers here are never hand-written -- `AGENTS.md` forbids fabricated
eval results (mock data is allowed only for internal documents). The hackathon dashboard demo has
its own clearly-labelled `app.evaluation.demo_seed` (illustrative numbers in `demo_runs/`); this
module and `baseline_run.json` stay for real measured runs only.

Usage (from backend/): uv run python -m app.evaluation.seed [run.json ...]
With no argument it uses the committed baseline next to this module, when present. Pass several
files (oldest first) to seed a before/after pair; `clock_timestamp()` keeps their order.
"""

import sys
from pathlib import Path

from app.db import get_sessionmaker
from app.evaluation import schemas, store

# The runner writes here with `--save app/evaluation/baseline_run.json`; committing that file turns
# a one-off measurement into the demo's permanent baseline.
DEFAULT_BASELINE = Path(__file__).with_name("baseline_run.json")


def seed(paths: list[Path]) -> int:
    """Insert the given runs when `eval_runs` is empty. Returns how many were inserted."""
    for path in paths:
        if not path.is_file():
            print(f"bỏ qua (không có file): {path}")
    present = [path for path in paths if path.is_file()]
    if not present:
        print("không có seed nào để nạp.")
        return 0

    store.init_tables()
    with get_sessionmaker()() as session:
        if store.list_runs(session):
            # A real run is worth more than the seed, and duplicating it would corrupt the
            # before/after comparison the dashboard derives from array position.
            print("eval_runs đã có dữ liệu; bỏ qua seed.")
            return 0
        inserted = 0
        for path in present:
            body = schemas.EvalRunCreate.model_validate_json(path.read_text(encoding="utf-8"))
            run = store.save_run(
                session,
                label=body.label,
                dataset_size=body.dataset_size,
                note=body.note,
                # Same camelCase JSONB the API stores, so a seeded run is indistinguishable from one
                # posted by the runner.
                metrics=body.metrics.model_dump(by_alias=True),
                params=body.params,
                created_at=body.created_at,
            )
            print(f"đã nạp run {run.id}: {run.label}")
            inserted += 1
        return inserted


def main(argv: list[str]) -> int:
    paths = [Path(arg) for arg in argv] or [DEFAULT_BASELINE]
    seed(paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
