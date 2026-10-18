"""Engine 3 — Amendment Intelligence (design sections 13-15, RIA 4.0 section 07).

finding → minimal patch → verification → human decision → redline. Nothing here edits an
internal document: an approved patch is a proposal with a hash-checked locator, ready for the
document owner to apply.

- Patch: a single REPLACE / INSERT / DELETE on one clause, with offsets into the clause text and
  into the document, and the sha256 of the clause text it was computed against. VALUE_CHANGE
  findings whose spans came from the deterministic value rule get a rule patch ("24 tháng" →
  "tối đa 12 tháng"); other findings ask the LLM for the smallest edit, whose old text must occur
  exactly once in the clause (unique locator).
- Verification (section 14): source grounding, patch integrity, minimality, deterministic values,
  scope/exception review, semantic entailment by an independent model (Jev, not the LLM that
  drafted), human approval. Fail closed: a blocking check makes the patch BLOCKED and it cannot be
  approved.
"""

import hashlib
import html
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.db import get_engine
from app.ria import findings, jev, llm
from app.ria.compare import compare_values
from app.ria.schema import ensure_schema
from app.ria.textutil import extract_quantities, normalize

PATCHABLE = ("VALUE_CHANGE", "CONTRADICTION", "SCOPE_CHANGE", "ADDITION", "INDIRECT_IMPACT")
# Minimality: a patch may rewrite at most this share of the clause (REPLACE/DELETE) …
MAX_CHANGED_RATIO = 0.6
# … and insert at most this many characters.
MAX_INSERT_CHARS = 800
# Jev entailment thresholds: below FAIL the draft does not meet the obligation.
ENTAIL_PASS, ENTAIL_FAIL = 0.6, 0.4

DECISIONS = {"approve": "APPROVED", "reject": "REJECTED", "return": "NEED_MORE_EVIDENCE"}


class AmendmentError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


# --- Loading ----------------------------------------------------------------------------------


def load_finding(conn, finding_id: str) -> dict:
    try:
        return findings.load_finding(conn, finding_id)
    except findings.FindingError as exc:
        raise AmendmentError(exc.status_code, exc.detail) from exc


def load_amendment(conn, patch_id: str) -> dict:
    row = (
        conn.execute(text("SELECT * FROM amendment WHERE patch_id = :id"), {"id": patch_id})
        .mappings()
        .first()
    )
    if not row:
        raise AmendmentError(404, f"amendment {patch_id} not found")
    return dict(row)


# --- Patch generation ----------------------------------------------------------------------

SYSTEM = """Bạn là chuyên viên pháp chế soạn sửa đổi quy định nội bộ của ngân hàng.
Đề xuất MỘT thay đổi NHỎ NHẤT trên điều khoản nội bộ để đáp ứng nghĩa vụ pháp lý mới.
Quy tắc:
- Giữ nguyên thuật ngữ, văn phong, đánh số và mọi nội dung không bị tác động.
- REPLACE: old_text là đoạn ngắn nhất cần thay, chép CHÍNH XÁC từ điều khoản và xuất hiện đúng một
  lần; new_text là nội dung thay thế.
- INSERT: khi nghĩa vụ mới chưa có trong điều khoản; anchor_text là đoạn chép CHÍNH XÁC từ điều
  khoản, new_text được chèn ngay sau anchor_text (thường là một câu mới, bắt đầu bằng dấu cách).
- DELETE: old_text là đoạn cần bỏ.
- NONE: nếu điều khoản đã đáp ứng nghĩa vụ hoặc không đủ căn cứ để sửa.
- Không tạo nghĩa vụ, ngoại lệ hay giá trị không có trong nghĩa vụ nguồn.
Trả về DUY NHẤT JSON: {"operation": "REPLACE|INSERT|DELETE|NONE", "old_text": "...",
"anchor_text": "...", "new_text": "...", "rationale": "<lý do ngắn tiếng Việt>",
"conditions_to_verify": ["..."]}"""


def _rule_patch(f: dict) -> dict | None:
    """VALUE_CHANGE from the value rule: replace the internal value with the source value."""
    target, source = f.get("target_span"), f.get("source_span")
    if f["category"] != "VALUE_CHANGE" or not target or not source:
        return None
    start, end = target["start"], target["end"]
    if f["clause_text"][start:end] != target["text"]:
        return None
    new_text = normalize(source["text"])
    # Both spans must be exactly one value ("tối đa 12 tháng" / "24 tháng"), as the value rule
    # produces them. A broad LLM quote goes to the LLM drafter instead.
    if not (_is_single_value(new_text) and _is_single_value(normalize(target["text"]))):
        return None
    return {
        "operation": "REPLACE",
        "start": start,
        "end": end,
        "before": target["text"],
        "after": new_text,
        "method": "rule",
        "rationale": (
            f"Thay giá trị '{target['text']}' bằng '{new_text}' theo "
            f"{(f.get('regulation_clause_id') or '').split('#')[-1] or 'nghĩa vụ nguồn'}."
        ),
        "conditions": [],
    }


def _is_single_value(value: str) -> bool:
    found = extract_quantities(value)
    return len(found) == 1 and found[0].text.strip() == value.strip()


def _unique(haystack: str, needle: str) -> tuple[int, int] | None:
    """Offsets of needle when it occurs exactly once (design 07.01: no ambiguous locator)."""
    if not needle:
        return None
    first = haystack.find(needle)
    if first < 0 or haystack.find(needle, first + 1) >= 0:
        return None
    return first, first + len(needle)


def _llm_patch(f: dict, refresh: bool) -> dict:
    payload = json.dumps(
        {
            "loai_tac_dong": f["category"],
            "ly_do_phat_hien": f["rationale"],
            "nghia_vu_nguon": {
                "trich_dan": f["obligation_text"],
                "dieu_khoan_day_du": (f["regulation_clause_text"] or "")[:2000],
                "dieu_kien": f["condition"],
                "ngoai_le": f["exception"],
            },
            "dieu_khoan_noi_bo": {"ma": f["internal_clause_id"], "noi_dung": f["clause_text"]},
            "doan_lien_quan": (f.get("target_span") or {}).get("text"),
        },
        ensure_ascii=False,
    )
    last_error = "LLM returned no usable patch"
    for attempt in range(2):
        answer, _ = llm.chat_json_cached("amendment", SYSTEM, payload, refresh or attempt > 0)
        op = str(answer.get("operation", "")).upper()
        clause = f["clause_text"]
        base = {
            "method": "llm",
            "rationale": str(answer.get("rationale", ""))[:2000],
            "conditions": [str(c) for c in answer.get("conditions_to_verify", [])][:10],
        }
        if op == "NONE":
            return {**base, "operation": "NONE"}
        if op in ("REPLACE", "DELETE"):
            loc = _unique(clause, answer.get("old_text") or "")
            if loc:
                after = "" if op == "DELETE" else str(answer.get("new_text") or "")
                return {
                    **base,
                    "operation": op,
                    "start": loc[0],
                    "end": loc[1],
                    "before": clause[loc[0] : loc[1]],
                    "after": after,
                }
            last_error = "old_text is not a unique exact substring of the clause"
        elif op == "INSERT":
            anchor = answer.get("anchor_text") or ""
            loc = _unique(clause, anchor) if anchor else (len(clause), len(clause))
            new_text = str(answer.get("new_text") or "")
            if loc and new_text.strip():
                return {
                    **base,
                    "operation": "INSERT",
                    "start": loc[1],
                    "end": loc[1],
                    "before": "",
                    "after": new_text,
                }
            last_error = "anchor_text is not a unique exact substring, or new_text is empty"
        else:
            last_error = f"unknown operation {op!r}"
    raise AmendmentError(422, f"could not draft a grounded patch: {last_error}")


def create_amendment(finding_id: str, refresh: bool = False) -> tuple[dict, bool]:
    """Draft and verify a patch for a finding. Returns (amendment, created)."""
    ensure_schema()
    with get_engine().connect() as conn:
        f = load_finding(conn, finding_id)
        existing = (
            conn.execute(
                text(
                    "SELECT patch_id FROM amendment WHERE finding_id = :f "
                    "AND approval IN ('pending', 'APPROVED') ORDER BY created_at DESC LIMIT 1"
                ),
                {"f": finding_id},
            ).scalar()
            if not refresh
            else None
        )
        if existing:
            return get_amendment(existing), False
    if f["category"] == "EQUIVALENT":
        raise AmendmentError(409, "finding is EQUIVALENT: the internal clause already complies")
    if f["category"] not in PATCHABLE:
        raise AmendmentError(409, f"category {f['category']} is not patchable")
    if not f["internal_clause_id"] or not f["clause_text"]:
        raise AmendmentError(409, "finding has no internal clause to patch")
    if not f["obligation_id"]:
        raise AmendmentError(
            409, "document-level finding (knowledge graph link): review the document manually"
        )
    if (f["verification"] or {}).get("status") == "BLOCKED":
        raise AmendmentError(409, "finding verification is BLOCKED; resolve it before drafting")

    patch = _rule_patch(f)
    if patch is None:
        if not llm.llm_model():
            raise AmendmentError(
                503, "LLM_MODEL not configured; only VALUE_CHANGE has rule patches"
            )
        patch = _llm_patch(f, refresh)
    if patch["operation"] == "NONE":
        return {
            "finding_id": finding_id,
            "operation": "NONE",
            "rationale": patch["rationale"],
            "conditions": patch["conditions"],
        }, False

    patch_id = f"PATCH-{uuid.uuid4().hex[:10]}"
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO amendment (patch_id, finding_id, clause_id, version_id, target_start, "
                "target_end, doc_start, doc_end, operation, before_text, after_text, "
                "original_hash, method, rationale, conditions, validation, approval) VALUES "
                "(:id, :f, :c, :v, :s, :e, :ds, :de, :op, :before, :after, :hash, :method, "
                ":rationale, CAST(:conditions AS jsonb), 'PENDING', 'pending')"
            ),
            {
                "id": patch_id,
                "f": finding_id,
                "c": f["internal_clause_id"],
                "v": f["internal_version_id"],
                "s": patch["start"],
                "e": patch["end"],
                "ds": f["clause_start"] + patch["start"],
                "de": f["clause_start"] + patch["end"],
                "op": patch["operation"],
                "before": patch["before"],
                "after": patch["after"],
                "hash": sha256(f["clause_text"]),
                "method": patch["method"],
                "rationale": patch["rationale"],
                "conditions": json.dumps(patch["conditions"], ensure_ascii=False),
            },
        )
    validate_amendment(patch_id)
    return get_amendment(patch_id), True


# --- Verification ----------------------------------------------------------------------------


def apply_patch(clause_text: str, a: dict) -> str:
    return clause_text[: a["target_start"]] + a["after_text"] + clause_text[a["target_end"] :]


def _sentence_around(value: str, start: int, end: int) -> str:
    lo = max(value.rfind(sep, 0, start) for sep in ".;\n") + 1
    hi_candidates = [i for i in (value.find(sep, end) for sep in ".;\n") if i >= 0]
    hi = min(hi_candidates) + 1 if hi_candidates else len(value)
    return value[lo:hi].strip()


def _entailment(f: dict, before: str, after: str) -> dict:
    if not jev.jev_model():
        return {"check": "semantic_entailment", "status": "skipped", "detail": "JEV not configured"}
    questions = {
        "satisfies": jev.noul(
            "Điều khoản nội bộ SAU sửa đổi có đáp ứng nghĩa vụ pháp lý không?",
            "Nội dung sau sửa đổi thực hiện đúng nghĩa vụ, giá trị và mức bắt buộc của nguồn.",
            "Sau sửa đổi vẫn thiếu, sai giá trị hoặc mâu thuẫn với nghĩa vụ.",
        ),
        "no_new_obligation": jev.noul(
            "Sửa đổi có tránh được việc tạo nghĩa vụ, ngoại lệ hoặc giá trị không có trong nguồn?",
            "Chỉ đưa vào nội dung có căn cứ trong nghĩa vụ nguồn.",
            "Thêm nghĩa vụ, ngoại lệ, giá trị hoặc đối tượng không có trong nguồn.",
        ),
        "preserves_rest": jev.noul(
            "Các nội dung không liên quan đến nghĩa vụ có được giữ nguyên ý nghĩa không?",
            "Phần không bị tác động giữ nguyên ý nghĩa.",
            "Sửa đổi làm thay đổi ý nghĩa của phần không liên quan.",
        ),
    }
    try:
        answers = jev.decide(
            {
                "nghia_vu_nguon": f["obligation_text"],
                "dieu_khoan_truoc_sua": before,
                "dieu_khoan_sau_sua": after,
            },
            questions,
        )
    except Exception as exc:
        return {"check": "semantic_entailment", "status": "error", "detail": str(exc)[:200]}
    scores = {k: jev.probability(answers.get(k)) for k in questions}
    if any(v is None for v in scores.values()):
        status = "needs_review"
    elif scores["satisfies"] < ENTAIL_FAIL or scores["no_new_obligation"] < ENTAIL_FAIL:
        status = "fail"
    elif min(scores.values()) >= ENTAIL_PASS:
        status = "pass"
    else:
        status = "needs_review"
    return {
        "check": "semantic_entailment",
        "status": status,
        "detail": {"verifier": jev.jev_model(), "scores": scores},
    }


def run_checks(f: dict, a: dict, clause_text: str | None, version_status: str | None) -> list:
    checks = []
    # 1. Source grounding: the legal basis exists and is not superseded; citations resolve.
    grounded = bool(f["obligation_text"]) and f["regulation_status"] != "superseded"
    checks.append(
        {
            "check": "source_grounding",
            "status": "pass" if grounded else "block",
            "detail": {
                "regulation_clause": f["regulation_clause_id"],
                "regulation_status": f["regulation_status"],
            },
        }
    )
    # 2. Patch integrity: the clause still has the text the patch was computed against.
    integrity = (
        clause_text is not None
        and sha256(clause_text) == a["original_hash"]
        and 0 <= a["target_start"] <= a["target_end"] <= len(clause_text)
        and clause_text[a["target_start"] : a["target_end"]] == a["before_text"]
        and version_status == "effective"
    )
    checks.append(
        {
            "check": "patch_integrity",
            "status": "pass" if integrity else "block",
            "detail": "hash, offsets and version match"
            if integrity
            else "clause changed, offsets invalid or internal version no longer effective",
        }
    )
    if not integrity:
        return checks
    after = apply_patch(clause_text, a)
    # 3. Minimality: one contiguous edit inside the clause, small relative to it.
    if a["operation"] == "INSERT":
        minimal = 0 < len(a["after_text"].strip()) <= MAX_INSERT_CHARS
        ratio = None
    else:
        ratio = round((a["target_end"] - a["target_start"]) / max(1, len(clause_text)), 3)
        minimal = ratio <= MAX_CHANGED_RATIO and a["before_text"] != a["after_text"]
    checks.append(
        {
            "check": "minimality",
            "status": "pass" if minimal else "block",
            "detail": {"changed_ratio": ratio, "operation": a["operation"]},
        }
    )
    # 4. Deterministic values: values in the patched sentence must satisfy the source bounds.
    if extract_quantities(f["obligation_text"]):
        sentence = _sentence_around(
            after, a["target_start"], a["target_start"] + len(a["after_text"])
        )
        values = compare_values(f["obligation_text"], sentence)
        if values["conflicts"]:
            status = "block"
        elif values["pairs"]:
            status = "pass"
        else:
            status = "needs_review" if f["category"] == "VALUE_CHANGE" else "not_applicable"
        checks.append(
            {
                "check": "deterministic_values",
                "status": status,
                "detail": [
                    f"{p['source'].text.strip()} vs {p['target'].text.strip()}"
                    + (" → conflict" if p["conflict"] else " → ok")
                    for p in values["pairs"]
                ],
            }
        )
    else:
        checks.append({"check": "deterministic_values", "status": "not_applicable"})
    # 5. Scope and exceptions of the obligation are a human call.
    if f["condition"] or f["exception"]:
        checks.append(
            {
                "check": "scope_exceptions",
                "status": "needs_review",
                "detail": {"condition": f["condition"], "exception": f["exception"]},
            }
        )
    # 6. Semantic entailment by an independent verifier (not the drafting LLM).
    checks.append(_entailment(f, clause_text, after))
    # 7. Always: a human with authority approves.
    checks.append({"check": "human_approval", "status": "pending"})
    return checks


def overall(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks if c["check"] != "human_approval"}
    if statuses & {"block", "fail"}:
        return "BLOCKED"
    if statuses & {"needs_review", "skipped", "error", "warn"}:
        return "NEEDS_HUMAN_REVIEW"
    return "VERIFIED"


def validate_amendment(patch_id: str) -> dict:
    ensure_schema()
    with get_engine().connect() as conn:
        a = load_amendment(conn, patch_id)
        f = load_finding(conn, a["finding_id"])
        current = (
            conn.execute(
                text(
                    "SELECT c.text, v.status FROM clause c JOIN document_version v "
                    "USING (version_id) WHERE c.clause_id = :c"
                ),
                {"c": a["clause_id"]},
            )
            .mappings()
            .first()
        )
    checks = run_checks(
        f, a, current["text"] if current else None, current["status"] if current else None
    )
    status = overall(checks)
    report = {"status": status, "checks": checks, "validated_at": datetime.now(UTC).isoformat()}
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE amendment SET validation = :s, validation_report = CAST(:r AS jsonb) "
                "WHERE patch_id = :id"
            ),
            {"s": status, "r": json.dumps(report, ensure_ascii=False, default=str), "id": patch_id},
        )
    return get_amendment(patch_id)


# --- Decision, read, redline ---------------------------------------------------------------


def decide(patch_id: str, decision: str, reviewer: str, comment: str | None) -> dict:
    if decision not in DECISIONS:
        raise AmendmentError(422, f"decision must be one of {sorted(DECISIONS)}")
    ensure_schema()
    with get_engine().begin() as conn:
        a = load_amendment(conn, patch_id)
        if a["approval"] != "pending":
            raise AmendmentError(409, f"amendment already decided: {a['approval']}")
        if decision == "approve" and a["validation"] in ("BLOCKED", "PENDING"):
            # Fail closed (section 14): a blocked or unverified patch is never approved.
            raise AmendmentError(409, f"cannot approve: validation is {a['validation']}")
        status = DECISIONS[decision]
        conn.execute(
            text(
                "UPDATE amendment SET approval = :s, reviewer = :r, review_comment = :c, "
                "decided_at = now() WHERE patch_id = :id"
            ),
            {"s": status, "r": reviewer, "c": comment, "id": patch_id},
        )
        conn.execute(
            text("UPDATE impact_finding SET status = :s, reviewer = :r WHERE finding_id = :f"),
            {"s": status, "r": reviewer, "f": a["finding_id"]},
        )
    return get_amendment(patch_id)


def get_amendment(patch_id: str) -> dict:
    with get_engine().connect() as conn:
        a = load_amendment(conn, patch_id)
        clause = conn.execute(
            text("SELECT text FROM clause WHERE clause_id = :c"), {"c": a["clause_id"]}
        ).scalar()
    a["clause_text"] = clause
    a["patched_text"] = apply_patch(clause, a) if clause is not None else None
    return a


def list_for_finding(finding_id: str) -> list[dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT patch_id FROM amendment WHERE finding_id = :f ORDER BY created_at DESC"),
            {"f": finding_id},
        ).scalars()
        ids = list(rows)
    return [get_amendment(i) for i in ids]


def redline_html(patch_id: str) -> str:
    a = get_amendment(patch_id)
    with get_engine().connect() as conn:
        f = load_finding(conn, a["finding_id"])
    clause = a["clause_text"] or ""
    s, e = a["target_start"], a["target_end"]
    body = (
        html.escape(clause[:s])
        + (f"<del>{html.escape(a['before_text'])}</del>" if a["before_text"] else "")
        + (f"<ins>{html.escape(a['after_text'])}</ins>" if a["after_text"] else "")
        + html.escape(clause[e:])
    )
    checks = "".join(
        f"<li><b>{html.escape(c['check'])}</b>: {html.escape(str(c['status']))}</li>"
        for c in (a["validation_report"] or {}).get("checks", [])
    )
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<title>Redline {html.escape(patch_id)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;line-height:1.6;
padding:0 1rem}}del{{background:#fde2e2;color:#a40000}}ins{{background:#dcf5dc;color:#0a5a0a;
text-decoration:none}}.clause{{border:1px solid #ccc;border-radius:8px;padding:1rem;
white-space:pre-wrap}}.meta{{color:#555;font-size:.9rem}}</style></head><body>
<h1>Đề xuất sửa đổi {html.escape(patch_id)}</h1>
<p class="meta">Điều khoản {html.escape(a["clause_id"])} · {html.escape(a["operation"])} ·
kiểm chứng: {html.escape(a["validation"])} · phê duyệt: {html.escape(a["approval"])}</p>
<div class="clause">{body}</div>
<h2>Căn cứ</h2><p>{html.escape(f["regulation_clause_id"] or "")}:
{html.escape(f["obligation_text"] or "")}</p>
<h2>Lý do</h2><p>{html.escape(a["rationale"] or "")}</p>
<h2>Kiểm tra</h2><ul>{checks}</ul>
<p class="meta">Bản đề xuất; chưa áp dụng vào văn bản nội bộ.</p></body></html>"""
