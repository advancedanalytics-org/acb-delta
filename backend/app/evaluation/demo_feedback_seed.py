"""Seed an illustrative demo HITL-feedback corpus so the RLHF panel is populated (KHOA-02).

The "Học từ phản hồi (RLHF)" section and the few-shot example tabs on `/evaluation` are built from
real reviewer decisions (`app.routers.decisions.list_feedback`), not from the eval runs that
`demo_seed` fills. On a fresh demo there are almost no decisions, so that whole section reads empty:
the DPO-readiness ring sits at 0, the accept/edit/reject pie is blank and both example tabs say
"no cases".

This module inserts a **demo** corpus of reviewed impacts -- plausible VBPL -> internal-document
impacts, each with a reviewer decision (accept / edit / reject) -- so the readiness ring, the action
mix and the few-shot examples all have data to show. It is **demo data**, not real review history,
kept separate from the real HITL flow on purpose and labelled by this module, its `demo_feedback/`
folder and the AGENTS.md command row. Real decisions made through `POST /api/decisions` are never
touched and remain the source of truth; every row this seeder writes carries the `demofb-` id prefix
so it can find and remove exactly its own data.

Behaviour mirrors `demo_seed`:
* default -- insert only when the demo corpus is not already present (safe for the deploy hook; it
  never touches real decisions, and re-running it does not duplicate);
* `--replace` -- delete the demo corpus (its VBPLs cascade to impacts and decisions) and re-insert.

Usage (from backend/):
    uv run python -m app.evaluation.demo_feedback_seed            # insert when absent
    uv run python -m app.evaluation.demo_feedback_seed --replace  # re-seed the demo corpus

The corpus is deliberately sized so the usable preference pairs (edit + reject decisions, which are
the only ones that contrast two texts) clear the default `DPO_MIN_PAIRS` threshold, so the readiness
ring reads as "ready" without lowering the bar.
"""

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app import hitl
from app.db import get_sessionmaker
from app.models import hitl as models

CORPUS = Path(__file__).with_name("demo_feedback") / "corpus.json"
# Every demo row id carries this prefix, so the seed can find and remove exactly its own data.
DEMO_PREFIX = "demofb-"


def load_corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def _present(session) -> bool:
    """True when the demo corpus is already seeded (any demo VBPL exists)."""
    return (
        session.scalar(
            select(models.Vbpl.id).where(models.Vbpl.id.like(f"{DEMO_PREFIX}%")).limit(1)
        )
        is not None
    )


def _clear(session) -> int:
    """Delete the demo VBPLs; their impacts and decisions cascade. Returns VBPLs removed."""
    demo_vbpls = session.scalars(
        select(models.Vbpl).where(models.Vbpl.id.like(f"{DEMO_PREFIX}%"))
    ).all()
    for vbpl in demo_vbpls:
        session.delete(vbpl)
    session.commit()
    return len(demo_vbpls)


def _impact(vbpl_id: str, position: int, imp: dict) -> models.Impact:
    """Build one stored impact that looks like a RIA review package row to the feedback query."""
    affected, suggested = imp["affected_text"], imp["suggested_text"]
    # A whole-clause REPLACE keeps `patch` consistent with `suggested_text` for the redline view.
    patch = {
        "operation": "REPLACE",
        "start": 0,
        "end": len(affected),
        "old_text": affected,
        "new_text": suggested,
    }
    finding = {
        "finding_id": imp["finding_id"],
        "category": imp["category"],
        "rationale": imp["rationale"],
        "obligation": {"clause_id": imp["finding_id"], "text": imp["change_clause"]},
    }
    return models.Impact(
        id=imp["id"],
        vbpl_id=vbpl_id,
        position=position,
        document_id=imp["document_id"],
        chunk_id=f"{imp['document_id']}#{imp['finding_id']}",
        location=imp["location"],
        change_clause=imp["change_clause"],
        citation=imp["citation"],
        affected_text=affected,
        page=None,
        bboxes=[],
        type=imp["category"],
        severity=imp["severity"],
        reasoning=imp["reasoning"],
        suggested_text=suggested,
        # Non-empty model_output: the feedback query ignores rows with `{}` (raw findings), and the
        # few-shot examples read `finding.rationale` from here.
        model_output={
            "finding": finding,
            "related_findings": [],
            "draft": {"verification": {"status": "review_required"}, **patch},
        },
        finding_id=imp["finding_id"],
        category=imp["category"],
        patch=patch,
        draft_status="ready",
        draft_error=None,
    )


def seed_demo(*, replace: bool) -> int:
    """Insert the demo feedback corpus. Returns how many decisions were inserted (0 if skipped)."""
    corpus = load_corpus()
    hitl.init_tables()  # creates the HITL tables and the mock reviewers the decisions reference
    now = datetime.now(UTC)
    with get_sessionmaker()() as session:
        if _present(session):
            if not replace:
                print("demo feedback đã có; bỏ qua (dùng --replace để seed lại).")
                return 0
            removed = _clear(session)
            print(f"đã xoá {removed} VBPL demo cũ (--replace).")

        decisions = 0
        for vbpl in corpus["vbpls"]:
            session.add(
                models.Vbpl(
                    id=vbpl["id"],
                    number=vbpl["number"],
                    title=vbpl["title"],
                    issuer=vbpl["issuer"],
                    issued_date=date.fromisoformat(vbpl["issued_date"]),
                    effective_date=date.fromisoformat(vbpl["effective_date"]),
                    summary=vbpl["summary"],
                    text=vbpl.get("text", vbpl["summary"]),
                    status=vbpl.get("status", "done"),
                )
            )
            for position, imp in enumerate(vbpl["impacts"]):
                session.add(_impact(vbpl["id"], position, imp))
                d = imp["decision"]
                # Spread decisions over the past so "newest first" ordering reads naturally.
                at = now - timedelta(days=float(d["days_ago"]), hours=position)
                session.add(
                    models.Decision(
                        id=f"{DEMO_PREFIX}dec-{imp['id'].rsplit('-', 1)[-1]}",
                        impact_id=imp["id"],
                        action=d["action"],
                        edited_text=d.get("edited_text"),
                        reason_tags=d.get("reason_tags", []),
                        reviewer_id=d["reviewer_id"],
                        at=at,
                    )
                )
                decisions += 1
        session.commit()

    print(f"đã seed {decisions} quyết định demo trên {len(corpus['vbpls'])} VBPL.")
    return decisions


def main(argv: list[str] | None = None) -> int:
    replace = "--replace" in (sys.argv[1:] if argv is None else argv)
    seed_demo(replace=replace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
