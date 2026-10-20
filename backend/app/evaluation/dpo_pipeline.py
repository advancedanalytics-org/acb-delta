"""DPO long loop, built ahead of time (KHOA-02, vòng dài).

The export in `app.evaluation.dpo` already turns reviewer decisions into preference pairs. This
module is the orchestration around it so the loop can run on its own once enough feedback exists:

- `feedback_status` answers "have we gathered enough to train?" without writing anything -- the
  `GET /api/eval/feedback-status` endpoint and the UI read it.
- `build_dataset` writes a versioned JSONL + a manifest, but only once the threshold is met (or
  `force`). The threshold keeps a tiny, unrepresentative dataset from being built by accident.
- `train` is a deliberate roadmap stub: `PLAN.md` scopes the long loop as "produce the dataset, do
  not train", and the demo infra has no trainer. It raises rather than pretending to train.

Everything reuses `app.evaluation.feedback` and `app.evaluation.dpo`, so the chosen/rejected
contract (docs/amendment-review-contract.md §4) stays defined in one place.
"""

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.evaluation import dpo
from app.evaluation.feedback import split_examples
from app.evaluation.schemas import ExampleCounts, FeedbackStatus
from app.routers.decisions import list_feedback


def feedback_status(
    session: Session,
    *,
    min_pairs: int,
    vbpl_id: str | None = None,
    since: datetime | None = None,
) -> FeedbackStatus:
    """Count the feedback gathered so far and whether it clears the DPO threshold.

    Reads `list_feedback` once and derives every count from it, so the status cannot disagree with
    the examples served from the same rows.
    """
    rows = list_feedback(session, since=since, vbpl_id=vbpl_id)

    by_action = {"accept": 0, "edit": 0, "reject": 0}
    for row in rows:
        if row.action in by_action:
            by_action[row.action] += 1

    pairs_usable = sum(1 for row in rows if row.chosen and row.rejected)
    draft_failures = sum(1 for row in rows if row.draft_status in ("failed", "skipped"))

    newest_first = list(reversed(rows))
    draft_pos, draft_neg = split_examples(newest_first, "draft")
    judge_pos, judge_neg = split_examples(newest_first, "judge")

    return FeedbackStatus(
        decisions_read=len(rows),
        pairs_usable=pairs_usable,
        by_action=by_action,
        draft_failures=draft_failures,
        min_pairs=min_pairs,
        ready=pairs_usable >= min_pairs,
        draft_examples=ExampleCounts(
            positive_available=len(draft_pos), negative_available=len(draft_neg)
        ),
        judge_examples=ExampleCounts(
            positive_available=len(judge_pos), negative_available=len(judge_neg)
        ),
    )


@dataclass
class BuildResult:
    """What a build attempt did. `built` is False when the threshold was not met and not forced."""

    built: bool
    pairs: int
    min_pairs: int
    ready: bool
    forced: bool
    reason: str | None = None
    dataset_path: Path | None = None
    manifest_path: Path | None = None


def build_dataset(
    session: Session,
    *,
    out_dir: str | Path,
    min_pairs: int,
    force: bool = False,
    vbpl_id: str | None = None,
    since: datetime | None = None,
) -> BuildResult:
    """Write a versioned DPO dataset + manifest when enough feedback has been gathered.

    Nothing is written below the threshold unless `force`; a half-empty preference set is worse
    than none, because it would train on a corner of the reviewers' decisions.
    """
    status = feedback_status(session, min_pairs=min_pairs, vbpl_id=vbpl_id, since=since)

    if not status.ready and not force:
        missing = max(0, min_pairs - status.pairs_usable)
        return BuildResult(
            built=False,
            pairs=status.pairs_usable,
            min_pairs=min_pairs,
            ready=status.ready,
            forced=force,
            reason=f"Chưa đủ: có {status.pairs_usable}/{min_pairs} cặp, còn thiếu {missing}.",
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dataset_path = Path(out_dir) / f"dpo-{stamp}.jsonl"
    manifest_path = Path(out_dir) / f"dpo-{stamp}.manifest.json"

    # write_jsonl creates the directory and writes the same preference rows the status counted.
    written = dpo.write_jsonl(session, dataset_path, vbpl_id=vbpl_id, since=since)

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "pairs": written,
        "min_pairs": min_pairs,
        "ready": status.ready,
        "forced": force,
        "vbpl_id": vbpl_id,
        "since": since.isoformat() if since else None,
        "prompt_template": dpo.PROMPT_TEMPLATE,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return BuildResult(
        built=True,
        pairs=written,
        min_pairs=min_pairs,
        ready=status.ready,
        forced=force,
        dataset_path=dataset_path,
        manifest_path=manifest_path,
    )


def train(dataset_path: str | Path, manifest_path: str | Path | None = None) -> NoReturn:
    """Roadmap hook: fine-tune with DPO on an exported dataset. Intentionally not implemented.

    The plan is trl `DPOTrainer` over a base model, which needs GPUs the demo VM / MaaS does not
    have, so this raises instead of faking a trained model. Wire a real trainer here when the
    roadmap step (PLAN.md, TAI-04) is picked up; it consumes the JSONL + manifest `build_dataset`
    writes.
    """
    raise NotImplementedError(
        "Bước train DPO là roadmap (PLAN.md, TAI-04): dự kiến trl DPOTrainer trên model nền, "
        "chạy ngoài hạ tầng demo. Dataset + manifest đã sẵn sàng để nạp khi có trainer."
    )


def _engine(database_url: str):
    return create_engine(database_url, connect_args={"connect_timeout": 5})


def _parse_since(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    status_cmd = sub.add_parser("status", help="In readiness của feedback cho DPO")
    build_cmd = sub.add_parser("build", help="Xuất dataset DPO khi đã đủ feedback")
    for cmd in (status_cmd, build_cmd):
        cmd.add_argument("--database-url", required=True, help="Postgres URL reachable from here")
        cmd.add_argument(
            "--min-pairs", type=int, default=None, help="Ngưỡng (mặc định DPO_MIN_PAIRS)"
        )
        cmd.add_argument("--vbpl-id", default=None, help="Giới hạn trong một gói duyệt")
        cmd.add_argument("--since", default=None, help="Chỉ tính quyết định từ mốc ISO này")
    build_cmd.add_argument("--out-dir", default=None, help="Thư mục ra (mặc định DPO_OUT_DIR)")
    build_cmd.add_argument("--force", action="store_true", help="Xuất kể cả khi chưa đủ ngưỡng")

    args = parser.parse_args()
    settings = get_settings()
    min_pairs = args.min_pairs if args.min_pairs is not None else settings.dpo_min_pairs
    since = _parse_since(args.since)

    engine = _engine(args.database_url)
    try:
        with Session(engine) as session:
            if args.cmd == "status":
                _print_status(
                    feedback_status(session, min_pairs=min_pairs, vbpl_id=args.vbpl_id, since=since)
                )
                return

            out_dir = args.out_dir or settings.dpo_out_dir
            if not out_dir:
                build_cmd.error("Cần --out-dir hoặc đặt DPO_OUT_DIR")
            result = build_dataset(
                session,
                out_dir=out_dir,
                min_pairs=min_pairs,
                force=args.force,
                vbpl_id=args.vbpl_id,
                since=since,
            )
            _print_build(result)
    finally:
        engine.dispose()


def _print_status(status: FeedbackStatus) -> None:
    acts = status.by_action
    verdict = "ĐỦ" if status.ready else "chưa đủ"
    draft, judge = status.draft_examples, status.judge_examples
    print(f"Quyết định đã gom: {status.decisions_read}")
    print(f"  accept={acts['accept']} edit={acts['edit']} reject={acts['reject']}")
    print(f"Cặp DPO dùng được: {status.pairs_usable}/{status.min_pairs} -> {verdict}")
    print(f"Draft lỗi/bỏ qua (không tạo cặp): {status.draft_failures}")
    print(
        "Few-shot đang phục vụ: "
        f"draft {draft.positive_available}+/{draft.negative_available}-, "
        f"judge {judge.positive_available}+/{judge.negative_available}-"
    )


def _print_build(result: BuildResult) -> None:
    if not result.built:
        print(result.reason)
        return
    print(f"{result.pairs} cặp preference -> {result.dataset_path}")
    print(f"Manifest -> {result.manifest_path}")
    print("Bước tiếp theo: cấu hình train DPO (roadmap) — xem app.evaluation.dpo_pipeline.train")


if __name__ == "__main__":
    main()
