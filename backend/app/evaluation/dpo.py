"""Export reviewer decisions as DPO preference pairs (KHOA-02, vòng dài).

`PLAN.md` scopes this as roadmap: produce the dataset, do not train. One JSONL line per decision
that contrasts two texts -- `{"prompt", "chosen", "rejected"}`.

Only `edit` and `reject` decisions qualify. An `accept` has no rejected alternative (the reviewer
took the AI text), and a draft that failed or was skipped has no AI text at all, so
`docs/amendment-review-contract.md` §4 leaves its `rejected` null. Dropping those is not data loss:
a pair with one side missing is not a preference.

The file goes outside the repo by default -- `AGENTS.md` keeps generated datasets out of git.
"""

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.evaluation.feedback import preference_rows
from app.evaluation.schemas import FeedbackExample

PROMPT_TEMPLATE = (
    "Quy định nội bộ hiện tại:\n{affected_text}\n\n"
    "Lý do cần xem xét sửa: {rationale}\n\n"
    "Viết lại đoạn trên cho đúng quy định mới, sửa tối thiểu."
)


def to_pair(example: FeedbackExample) -> dict:
    """One preference pair. The prompt restates what the model was asked, not what it answered."""
    return {
        "prompt": PROMPT_TEMPLATE.format(
            affected_text=example.affected_text,
            rationale=example.rationale or "(không có lý do ghi kèm)",
        ),
        "chosen": example.chosen,
        "rejected": example.rejected,
        "meta": {
            "impact_id": example.impact_id,
            "category": example.category,
            "reason_tags": example.reason_tags,
        },
    }


def write_jsonl(session: Session, out_path: Path, vbpl_id: str | None = None) -> int:
    """Write every usable pair. Returns how many lines were written."""
    rows = preference_rows(session, vbpl_id=vbpl_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(to_pair(row), ensure_ascii=False) + "\n")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Postgres URL reachable from here")
    parser.add_argument("--out", type=Path, required=True, help="JSONL path, outside the repo")
    parser.add_argument("--vbpl-id", default=None, help="Limit to one review package")
    args = parser.parse_args()

    engine = create_engine(args.database_url, connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as session:
            written = write_jsonl(session, args.out, vbpl_id=args.vbpl_id)
    finally:
        engine.dispose()

    print(f"{written} cặp preference -> {args.out}")
    if written == 0:
        print("Chưa có quyết định nào đối lập hai văn bản (accept không tạo được cặp).")


if __name__ == "__main__":
    main()
