# Báo cáo tiến độ nhóm — 18/10/2026

Nguồn: `PLAN.md` + git log `origin/main` @ `87773f3` (sau PR #27). Không còn PR mở trước khi tạo PR #28 (đồng bộ `PLAN.md` theo báo cáo này).

## 1. Trạng thái theo người

### Tài

| Task | Trạng thái | Chi tiết |
|---|---|---|
| TAI-01 Agent gợi ý chỉnh sửa | ✅ Xong | Skeleton LangGraph (#7); Engine A `POST /draft` → patch tối thiểu `REPLACE`/`INSERT`/`DELETE` + verifier (#21) |
| TAI-02 HITL | ✅ Xong | Bảng + API quyết định (#9); bridge RIA → gói review (#23); UI đọc gói review (#24); card hiện đề xuất AI + accept/reject (#25); E2E thật trên model GCP |
| TAI-03 VBPL + mock nội bộ | ✅ Xong | Ground truth có mâu thuẫn cài sẵn cho eval |
| TAI-04 Slide | ⬜ Chưa | |
| TAI-05 Thuyết trình + kịch bản demo | ⬜ Chưa | |
| TAI-06 Deploy Phase 1 | ✅ Xong | Stack local + `scripts/run.sh`; GCP demo VM tự deploy từ `main` (#14, #17, #18, #26, #27): Gemini 4 Argon, Vertex semantic ranker, bge-m3 |
| TAI-07 Deploy GreenNode | ⬜ Hoãn | Tạm demo trên GCP VM; chuyển khi có tài khoản GreenNode |

### Khoa

| Task | Trạng thái | Chi tiết |
|---|---|---|
| KHOA-01 Evaluation pipeline | 🟡 Đang làm | Có: metric core + dataset schema (#5), `docs/evaluation-data-contract.md` (#11), API `/api/eval/runs` (#16). Metric đã code: tách thay đổi P/R, retrieval Recall@k + MRR, phát hiện tác động P/R/F1. Chưa: Langfuse dataset, LLM-as-judge cho bản sửa, số đo latency/cost, enrich test set từ HITL, lượt chạy experiment thật |
| KHOA-02 Feedback loop (RLHF) | ⬜ Chưa | Đầu vào `GET /api/feedback` sẵn sàng (TAI-02), luồng dữ liệu đã chốt |

### Huy

| Task | Trạng thái | Chi tiết |
|---|---|---|
| HUY-01 UI | ✅ Xong | 5 màn hình, nối live API, upload VBPL, PDF viewer highlight bbox theo trạng thái, phím tắt A/E/R/J/K, toast Undo, optimistic update, user switcher (#6, #10, #20, #22) |
| HUY-02 Pipeline PDF NHNN | ✅ Xong | PyMuPDF giữ page + bbox, chunk theo Điều/Khoản, embed → pgvector, upload MinIO |

### Minh

| Task | Trạng thái | Chi tiết |
|---|---|---|
| MINH-01 Embed + search pgvector | 🟡 Đang làm | Có: ingest + analyze RIA (#12), hybrid search, rerank, lọc applicability, gộp LLM judge, cache LLM (#19). Chưa: chốt model embedding trên MaaS, chốt schema chunk |
| MINH-02 Format tài liệu mock | ✅ Xong | `db/DOC-102.md` → `db/DOC-102.parsed.json`, mô hình dữ liệu `db/data-model.md` |

## 2. Lệch giữa PLAN.md và code (trước PR #28)

1. HUY-01: UI đã đủ nhưng checkbox còn `[ ]`.
2. KHOA-01: 3 PR đã merge nhưng checkbox metric còn `[ ]`.
3. MINH-02: format đã dùng thực tế nhưng "Quyết định đã thống nhất" ghi `_chưa chốt_`.
4. MINH-01 "Đóng gói tool retrieve cho agent": theo Engine A agent không tự retrieve → có thể lỗi thời (chưa sửa, chờ Minh).

## 3. Quyết định trong buổi này

- Tài cập nhật checkbox HUY-01 / KHOA-01 / MINH-02 thay owner (owner kiểm tra lại trong PR #28).
- Tạm thời demo trên GCP VM; TAI-07 (GreenNode) hoãn đến khi có tài khoản.

## 4. Thay đổi trong PR #28 (`PLAN.md`)

- HUY-01 → `[x]` toàn bộ mục con.
- KHOA-01 giữ `[~]`; tick 3 nhóm metric đã code; ghi chú data contract + `/api/eval/runs`; metric hệ thống giữ `[ ]` (có hàm, chưa có nguồn đo).
- MINH-02 → `[x]`; ghi format mock vào "Quyết định đã thống nhất".
- TAI-07: ghi chú demo trên GCP VM.

## 5. Ưu tiên tiếp theo (để kịp demo)

1. Khoa: chạy eval thật trên đường RIA; làm KHOA-02 few-shot → số liệu trước/sau feedback.
2. Huy: dashboard Evaluation hiển thị run thật từ `/api/eval/runs`.
3. Minh: chốt model embedding + schema chunk, ghi vào PLAN.md.
4. Tài: TAI-04 slide, TAI-05 kịch bản demo.

## Câu hỏi chưa giải quyết

- MINH-01 mục "Đóng gói tool retrieve cho agent" còn cần không (Engine A)?
- Chốt chính thức `bge-m3` (1024 dims) làm model embedding? Code + GCP VM đang dùng nhưng PLAN.md vẫn `_chưa chốt_`.
