"""Engine 2 — proposition matching and fine-grained diff (design sections 10, 11, 14).

Deterministic checks run first (values / deadlines, modality). An optional LLM judge then
classifies the pair, but its quotes must be found verbatim in the sources (grounding), and it
can never downgrade a conflict the rules found to EQUIVALENT (no false-safe).
"""

import json
import logging
import re

from app.config import get_settings
from app.ria import llm, spans
from app.ria.obligations import find_modality
from app.ria.textutil import Quantity, content_bigrams, extract_quantities

log = logging.getLogger(__name__)

LABELS = (
    "EQUIVALENT",
    "CONTRADICTION",
    "ADDITION",
    "SCOPE_CHANGE",
    "VALUE_CHANGE",
    "INDIRECT_IMPACT",
)
PRIORITY = {
    "VALUE_CHANGE": "high",
    "CONTRADICTION": "high",
    "ADDITION": "medium",
    "SCOPE_CHANGE": "medium",
    "INDIRECT_IMPACT": "low",
    "EQUIVALENT": "low",
}
_PERMISSIVE = re.compile(r"\b(có thể|được phép|được quyền|không bắt buộc)\b", re.I)


def _permissive_sentence(
    internal_text: str, shared: list[str], action_terms: set[str]
) -> tuple[int, int, str] | None:
    """A sentence that permits ("có thể", "được phép") the same action the obligation governs:
    it shares two gated evidence terms and the words right after the marker share a term with
    the obligation's action / object ("được phép cư trú" does not permit "yêu cầu giấy tờ")."""
    for m in re.finditer(r"[^.;\n]+", internal_text):
        sentence = m.group(0)
        marker = _PERMISSIVE.search(sentence)
        if not marker or len(set(content_bigrams(sentence)) & set(shared)) < 2:
            continue
        # The permitted verb phrase: the few words right after the marker.
        permitted = set(content_bigrams(" ".join(sentence[marker.end() :].split()[:4])))
        if permitted & action_terms:
            lead = len(sentence) - len(sentence.lstrip())
            return m.start() + lead, m.start() + len(sentence.rstrip()), marker.group(0)
    return None


# Words that sit next to any duration ("trong thời hạn 60 ngày") and say nothing about what
# the duration measures.
_VALUE_NOISE = frozenset({"thời hạn", "thời gian", "hạn ba", "hạn tối"})


def _window_bigrams(text: str, q: Quantity, width: int = 80) -> set[str]:
    """Topic around a quantity, the quantity itself excluded."""
    around = f"{text[max(0, q.start - width) : q.start]} . {text[q.end : q.end + width]}"
    return set(content_bigrams(around)) - _VALUE_NOISE


def compare_values(source_text: str, target_text: str, topic_terms: set[str] | None = None) -> dict:
    """Pair quantities of the same dimension measuring the same thing: their surroundings share
    at least two bigrams, one of them a gated topic term when `topic_terms` is given."""
    src_qs, tgt_qs = extract_quantities(source_text), extract_quantities(target_text)
    pairs = []
    for s in src_qs:
        s_ctx = _window_bigrams(source_text, s)
        for t in tgt_qs:
            if s.dimension != t.dimension:
                continue
            shared = s_ctx & _window_bigrams(target_text, t)
            if len(shared) < 2 or (topic_terms is not None and not shared & topic_terms):
                continue
            if s.bound == "max":
                conflict = t.value > s.value
            elif s.bound == "min":
                conflict = t.value < s.value
            else:
                conflict = abs(t.value - s.value) > 1e-9
            pairs.append({"source": s, "target": t, "conflict": conflict, "shared": sorted(shared)})
    conflicts = [p for p in pairs if p["conflict"]]
    return {"pairs": pairs, "conflicts": conflicts}


def _span(text: str, start: int, end: int) -> dict:
    return {"text": text[start:end], "start": start, "end": end}


# Similarity above which both sides state the same proposition, so a condition or exception
# present on one side only is a scope difference rather than a different topic.
SCOPE_MIN_SIMILARITY = 0.5
_SPAN_VI = {"CONDITION": "điều kiện", "EXCEPTION": "ngoại lệ"}
_SNAP_TYPES = {
    "VALUE_CHANGE": ("VALUE",),
    "SCOPE_CHANGE": spans.SCOPE_TYPES,
    "CONTRADICTION": ("MODALITY", "NEGATION", "VALUE"),
}


def _scope_difference(diff: dict | None) -> tuple[str, list[str]] | None:
    if not diff or diff["similarity"] < SCOPE_MIN_SIMILARITY:
        return None
    for side in ("source", "target"):
        kinds = [k for k in diff[f"only_in_{side}"] if k in _SPAN_VI]
        if kinds:
            return side, kinds
    return None


def _locate(haystack: str, quote: str | None) -> tuple[int, int] | None:
    if not quote:
        return None
    quote = quote.strip().strip('"“”')
    idx = haystack.find(quote)
    if idx >= 0:
        return idx, idx + len(quote)
    # Whitespace in PDFs differs (line breaks): match on collapsed whitespace.
    pattern = r"\s+".join(re.escape(w) for w in quote.split())
    m = re.search(pattern, haystack) if pattern else None
    return (m.start(), m.end()) if m else None


def rule_classify(
    obligation: dict,
    reg_clause_text: str,
    internal_text: str,
    evidence: dict,
    diff: dict | None = None,
) -> dict:
    o_start = obligation["span_start"]
    values = compare_values(
        obligation["text"], internal_text, set(evidence.get("shared_terms", []))
    )
    checks = []
    if values["pairs"]:
        checks.append(
            {
                "check": "deterministic_values",
                "status": "fail" if values["conflicts"] else "pass",
                "detail": [_pair_detail(p) for p in values["pairs"]],
            }
        )
    else:
        checks.append({"check": "deterministic_values", "status": "not_applicable"})
    if diff is not None:
        checks.append(
            {
                "check": "span_diff",
                "status": "info",
                "detail": {
                    "backend": diff["backend"],
                    "similarity": diff["similarity"],
                    "only_in_source": diff["only_in_source"],
                    "only_in_target": diff["only_in_target"],
                    "diffs": spans.compact(diff),
                },
            }
        )

    target_default = evidence["span"]
    if values["conflicts"]:
        p = values["conflicts"][0]
        s, t = p["source"], p["target"]
        return {
            "category": "VALUE_CHANGE",
            "confidence": 0.7,
            "rationale": (
                f"Văn bản mới quy định '{s.text.strip()}' ({_bound_vi(s.bound)}), quy định nội bộ "
                f"đang ghi '{t.text.strip()}' trong cùng ngữ cảnh ({', '.join(p['shared'][:3])})."
            ),
            "source_span": _span(reg_clause_text, o_start + s.start, o_start + s.end),
            "target_span": _span(internal_text, t.start, t.end),
            "checks": checks,
        }

    modality = obligation["modality"]
    shared = evidence.get("shared_terms", [])
    action_terms = set(content_bigrams(f"{obligation['action']} {obligation['object']}"))
    permissive = (
        _permissive_sentence(internal_text, shared, action_terms) if modality != "may" else None
    )
    if permissive:
        sentence = internal_text[permissive[0] : permissive[1]]
        internal_modality = find_modality(sentence)
        if modality == "must_not" or (internal_modality and internal_modality[0] == "may"):
            checks.append(
                {
                    "check": "modality",
                    "status": "fail",
                    "detail": f"nguồn: {modality}; nội bộ: '{permissive[2]}'",
                }
            )
            return {
                "category": "CONTRADICTION",
                "confidence": 0.4,
                "rationale": (
                    f"Nghĩa vụ nguồn mang tính {_modality_vi(modality)}, điều khoản nội bộ "
                    f"cùng chủ đề ({', '.join(shared[:3])}) dùng cách diễn đạt cho phép "
                    f"'{permissive[2]}'. Cần xác minh phạm vi áp dụng."
                ),
                "source_span": _span(reg_clause_text, o_start, obligation["span_end"]),
                "target_span": _span(internal_text, permissive[0], permissive[1]),
                "checks": checks,
            }

    if values["pairs"] and not values["conflicts"]:
        p = values["pairs"][0]
        return {
            "category": "EQUIVALENT",
            "confidence": 0.5,
            "rationale": (
                f"Giá trị nội bộ '{p['target'].text.strip()}' đáp ứng yêu cầu "
                f"'{p['source'].text.strip()}' ({_bound_vi(p['source'].bound)})."
            ),
            "source_span": _span(
                reg_clause_text, o_start + p["source"].start, o_start + p["source"].end
            ),
            "target_span": _span(internal_text, p["target"].start, p["target"].end),
            "checks": checks,
        }

    scope = _scope_difference(diff)
    if scope:
        side, kinds = scope
        sentence = diff["target_sentence"]
        where = "văn bản mới" if side == "source" else "quy định nội bộ"
        return {
            "category": "SCOPE_CHANGE",
            "confidence": 0.35,
            "rationale": (
                f"Cùng nội dung (độ tương đồng {diff['similarity']:.2f}) nhưng chỉ {where} có "
                f"{', '.join(_SPAN_VI[k] for k in kinds)}. Cần đánh giá phạm vi áp dụng."
            ),
            "source_span": _span(reg_clause_text, o_start, obligation["span_end"]),
            "target_span": _span(internal_text, sentence["start"], sentence["end"]),
            "checks": checks,
        }

    return {
        "category": "INDIRECT_IMPACT",
        "confidence": 0.3,
        "rationale": (
            "Điều khoản nội bộ cùng chủ đề với nghĩa vụ mới (thuật ngữ chung: "
            f"{', '.join(shared[:5]) or 'tương đồng ngữ nghĩa'}). "
            "Rule chưa xác định được khác biệt cụ thể; "
            "cần chuyên gia xác minh có phải sửa đổi hay không."
        ),
        "source_span": _span(reg_clause_text, o_start, obligation["span_end"]),
        "target_span": _span(internal_text, *target_default),
        "checks": checks,
    }


SYSTEM = """Bạn là chuyên gia pháp chế ngân hàng. So sánh MỘT nghĩa vụ trong văn bản pháp quy mới
với từng điều khoản quy định nội bộ được liệt kê (mỗi điều khoản có "ma").
Chỉ dựa vào văn bản được cung cấp, không suy đoán.
Nhãn hợp lệ cho từng điều khoản:
- EQUIVALENT: cùng nghĩa vụ dù khác từ ngữ, nội bộ đã đáp ứng
- CONTRADICTION: yêu cầu xung đột trong cùng phạm vi
- ADDITION: nguồn thêm yêu cầu mà điều khoản nội bộ chưa có
- SCOPE_CHANGE: khác đối tượng, điều kiện hoặc ngoại lệ
- VALUE_CHANGE: khác số liệu, hạn mức, thời hạn
- INDIRECT_IMPACT: chỉ liên quan gián tiếp, cần xác minh
Trả về DUY NHẤT một JSON object:
{"best": "<ma điều khoản khớp nhất với nghĩa vụ>",
 "results": [{"ma": "<ma>", "classification": "<nhãn>",
   "rationale": "<giải thích ngắn tiếng Việt>",
   "source_quote": "<trích nguyên văn ngắn từ nghĩa vụ nguồn>",
   "target_quote": "<trích nguyên văn ngắn từ điều khoản nội bộ đó>",
   "confidence": <0..1>, "conditions_to_verify": ["..."]}]}
Có đúng một phần tử results cho mỗi điều khoản. Trích dẫn phải sao chép CHÍNH XÁC từ văn bản.
Nếu không đủ căn cứ, dùng INDIRECT_IMPACT."""


def _group_payload(obligation: dict, reg_clause_text: str, items: list[dict]) -> str:
    return json.dumps(
        {
            "nghia_vu_nguon": {
                "trich_dan": obligation["text"],
                "chu_the": obligation["subject"],
                "muc_bat_buoc": obligation["modality"],
                "dieu_kien": obligation.get("condition"),
                "thoi_han": obligation.get("deadline"),
                "ngoai_le": obligation.get("exception"),
                "dieu_khoan_day_du": reg_clause_text[:2000],
            },
            "dieu_khoan_noi_bo": [
                {
                    "ma": it["internal"]["clause_id"],
                    "noi_dung": it["internal"]["text"][:2000],
                    "ngu_canh": [c["text"] for c in it["context"]][:4],
                    "khac_biet_span": spans.compact(it["span_diff"]) if it.get("span_diff") else [],
                    "ket_qua_rule": {
                        "nhan": it["rule"]["category"],
                        "kiem_tra": it["rule"]["checks"],
                    },
                }
                for it in items
            ],
        },
        ensure_ascii=False,
    )


def _answers_by_clause(answer: dict, items: list[dict]) -> dict[str, dict]:
    results = answer.get("results")
    if results is None and "classification" in answer and len(items) == 1:
        # A model may answer a single-clause question with a bare object.
        results = [{**answer, "ma": items[0]["internal"]["clause_id"]}]
    out = {}
    for r in results or []:
        if isinstance(r, dict) and r.get("ma"):
            out[str(r["ma"])] = r
    return out


def _grounded(obligation: dict, internal: dict, r: dict | None):
    if not r:
        return None
    label = str(r.get("classification", "")).upper()
    src = _locate(obligation["text"], r.get("source_quote"))
    tgt = _locate(internal["text"], r.get("target_quote"))
    if label in LABELS and src is not None and tgt is not None:
        return label, src, tgt
    return None


def _merge(obligation, reg_clause_text, internal, rule, r, grounded, diff=None) -> dict:
    """Combine the rule result with one LLM answer (or its grounding failure). Fail closed."""
    result = {**rule, "method": "rule"}
    checks = list(rule["checks"])
    if grounded is None:
        checks.append(
            {
                "check": "source_grounding",
                "status": "fail",
                "detail": {
                    "reason": "LLM label or quote not found verbatim in the sources",
                    "llm_label": (r or {}).get("classification"),
                    "source_quote": str((r or {}).get("source_quote"))[:300],
                    "target_quote": str((r or {}).get("target_quote"))[:300],
                },
            }
        )
        result["checks"] = checks
        return result
    label, src, tgt = grounded
    checks.append(
        {"check": "source_grounding", "status": "pass", "detail": "LLM quotes found verbatim"}
    )
    conflict = rule["category"] in ("VALUE_CHANGE", "CONTRADICTION")
    if conflict and label in ("EQUIVALENT", "INDIRECT_IMPACT"):
        # Fail closed: a rule-detected conflict is never overridden as safe.
        checks.append(
            {
                "check": "verifier_agreement",
                "status": "fail",
                "detail": f"rule={rule['category']} llm={label}; giữ nhãn rule",
            }
        )
    else:
        result.update(
            category=label,
            rationale=str(r.get("rationale", ""))[:2000] or rule["rationale"],
            confidence=_clamp(r.get("confidence")),
        )
        if not (conflict and label == rule["category"]):
            # Same conflict as the rule: keep the rule's exact value spans, which a minimal
            # patch needs; otherwise use the LLM's verified quotes.
            o_start = obligation["span_start"]
            result.update(
                source_span=_span(reg_clause_text, o_start + src[0], o_start + src[1]),
                target_span=_span(internal["text"], *tgt),
            )
            # Narrow a broad LLM quote to the typed span that differs, for a minimal patch.
            snapped = diff and spans.typed_target_span(diff, tgt, _SNAP_TYPES.get(label, ()))
            if snapped:
                result["target_span"] = _span(internal["text"], snapped["start"], snapped["end"])
                result["llm_target_quote"] = _span(internal["text"], *tgt)
        if conflict:
            checks.append(
                {
                    "check": "verifier_agreement",
                    "status": "pass" if label == rule["category"] else "warn",
                    "detail": f"rule={rule['category']} llm={label}",
                }
            )
    result["method"] = "llm+rule"
    result["conditions_to_verify"] = [str(c) for c in r.get("conditions_to_verify", [])][:10]
    result["checks"] = checks
    return result


def judge_group(
    obligation: dict,
    reg_clause_text: str,
    items: list[dict],
    use_llm: bool,
    refresh: bool = False,
) -> tuple[list[dict], dict]:
    """Compare one obligation with all its candidate clauses in a single LLM call (06.1–06.2).

    items: [{"internal": clause, "evidence": {span, shared_terms}, "context": [...]}].
    Returns one result per item (same order) and call stats. Ungrounded answers are asked once
    more without the cache; what is still ungrounded falls back to the rule result.
    """
    for it in items:
        it["span_diff"] = _span_diff(obligation["text"], it["internal"]["text"])
        it["rule"] = rule_classify(
            obligation, reg_clause_text, it["internal"]["text"], it["evidence"], it["span_diff"]
        )
    stats = {"llm_calls": 0, "cache_hits": 0, "best": None}
    if not use_llm or not items:
        return [{**it["rule"], "method": "rule"} for it in items], stats

    payload = _group_payload(obligation, reg_clause_text, items)
    answers: dict[str, dict] = {}
    grounded: dict[str, tuple] = {}
    try:
        for attempt in range(2):
            answer, cached = llm.chat_json_cached(
                "judge_group", SYSTEM, payload, refresh=refresh or attempt > 0
            )
            stats["cache_hits" if cached else "llm_calls"] += 1
            stats["best"] = stats["best"] or answer.get("best")
            for cid, r in _answers_by_clause(answer, items).items():
                if cid in grounded:
                    continue
                answers[cid] = r
                internal = next(
                    (it["internal"] for it in items if it["internal"]["clause_id"] == cid), None
                )
                g = _grounded(obligation, internal, r) if internal else None
                if g:
                    grounded[cid] = g
            if len(grounded) == len(items):
                break
    except Exception as exc:  # LLM down or malformed: keep the rule results, say so
        error = {"check": "llm_judge", "status": "error", "detail": str(exc)[:200]}
        return [
            {**it["rule"], "method": "rule", "checks": [*it["rule"]["checks"], error]}
            for it in items
        ], stats

    results = []
    for it in items:
        cid = it["internal"]["clause_id"]
        merged = _merge(
            obligation,
            reg_clause_text,
            it["internal"],
            it["rule"],
            answers.get(cid),
            grounded.get(cid),
            it["span_diff"],
        )
        merged["llm_best"] = stats["best"] == cid
        results.append(merged)
    return results, stats


def _span_diff(source: str, target: str) -> dict | None:
    """NLP span diff, or None when disabled or failing (it only adds hints and precision)."""
    if not get_settings().span_detection_enabled:
        return None
    try:
        return spans.span_diff(source, target)
    except Exception as exc:
        log.warning("span detection failed: %s", exc)
        return None


def classify(
    obligation: dict,
    reg_clause_text: str,
    internal: dict,
    evidence: dict,
    context: list[dict],
    use_llm: bool,
) -> dict:
    """Single-pair form of judge_group."""
    results, _ = judge_group(
        obligation,
        reg_clause_text,
        [{"internal": internal, "evidence": evidence, "context": context}],
        use_llm,
    )
    return results[0]


def _pair_detail(p: dict) -> str:
    s, t = p["source"], p["target"]
    verdict = "conflict" if p["conflict"] else "ok"
    return f"{s.text.strip()} ({s.bound}) vs {t.text.strip()} → {verdict}"


def _clamp(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _bound_vi(bound: str) -> str:
    return {"max": "mức tối đa", "min": "mức tối thiểu"}.get(bound, "giá trị cụ thể")


def _modality_vi(modality: str) -> str:
    return {"must": "bắt buộc", "must_not": "cấm"}.get(modality, "cho phép")
