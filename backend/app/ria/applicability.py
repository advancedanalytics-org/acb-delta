"""Does an obligation bind the bank? Decided before retrieval so Engine 1/2 skip noise.

Rules settle the clear cases from the subject (state bodies and data subjects: no; credit
institutions, controllers/processors, "cơ quan, tổ chức, cá nhân": yes). The rest goes to the LLM
in batches. Results are stored on the obligation row and reused by later runs. "uncertain" and
LLM failures keep the obligation in scope: recall comes first (design section 02).
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

from app.config import get_settings
from app.ria import llm

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


def rule_decision(obligation: dict) -> tuple[str, str] | None:
    subject = (obligation.get("subject") or "").strip()
    if STATE_SUBJECT.match(subject):
        return "no", f"chủ thể là cơ quan nhà nước: {subject[:80]}"
    if PERSON_SUBJECT.match(subject):
        return "no", f"chủ thể là cá nhân tự thân: {subject[:80]}"
    if BANK_SUBJECT.search(subject):
        return "yes", f"chủ thể bao gồm ngân hàng: {subject[:80]}"
    return None


def _ask_batch(batch: list[dict], refresh: bool) -> dict[str, tuple[str, str]]:
    payload = json.dumps(
        [
            {
                "id": o["obligation_id"],
                "chu_the": o.get("subject"),
                "dieu": o.get("article_heading"),
                "nghia_vu": o["text"][:600],
            }
            for o in batch
        ],
        ensure_ascii=False,
    )
    answer, _ = llm.chat_json_cached("applicability", SYSTEM, payload, refresh=refresh)
    out = {}
    for item in answer.get("items", []):
        applies = str(item.get("applies", "")).lower()
        if applies in ("yes", "no", "uncertain") and item.get("id"):
            out[str(item["id"])] = (applies, str(item.get("reason", ""))[:300])
    return out


def classify_obligations(
    conn, obligations: list[dict], use_llm: bool, refresh: bool = False
) -> dict[str, str]:
    """applicability per obligation_id; stored decisions are reused unless refresh."""
    result: dict[str, str] = {}
    to_store: list[dict] = []
    pending: list[dict] = []
    for o in obligations:
        if o.get("applicability") and not refresh:
            result[o["obligation_id"]] = o["applicability"]
            continue
        decided = rule_decision(o)
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
            futures = [(b, pool.submit(_ask_batch, b, refresh)) for b in batches]
        method = f"llm:{llm.llm_model()}"
        for batch, future in futures:
            try:
                answers = future.result()
            except Exception as exc:  # LLM down: keep these in scope, decide next run
                log.warning("applicability batch failed: %s", exc)
                answers = {}
            for o in batch:
                oid = o["obligation_id"]
                if oid in answers:
                    applies, reason = answers[oid]
                    result[oid] = applies
                    to_store.append({"id": oid, "a": applies, "r": reason, "m": method})
                else:
                    result[oid] = "uncertain"

    if to_store:
        conn.execute(
            text(
                "UPDATE obligation SET applicability = :a, applicability_reason = :r, "
                "applicability_method = :m WHERE obligation_id = :id"
            ),
            to_store,
        )
    return result
