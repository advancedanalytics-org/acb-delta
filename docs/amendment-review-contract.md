# Hợp đồng soạn patch (M04) và review HITL (M05 backend)

Áp dụng blueprint RIA 4.0 (`docs/ACB_RIA_4_0_Final_E2E_6_Modules_6_Owners.html`, mục §07 Amendment Intelligence và §08 Review & Feedback) với engine **A**: RIA (`MINH-01`, M01–M03, xem `docs/ria-ingest-analyze.md`) tìm `impact_finding`, agent (`TAI-01`) chỉ soạn patch, backend (`TAI-02`) đưa finding vào HITL. Quyết định ghi trong `PLAN.md` → *Quyết định đã thống nhất*.

```text
POST /api/regulations/{id}/analyze ─► job analyze ─► impact_finding (AI_PROPOSED)
POST /api/analyses/{job_id}/review ─► job review ─► mỗi finding: agent POST /draft
                                                  ─► vbpls (1 / job analyze) + impacts (+patch)
UI  ── GET /api/vbpls · /api/vbpls/{id}/impacts · POST/DELETE /api/decisions · GET /api/audit
KHOA-02 ── GET /api/feedback
```

## 1. Agent `POST /draft` (M04)

Một finding vào, một patch tối thiểu ra. Không bao giờ tự duyệt: trạng thái cao nhất là `review_required`.

### Request

```json
{
  "finding_id": "RIA-1a2b3c4d5e",
  "category": "VALUE_CHANGE",
  "rationale": "Quy định mới: tối đa 12 tháng; nội bộ: 24 tháng.",
  "obligation": {"clause_id": "REG-99-2026-TT-NHNN@v1#2.1", "text": "Tổ chức tín dụng phải rà soát … tối đa 12 tháng một lần."},
  "source_span": {"text": "tối đa 12 tháng", "start": 70, "end": 85},
  "clause": {"clause_id": "DOC-102@v4#5.2", "numbering": "5.2", "text": "… định kỳ 24 tháng một lần."},
  "target_span": {"text": "24 tháng", "start": 50, "end": 58},
  "citations": ["REG-99-2026-TT-NHNN@v1#2.1", "DOC-102@v4#5.2"]
}
```

`target_span` có thể `null`. Khi có, phải đúng `clause.text[start:end]` (sai → `422`).

### Response `AmendmentProposal v1`

```json
{
  "finding_id": "RIA-1a2b3c4d5e",
  "clause_id": "DOC-102@v4#5.2",
  "operation": "REPLACE",
  "start": 50, "end": 58,
  "old_text": "24 tháng",
  "new_text": "tối đa 12 tháng",
  "rationale": "…",
  "legal_evidence_ids": ["REG-99-2026-TT-NHNN@v1#2.1"],
  "verification": {
    "status": "review_required",
    "reason": null,
    "checks": [
      {"check": "span_matches_source", "status": "pass"},
      {"check": "span_unique", "status": "pass"},
      {"check": "inside_target_span", "status": "pass"},
      {"check": "minimal_change", "status": "pass"},
      {"check": "independent_verifier", "status": "pass", "detail": "…"}
    ]
  },
  "model": "qwen3-next-80b",
  "prompt_version": "3f9c0a1b2d4e"
}
```

| Trường | Quy tắc |
|---|---|
| `operation` | `REPLACE` \| `INSERT` \| `DELETE`; `null` khi `failed` |
| `start`, `end` | offset trong `clause.text`. `REPLACE`/`DELETE`: `old_text == clause.text[start:end]`. `INSERT`: `start == end == target_span.end` (không có `target_span`: cuối điều khoản), `old_text == ""`, agent tự thêm dấu cách hai bên nếu cần |
| `new_text` | `""` khi `DELETE` |
| `legal_evidence_ids` | các `citations` thuộc cùng văn bản với `obligation.clause_id`; không có thì `[obligation.clause_id]` |
| `verification.status` | `review_required` (con người quyết) hoặc `failed` (không có patch dùng được; `operation`/`start`/`end`/`old_text`/`new_text` = `null`, `reason` ghi lý do ngắn, chỉ tên loại lỗi khi LLM lỗi). `checks` có thể rỗng khi LLM soạn lỗi ngay lần đầu |
| `prompt_version` | sha256 của system prompt + JSON schema output (drafter, verifier), 12 ký tự đầu |

Các check (`status`: `pass` \| `fail` \| `warn` \| `skipped`):

| Check | Loại | Fail khi |
|---|---|---|
| `span_matches_source` | quy tắc | `old_text` không có trong `clause.text` (khoảng trắng được phép khác, chữ thì không; không khớp giữa một từ: `30 ngày` không khớp trong `130 ngày`) |
| `span_unique` | quy tắc | `old_text` xuất hiện nhiều lần, kể cả chồng lấn (locator không duy nhất). Nhiều lần nhưng đúng một lần nằm trong `target_span` vẫn là duy nhất |
| `inside_target_span` | quy tắc | có `target_span` mà vùng sửa nằm ngoài nó (`skipped` khi không có `target_span`) |
| `minimal_change` | quy tắc | `new_text == old_text`, hoặc patch rỗng. `warn` khi thay > 50% điều khoản |
| `independent_verifier` | LLM (lần gọi thứ 2, prompt khác) | verifier không đồng ý. Chỉ tư vấn: không chặn, không duyệt. Lỗi LLM → `skipped` |

Bốn check quy tắc (trừ `warn`) fail, hoặc LLM soạn lỗi → agent gọi lại bước soạn một lần kèm lý do; vẫn fail → `failed`.

## 2. Bảng HITL mở rộng (M05)

Mọi cột mới đều nullable, dòng cũ từ `/invoke` vẫn hợp lệ.

| Bảng.cột | Kiểu | Giá trị |
|---|---|---|
| `vbpls.ria_job_id` | text, unique | job analyze của RIA; một gói review cho mỗi job |
| `impacts.finding_id` | text, index | `impact_finding.finding_id` |
| `impacts.category` | varchar(32) | category gốc của RIA |
| `impacts.patch` | jsonb | `{operation, start, end, old_text, new_text}` = dữ liệu before/after cho redline |
| `impacts.draft_status` | varchar(16) | `review_required` \| `failed` \| `skipped` (`ok` dành cho sau này nếu có tự duyệt) |
| `impacts.draft_error` | text | lý do ngắn khi `failed` / `skipped` |

Không ghi bảng `amendment` của RIA.

### Category → `type` của UI

| RIA `category` | `type` | Soạn patch? |
|---|---|---|
| `VALUE_CHANGE`, `CONTRADICTION`, `SCOPE_CHANGE` | `conflict` | có (thường `REPLACE`) |
| `ADDITION` | `new_obligation` | có (`INSERT` sau `target_span`, hoặc `REPLACE` trong nó) |
| `INDIRECT_IMPACT` | `outdated_reference` | có nếu có `target_span`, không thì `skipped` |
| `EQUIVALENT` (`NO_ACTION_PROPOSED`) | — | không nhập |

`severity` = `priority` của RIA (`high` \| `medium` \| `low`). Finding không có `target_span` (RIA hiện luôn ghi `target_span`, nên đây là phòng hờ) vẫn được nhập với `draft_status = skipped`, backend không gọi `/draft`. Nhánh `INSERT` cuối điều khoản của agent chỉ dành cho caller khác gọi thẳng `/draft`.

### Cột `impacts` lấy từ đâu

| Cột | Nguồn |
|---|---|
| `document_id` | `impact_finding.impacted_document_id` |
| `chunk_id` | `impact_finding.internal_clause_id` |
| `location` | numbering của điều khoản nội bộ |
| `change_clause` | numbering của điều khoản VBPL chứa nghĩa vụ |
| `citation` | text của `source_span` (đoạn VBPL làm căn cứ) |
| `affected_text` | text điều khoản nội bộ |
| `suggested_text` | `affected_text` sau khi áp patch; `""` khi không có patch |
| `page`, `bboxes` | từ `clause.bbox` (`[[page, x0, y0, x1, y1], …]`): `page` = trang của box đầu, `bboxes` = các box cùng trang đó; `null` / `[]` khi không có bbox |
| `reasoning` | `impact_finding.rationale` |
| `model_output` | `{"finding": <impact_finding>, "draft": <AmendmentProposal> \| null}`: RLHF cần biết bước nào bị người duyệt sửa (`edit` ≈ lỗi drafter, `reject` ≈ lỗi judge của RIA) |

## 3. `POST /api/analyses/{job_id}/review`

- `404` khi job không tồn tại hoặc không phải `analyze`; `409` khi job chưa `succeeded`.
- `202 {vbpl_id, review_job_id}` khi tạo gói mới. Gọi lại: `200` với gói hiện có; nếu job review trước `failed` thì chỉ chạy lại các finding còn thiếu.
- Job `review` chạy trên runner của RIA (`backend/app/ria/jobs.py`), theo dõi qua `GET /api/jobs/{review_job_id}`.
- Lỗi agent ở một finding → impact đó `draft_status = failed`, các finding khác vẫn chạy. Chỉ lỗi DB / hạ tầng mới làm gói `failed`.
- Song song tối đa `REVIEW_DRAFT_CONCURRENCY` (mặc định 4) lời gọi `/draft`.

## 4. `GET /api/feedback`

Một dòng cho mỗi impact có quyết định còn hiệu lực (mới nhất, `undone_at IS NULL`). Lọc: `since`, `vbplId`.

| `action` | `chosen` | `rejected` |
|---|---|---|
| `accept` | `suggested_text` | `null` |
| `edit` | `edited_text` | `suggested_text` |
| `reject` | `affected_text` | `suggested_text` |

Impact `draft_status = failed` (hoặc không có patch): `rejected = null`, vì không có văn bản AI để học. Quyết định đã undo không có trong feedback nhưng vẫn ở bảng `decisions` cho audit. Theo `docs/evaluation-data-contract.md`.
