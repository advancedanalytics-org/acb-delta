"""Does an obligation bind the bank? Decided before retrieval so Engine 1/2 skip noise.

Rules settle the clear cases from the subject (state bodies and data subjects: no; credit
institutions, controllers/processors, "cơ quan, tổ chức, cá nhân": yes). The rest goes to the LLM
in batches. Results are stored on the obligation row and reused by later runs. "uncertain" and
LLM failures keep the obligation in scope: recall comes first (design section 02).

With refine=True the same LLM call also re-reads each rule-extracted obligation (subject, action,
object, condition, deadline, exception; RIA 4.0 "LLM + Pydantic"). Answers are validated with
Pydantic and every field must be a verbatim phrase of the obligation (the subject may also come
from the lead-in or the article heading); anything else keeps the rule value. Modality and the
span stay rule-owned. Refined fields are stored on the row with the original rule values in
rule_fields, so each obligation is refined once.
"""

import json
import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator
from sqlalchemy import text

from app.config import get_settings
from app.ria import llm
from app.ria.textutil import syllables

log = logging.getLogger(__name__)

# Duties of state bodies bind no bank unit.
STATE_SUBJECT = re.compile(
    r"^(Bộ\s|Bộ trưởng|Chính phủ|Thủ tướng|Ủy ban nhân dân|Ủy ban Nhân dân|Cơ quan chuyên trách|"
    r"Cơ quan quản lý nhà nước|Cơ quan nhà nước|Ngân hàng Nhà nước|Thống đốc|Thanh tra|Quốc hội|"
    r"Tòa án|Viện kiểm sát)",
)
# Natural persons acting for themselves: data subjects, citizens, users.
PERSON_SUBJECT = re.compile(
    r"^(Chủ thể dữ liệu|chủ thể dữ liệu|Người dân|Công dân|Người sử dụng|Người dùng|"
    r"Trẻ em|Cha, mẹ|Người giám hộ|Người đại diện của chủ thể)",
)
# Roles a bank or its units hold.
BANK_SUBJECT = re.compile(
    r"(tổ chức tín dụng|ngân hàng|chi nhánh ngân hàng nước ngoài|bên kiểm soát|bên xử lý|"
    r"cơ quan, tổ chức, cá nhân|tổ chức, cá nhân|tổ chức, doanh nghiệp|doanh nghiệp|"
    r"bên triển khai|đơn vị)",
    re.IGNORECASE,
)

BATCH_SIZE = 20

SYSTEM = """Bạn là chuyên viên pháp chế của một ngân hàng thương mại cổ phần tại Việt Nam (ACB).
Với mỗi nghĩa vụ trích từ văn bản pháp luật, xác định nghĩa vụ đó có ràng buộc trực tiếp
ngân hàng hoặc một đơn vị của ngân hàng (với tư cách tổ chức tín dụng, doanh nghiệp, bên kiểm soát
hoặc xử lý dữ liệu, người sử dụng lao động, bên triển khai hệ thống...) hay không.
- "yes": ngân hàng phải thực hiện / không được làm điều này.
- "no": nghĩa vụ chỉ của cơ quan nhà nước, cá nhân tự thân (chủ thể dữ liệu, người dân),
  hoặc loại chủ thể mà ngân hàng không thể là.
- "uncertain": không đủ căn cứ.
Trả về DUY NHẤT JSON: {"items": [{"id": "<id>", "applies": "yes|no|uncertain",
"reason": "<lý do ngắn tiếng Việt>"}]} với đủ mọi id được hỏi."""


REFINE_SYSTEM = """Bạn là chuyên viên pháp chế của một ngân hàng thương mại cổ phần tại Việt Nam
(ACB). Mỗi mục là một nghĩa vụ trích từ văn bản pháp luật: "nghia_vu" (nguyên văn), "cau_dan"
(câu dẫn của khoản/điểm cha, có thể rỗng), "dieu" (tên Điều), "rule" (kết quả tách bằng luật,
có thể sai). Với mỗi mục làm hai việc.

1. Tách nghĩa vụ. Mỗi trường CHÉP NGUYÊN VĂN một cụm liên tục trong "nghia_vu" (riêng subject
   được lấy từ "cau_dan" hoặc "dieu" khi "nghia_vu" không nêu chủ thể); không diễn giải, không
   thêm từ, không bao giờ chứa nhãn điểm/khoản như "a)", "b)", "1.".
   - subject: chủ thể phải / không được / được làm việc này (với câu bị động, là bên thực hiện).
   - action: cụm động từ chính, ngắn, không gồm từ chỉ mức bắt buộc (phải, không được, có quyền,
     có trách nhiệm...).
   - object: đối tượng / nội dung của hành động.
   - condition: điều kiện áp dụng ("khi...", "trường hợp...", "trước khi..."), hoặc null.
   - deadline: thời hạn, tần suất, số tiền, tỷ lệ, hoặc null.
   - exception: ngoại lệ ("trừ trường hợp...", "trừ khi..."), hoặc null.
2. applies: nghĩa vụ có ràng buộc trực tiếp ngân hàng hoặc một đơn vị của ngân hàng (tổ chức tín
   dụng, doanh nghiệp, bên kiểm soát hoặc xử lý dữ liệu, người sử dụng lao động, bên triển khai
   hệ thống...) không.
   - "yes": ngân hàng phải thực hiện / không được làm điều này.
   - "no": chỉ của cơ quan nhà nước, cá nhân tự thân (chủ thể dữ liệu, người dân), hoặc loại
     chủ thể mà ngân hàng không thể là.
   - "uncertain": không đủ căn cứ.
Trả về DUY NHẤT JSON: {"items": [{"id": "<id>", "subject": "...", "action": "...",
"object": "...", "condition": null, "deadline": null, "exception": null,
"applies": "yes|no|uncertain", "reason": "<lý do ngắn tiếng Việt>"}]} với đủ mọi id được hỏi."""

# A null or empty answer keeps the rule value: the rule found it verbatim in the text.
FIELDS = ("subject", "action", "object", "condition", "deadline", "exception")


class ObligationAnswer(BaseModel):
    """One item of the LLM answer. Invalid items are dropped, not the whole batch."""

    id: str
    subject: str | None = None
    action: str | None = None
    object: str | None = None
    condition: str | None = None
    deadline: str | None = None
    exception: str | None = None
    applies: Literal["yes", "no", "uncertain"] | None = None
    reason: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _id_text(cls, v):
        return str(v) if v is not None else v

    @field_validator("applies", mode="before")
    @classmethod
    def _applies_known(cls, v):
        v = str(v or "").strip().lower()
        return v if v in ("yes", "no", "uncertain") else None

    @field_validator("reason", mode="before")
    @classmethod
    def _reason_text(cls, v):
        return str(v or "")[:300]


def _verbatim(value: str, sources: list[str | None]) -> bool:
    """value is a run of whole syllables of one source (case, spacing, punctuation ignored)."""
    words = " ".join(syllables(value))
    return bool(words) and any(
        f" {words} " in f" {' '.join(syllables(src))} " for src in sources if src
    )


def grounded_fields(obligation: dict, answer: ObligationAnswer) -> tuple[dict, int]:
    """Fields to apply from a validated answer, and how many answered fields were rejected."""
    text_only = [obligation["text"]]
    # Points under a lead-in name no subject: it comes from the lead-in or the article heading.
    subject_sources = [
        *text_only,
        obligation.get("parent_text"),
        obligation.get("article_heading"),
        obligation.get("subject"),
    ]
    fields, rejected = {}, 0
    for name in FIELDS:
        value = (getattr(answer, name) or "").strip(" ,;:.-–\n")
        if not value:
            continue
        if _verbatim(value, subject_sources if name == "subject" else text_only):
            fields[name] = value
        else:
            rejected += 1
    return fields, rejected


def refined(obligation: dict) -> bool:
    return str(obligation.get("extraction_method") or "").startswith("rule+llm")


def rule_decision(obligation: dict) -> tuple[str, str] | None:
    subject = (obligation.get("subject") or "").strip()
    if STATE_SUBJECT.match(subject):
        return "no", f"chủ thể là cơ quan nhà nước: {subject[:80]}"
    if PERSON_SUBJECT.match(subject):
        return "no", f"chủ thể là cá nhân tự thân: {subject[:80]}"
    if BANK_SUBJECT.search(subject):
        return "yes", f"chủ thể bao gồm ngân hàng: {subject[:80]}"
    return None


def _ask_batch(batch: list[dict], refine: bool, refresh: bool) -> dict[str, ObligationAnswer]:
    if refine:
        items = [
            {
                "id": o["obligation_id"],
                "nghia_vu": o["text"][:600],
                "cau_dan": (o.get("parent_text") or "")[:300],
                "dieu": o.get("article_heading"),
                "rule": {name: o.get(name) for name in FIELDS},
            }
            for o in batch
        ]
        kind, system = "obligation_refine", REFINE_SYSTEM
    else:
        items = [
            {
                "id": o["obligation_id"],
                "chu_the": o.get("subject"),
                "dieu": o.get("article_heading"),
                "nghia_vu": o["text"][:600],
            }
            for o in batch
        ]
        kind, system = "applicability", SYSTEM
    payload = json.dumps(items, ensure_ascii=False)
    answer, _ = llm.chat_json_cached(kind, system, payload, refresh=refresh)
    out = {}
    for item in answer.get("items", []) if isinstance(answer, dict) else []:
        try:
            parsed = ObligationAnswer.model_validate(item)
        except ValidationError:
            continue
        if parsed.id:
            out[parsed.id] = parsed
    return out


def classify_obligations(
    conn,
    obligations: list[dict],
    use_llm: bool,
    refresh: bool = False,
    refine: bool = False,
    stats: Counter | None = None,
) -> dict[str, str]:
    """applicability per obligation_id; stored decisions are reused unless refresh.

    refine=True (needs use_llm) also refines rule-extracted fields; the obligation dicts are
    updated in place so retrieval and comparison use the refined fields.
    """
    stats = stats if stats is not None else Counter()
    refine = refine and use_llm
    result: dict[str, str] = {}
    to_store: list[dict] = []
    to_refine: list[dict] = []
    pending: list[dict] = []
    for o in obligations:
        needs_refine = refine and (refresh or not refined(o))
        if o.get("applicability") and not refresh and not needs_refine:
            result[o["obligation_id"]] = o["applicability"]
            continue
        decided = None if needs_refine else rule_decision(o)
        if decided:
            result[o["obligation_id"]] = decided[0]
            to_store.append(
                {"id": o["obligation_id"], "a": decided[0], "r": decided[1], "m": "rule"}
            )
        elif use_llm:
            pending.append(o)
        else:
            result[o["obligation_id"]] = "uncertain"  # not stored: an LLM may decide later

    if pending:
        batches = [pending[i : i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]
        workers = max(1, min(len(batches), get_settings().llm_concurrency))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ria-applies") as pool:
            futures = [(b, pool.submit(_ask_batch, b, refine, refresh)) for b in batches]
        method = f"llm:{llm.llm_model()}"
        for batch, future in futures:
            try:
                answers = future.result()
            except Exception as exc:  # LLM down: keep these in scope, decide next run
                log.warning("applicability batch failed: %s", exc)
                stats["llm_failed"] += len(batch)
                answers = {}
            for o in batch:
                oid = o["obligation_id"]
                answer = answers.get(oid)
                if answer and refine:
                    fields, rejected = grounded_fields(o, answer)
                    stats["fields_rejected"] += rejected
                    if fields:
                        stats["refined"] += 1
                    rule_fields = {name: o.get(name) for name in FIELDS}
                    o.update(fields)
                    o["extraction_method"] = f"rule+{method}"
                    to_refine.append(
                        {
                            "id": oid,
                            **{name: o.get(name) for name in FIELDS},
                            "m": o["extraction_method"],
                            "rf": json.dumps(rule_fields, ensure_ascii=False),
                        }
                    )
                # Rules on the (refined) subject first; the LLM decides only what they cannot.
                decided = rule_decision(o)
                if decided:
                    result[oid] = decided[0]
                    to_store.append({"id": oid, "a": decided[0], "r": decided[1], "m": "rule"})
                elif answer and answer.applies:
                    result[oid] = answer.applies
                    to_store.append(
                        {"id": oid, "a": answer.applies, "r": answer.reason, "m": method}
                    )
                else:
                    result[oid] = "uncertain"

    if to_refine:
        conn.execute(
            text(
                "UPDATE obligation SET subject = :subject, action = :action, object = :object, "
                "condition = :condition, deadline = :deadline, exception = :exception, "
                "extraction_method = :m, "
                "rule_fields = COALESCE(rule_fields, CAST(:rf AS jsonb)) "
                "WHERE obligation_id = :id"
            ),
            to_refine,
        )
    if to_store:
        conn.execute(
            text(
                "UPDATE obligation SET applicability = :a, applicability_reason = :r, "
                "applicability_method = :m WHERE obligation_id = :id"
            ),
            to_store,
        )
    return result
