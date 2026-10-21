"""Seed the illustrative demo eval runs for the dashboard (KHOA-01).

These numbers are **demo data**, not measured: the files in `demo_runs/` give the evaluation
dashboard a believable improvement story (Baseline -> +Few-shot -> +DPO) for the hackathon demo, so
it is not empty or stuck on a single run. Real measurements are unchanged and still flow through
`app.evaluation.ria_runner --save app/evaluation/baseline_run.json` -> `app.evaluation.seed`; this
module is the clearly-labelled exception, kept separate from `seed.py` on purpose.

Behaviour mirrors `seed.py`:
* default -- insert only when `eval_runs` is empty (safe for the deploy hook; keeps real runs);
* `--replace` -- clear `eval_runs` first, then insert (one-off, to swap a stale single run on an
  already-populated demo database).

Usage (from backend/):
    uv run python -m app.evaluation.demo_seed            # insert when empty
    uv run python -m app.evaluation.demo_seed --replace  # overwrite whatever is there

The files are exactly `POST /api/eval/runs` bodies (`schemas.EvalRunCreate`), loaded oldest first by
filename so `created_at` and dashboard order line up.
"""

import sys
from pathlib import Path

from app.db import get_sessionmaker
from app.evaluation import schemas, store

DEMO_DIR = Path(__file__).with_name("demo_runs")


def _demo_files() -> list[Path]:
    """The demo run bodies, oldest first (filenames are zero-padded: 01-, 02-, 03-)."""
    return sorted(DEMO_DIR.glob("*.json"))


def seed_demo(*, replace: bool) -> int:
    """Insert the demo runs. Returns how many were inserted (0 when skipped)."""
    files = _demo_files()
    if not files:
        print(f"không có file demo nào trong {DEMO_DIR}")
        return 0

    store.init_tables()
    with get_sessionmaker()() as session:
        if store.list_runs(session):
            if not replace:
                print("eval_runs đã có dữ liệu; bỏ qua (dùng --replace để ghi đè).")
                return 0
            removed = store.clear_runs(session)
            print(f"đã xoá {removed} run cũ (--replace).")
        inserted = 0
        for path in files:
            body = schemas.EvalRunCreate.model_validate_json(path.read_text(encoding="utf-8"))
            run = store.save_run(
                session,
                label=body.label,
                dataset_size=body.dataset_size,
                note=body.note,
                metrics=body.metrics.model_dump(by_alias=True),
                params=body.params,
                created_at=body.created_at,
            )
            print(f"đã nạp run demo {run.id}: {run.label}")
            inserted += 1
        return inserted


def main(argv: list[str]) -> int:
    seed_demo(replace="--replace" in argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
