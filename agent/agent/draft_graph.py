"""Amendment drafter: one RIA finding in, one minimal patch checked against the source text out.

draft (LLM) → validate (rules, no LLM) → verify (second LLM, advisory). Fails closed: a patch that
cannot be located exactly once in the clause is never returned, and nothing is ever "approved".
"""

import hashlib
import json
import logging
import re
import unicodedata
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent import llm, prompts
from agent.config import get_settings
from agent.llm import LLMNotConfiguredError
from agent.schemas import (
    AmendmentProposal,
    Check,
    DraftRequest,
    PatchDraft,
    Span,
    Verdict,
    Verification,
)

log = logging.getLogger(__name__)

# One retry when the rule checks reject the first draft; the failure reason goes into the prompt.
MAX_ATTEMPTS = 2
# A patch replacing more than this share of the clause is flagged (warn, not fail).
MAX_CHANGED_SHARE = 0.5
# Checks whose failure means the patch is unusable (retry, then `failed`).
BLOCKING_CHECKS = {
    "span_matches_source",
    "span_unique",
    "inside_target_span",
    "insert_position",
    "minimal_change",
}
# An edit may run past either end of `target_span` over these characters only: the spaces and
# punctuation around a phrase. RIA's span "trừ trường hợp …" is deleted as ", trừ trường hợp …".
SPAN_EDGE = frozenset(" \t\n,;:.")

# System prompts + output schemas (their field descriptions are prompt text too).
PROMPT_VERSION = hashlib.sha256(
    json.dumps(
        [
            prompts.DRAFT_PATCH,
            prompts.VERIFY_PATCH,
            PatchDraft.model_json_schema(),
            Verdict.model_json_schema(),
        ],
        ensure_ascii=False,
        sort_keys=True,
    ).encode()
).hexdigest()[:12]


class DraftState(TypedDict, total=False):
    request: dict
    attempts: int
    # `PatchDraft` dict from the latest attempt; None when the LLM call failed.
    draft: dict | None
    # Why the latest attempt was rejected (LLM error or failed check); None once valid.
    failure: str | None
    start: int
    end: int
    old_text: str
    checks: list[dict]
    # Text actually inserted at [start, end): the drafter's new_text, spaced for INSERT.
    new_text: str


def _matches(clause_text: str, old_text: str) -> list[tuple[int, int]]:
    """Every occurrence of `old_text`, overlapping ones included.

    Whitespace may differ (PDF line breaks); words may not, and a match never starts or ends
    inside a word ("30 ngày" does not match inside "130 ngày").
    """
    words = unicodedata.normalize("NFC", old_text).split()
    if not words:
        return []
    pattern = r"\s+".join(re.escape(w) for w in words)
    if words[0][0].isalnum():
        pattern = r"(?<!\w)" + pattern
    if words[-1][-1].isalnum():
        pattern += r"(?!\w)"
    regex = re.compile(pattern)
    out, pos = [], 0
    while (m := regex.search(clause_text, pos)) is not None:
        out.append((m.start(), m.end()))
        pos = m.start() + 1
    return out


def edit_bounds(clause_text: str, target_span: Span) -> tuple[int, int]:
    """Where an edit may reach: `target_span` widened over adjacent spaces and punctuation."""
    lo, hi = target_span.start, target_span.end
    while lo > 0 and clause_text[lo - 1] in SPAN_EDGE:
        lo -= 1
    while hi < len(clause_text) and clause_text[hi] in SPAN_EDGE:
        hi += 1
    return lo, hi


def locate_patch(
    clause_text: str, operation: str, old_text: str, target_span: Span | None
) -> tuple[int, int] | str:
    """Offsets of the edit in `clause_text`, or the reason it cannot be placed.

    INSERT goes at the end of `target_span` (or of the clause). REPLACE / DELETE need `old_text`
    found exactly once; when it occurs several times, exactly one occurrence inside `target_span`
    (see `edit_bounds`) is still a unique locator.
    """
    if operation == "INSERT":
        at = target_span.end if target_span else len(clause_text)
        return at, at
    matches = _matches(clause_text, old_text)
    if not matches:
        return "span_matches_source: old_text không có trong điều khoản nội bộ"
    if len(matches) > 1 and target_span:
        lo, hi = edit_bounds(clause_text, target_span)
        inside = [(s, e) for s, e in matches if lo <= s and e <= hi]
        if len(inside) == 1:
            return inside[0]
    if len(matches) > 1:
        return (
            f"span_unique: old_text xuất hiện {len(matches)} lần, "
            "hãy chép đoạn dài hơn để chỉ khớp một chỗ"
        )
    return matches[0]


def insert_text(clause_text: str, at: int, new_text: str) -> str:
    """`new_text` with a space added where it would otherwise glue onto a neighbouring word."""
    text = new_text.strip()
    if at > 0 and not clause_text[at - 1].isspace():
        text = " " + text
    if at < len(clause_text) and not clause_text[at].isspace() and clause_text[at] not in ".,;:)":
        text += " "
    return text


def splits_a_sentence(clause_text: str, at: int, new_text: str) -> bool:
    """True when `new_text` is a whole sentence (capital first letter, ends with '.' or ';') and
    `at` sits inside a sentence of the clause. Such an INSERT reads as two sentences glued
    together: "…báo cáo Khối Tuân thủ Đơn vị báo cáo Ngân hàng Nhà nước … hằng quý.:".
    A continuing phrase ("và lưu kết quả") may go anywhere."""
    text = new_text.strip()
    first = next((ch for ch in text if ch.isalpha()), "")
    if not (first.isupper() and text.endswith((".", ";"))):
        return False
    if not clause_text[at:].strip():
        return False  # end of the clause
    before = clause_text[:at].rstrip(" \t")
    return bool(before) and before[-1] not in ".;\n"


def _rule_checks(
    request: DraftRequest, draft: PatchDraft
) -> tuple[list[Check], int, int, str, str]:
    clause_text = request.clause.text
    target = request.target_span
    located = locate_patch(clause_text, draft.operation, draft.old_text, target)
    if isinstance(located, str):
        name = located.split(":", 1)[0]
        checks = [Check(check=name, status="fail", detail=located)]
        if name == "span_unique":
            checks.insert(0, Check(check="span_matches_source", status="pass"))
        return checks, -1, -1, "", ""
    start, end = located
    old_text = clause_text[start:end]
    checks = [
        Check(check="span_matches_source", status="pass"),
        Check(check="span_unique", status="pass"),
    ]
    if target is None:
        checks.append(Check(check="inside_target_span", status="skipped"))
    elif (bounds := edit_bounds(clause_text, target))[0] <= start and end <= bounds[1]:
        checks.append(Check(check="inside_target_span", status="pass"))
    else:
        checks.append(
            Check(
                check="inside_target_span",
                status="fail",
                detail=f"inside_target_span: chỉ được sửa trong đoạn {target.text!r}",
            )
        )
    if draft.operation == "INSERT":
        if splits_a_sentence(clause_text, start, draft.new_text):
            checks.append(
                Check(
                    check="insert_position",
                    status="fail",
                    detail=(
                        "insert_position: new_text là một câu hoàn chỉnh nhưng điểm chèn nằm "
                        "giữa câu; hãy chèn một cụm từ nối tiếp hoặc dùng REPLACE"
                    ),
                )
            )
        else:
            checks.append(Check(check="insert_position", status="pass"))
    new_text = {"DELETE": "", "INSERT": insert_text(clause_text, start, draft.new_text)}.get(
        draft.operation, draft.new_text
    )
    if draft.operation != "DELETE" and not new_text.strip():
        checks.append(
            Check(check="minimal_change", status="fail", detail="minimal_change: new_text trống")
        )
    elif " ".join(new_text.split()) == " ".join(old_text.split()):
        checks.append(
            Check(
                check="minimal_change",
                status="fail",
                detail="minimal_change: new_text giống old_text, patch không thay đổi gì",
            )
        )
    elif clause_text and (end - start) / len(clause_text) > MAX_CHANGED_SHARE:
        checks.append(
            Check(
                check="minimal_change",
                status="warn",
                detail=f"patch thay {end - start}/{len(clause_text)} ký tự của điều khoản",
            )
        )
    else:
        checks.append(Check(check="minimal_change", status="pass"))
    return checks, start, end, old_text, new_text


def apply_patch(text: str, start: int, end: int, new_text: str) -> str:
    return text[:start] + new_text + text[end:]


def _request(state: DraftState) -> DraftRequest:
    return DraftRequest.model_validate(state["request"])


def _obligation_blocks(request: DraftRequest) -> list[str]:
    """The finding's obligation, then those of the other findings on the same clause."""
    obligations = [request.obligation, *(r.obligation for r in request.related_findings)]
    return [prompts.obligation_block(o.clause_id, o.text) for o in obligations]


def draft(state: DraftState) -> DraftState:
    request = _request(state)
    parts = [
        f"Loại tác động (RIA): {request.category}",
        *_obligation_blocks(request),
        prompts.clause_block("Điều khoản nội bộ", request.clause.clause_id, request.clause.text),
    ]
    if request.target_span:
        parts.append(f"Đoạn cần sửa: {request.target_span.text}")
        parts.append(
            "Nếu INSERT, nội dung mới được chèn ngay sau 'Đoạn cần sửa'. Nếu chỗ đó nằm giữa câu, "
            "chỉ chèn một cụm từ nối tiếp, không chèn một câu hoàn chỉnh."
        )
    else:
        parts.append("Nếu INSERT, nội dung mới được chèn vào cuối điều khoản.")
    parts.append(f"Lý do phải sửa: {request.rationale}")
    parts.extend(f"Lý do phải sửa ({r.category}): {r.rationale}" for r in request.related_findings)
    if state.get("failure"):
        parts.append(f"Bản nháp trước bị từ chối ({state['failure']}). Sửa lại cho đúng.")
    attempts = state.get("attempts", 0) + 1
    try:
        result = llm.structured_call(PatchDraft, prompts.DRAFT_PATCH, "\n\n".join(parts))
    except LLMNotConfiguredError:
        raise
    except Exception as exc:  # malformed / missing structured output counts as a failed attempt
        # Only the error type leaves the agent (reason, retry prompt); the message is in the log.
        log.warning("draft LLM call failed for %s: %s", request.finding_id, exc)
        return {"attempts": attempts, "draft": None, "failure": f"LLM error: {type(exc).__name__}"}
    return {"attempts": attempts, "draft": result.model_dump(), "failure": None}


def validate(state: DraftState) -> DraftState:
    if state.get("draft") is None:
        return {}  # keep the previous attempt's checks; `failure` holds the LLM error
    checks, start, end, old_text, new_text = _rule_checks(
        _request(state), PatchDraft.model_validate(state["draft"])
    )
    failed = [c for c in checks if c.status == "fail" and c.check in BLOCKING_CHECKS]
    return {
        "checks": [c.model_dump() for c in checks],
        "failure": failed[0].detail if failed else None,
        "start": start,
        "end": end,
        "old_text": old_text,
        "new_text": new_text,
    }


def after_validate(state: DraftState) -> str:
    if state.get("failure") is None:
        return "verify"
    return "draft" if state.get("attempts", 0) < MAX_ATTEMPTS else END


def verify(state: DraftState) -> DraftState:
    """Independent second opinion with a different prompt. Advisory: never blocks or approves."""
    request = _request(state)
    after = apply_patch(request.clause.text, state["start"], state["end"], state["new_text"])
    user = "\n\n".join(
        [
            *_obligation_blocks(request),
            prompts.clause_block("Trước khi sửa", request.clause.clause_id, request.clause.text),
            prompts.clause_block("Sau khi sửa", request.clause.clause_id, after),
        ]
    )
    try:
        verdict = llm.structured_call(Verdict, prompts.VERIFY_PATCH, user)
    except Exception as exc:
        log.warning("verifier failed for %s: %s", request.finding_id, exc)
        check = Check(check="independent_verifier", status="skipped", detail=type(exc).__name__)
    else:
        agrees = (
            verdict.satisfies_obligation
            and verdict.preserves_other_content
            and verdict.adds_no_exception
        )
        check = Check(
            check="independent_verifier",
            status="pass" if agrees else "fail",
            detail=verdict.comment,
        )
    return {"checks": [*state["checks"], check.model_dump()]}


def build_draft_graph() -> CompiledStateGraph:
    graph = StateGraph(DraftState)
    graph.add_node("draft", draft)
    graph.add_node("validate", validate)
    graph.add_node("verify", verify)
    graph.add_edge(START, "draft")
    graph.add_edge("draft", "validate")
    graph.add_conditional_edges("validate", after_validate, ["draft", "verify", END])
    graph.add_edge("verify", END)
    return graph.compile()


def to_proposal(request: DraftRequest, state: DraftState) -> AmendmentProposal:
    """Final graph state → AmendmentProposal v1. Patch fields are null when no draft passed."""
    reg_doc = request.obligation.clause_id.split("@", 1)[0]
    evidence = [c for c in request.citations if c.split("@", 1)[0] == reg_doc]
    patch = PatchDraft.model_validate(state["draft"]) if state.get("draft") else None
    common = {
        "finding_id": request.finding_id,
        "clause_id": request.clause.clause_id,
        "legal_evidence_ids": evidence
        or [
            request.obligation.clause_id,
            *(r.obligation.clause_id for r in request.related_findings),
        ],
        "model": get_settings().llm_model,
        "prompt_version": PROMPT_VERSION,
    }
    checks = [Check.model_validate(c) for c in state.get("checks", [])]
    if state.get("failure") is not None or patch is None:
        return AmendmentProposal(
            **common,
            operation=None,
            start=None,
            end=None,
            old_text=None,
            new_text=None,
            rationale=patch.rationale if patch else "",
            verification=Verification(
                status="failed", reason=state.get("failure") or "no draft", checks=checks
            ),
        )
    return AmendmentProposal(
        **common,
        operation=patch.operation,
        start=state["start"],
        end=state["end"],
        old_text=state["old_text"],
        new_text=state["new_text"],
        rationale=patch.rationale,
        verification=Verification(status="review_required", checks=checks),
    )
