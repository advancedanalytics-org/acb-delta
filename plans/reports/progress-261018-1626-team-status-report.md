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

## 2. Công việc đã hoàn thành đến hiện tại

27 PR đã merge vào `main` (giờ merge theo giờ Việt Nam). #8 cùng nội dung với #9 (stacked PR).

### 17/10

| PR | Giờ | Người | Task | Công việc |
|---|---|---|---|---|
| #1 | 10:07 | Tài | — | Rule chung cho coding agent (`AGENTS.md`) + workflow CI |
| #2 | 12:53 | Tài | TAI-06 | Skeleton dự án: backend FastAPI, agent, frontend prototype 5 màn hình, Docker Compose |
| #3 | 13:00 | Tài | TAI-06 | `scripts/run.sh` chạy / kiểm tra stack local |
| #4 | 13:03 | Tài | TAI-06 | Hướng dẫn agent dùng `run.sh` |
| #6 | 22:11 | Huy | HUY-01/02 | UI + API ingest PDF, gợi ý AI; dialog upload VBPL, PDF viewer highlight, trang audit |
| #5 | 22:17 | Khoa | KHOA-01 | Metric core (P/R/F1, Recall@k, MRR) + dataset schema |

### 18/10

| PR | Giờ | Người | Task | Công việc |
|---|---|---|---|---|
| #7 | 01:25 | Tài | TAI-01 | Agent LangGraph: `extract_changes` → fan-out → `judge_impact` → `draft_amendment` |
| #9 | 09:30 | Tài | TAI-02 | Bảng HITL + API quyết định accept / edit / reject / undo (audit append-only) |
| #10 | 10:05 | Huy | HUY-02 | Tăng giới hạn file, cải thiện chunker + vector store |
| #11 | 10:38 | Khoa | KHOA-01 | `docs/evaluation-data-contract.md` |
| #12 | 10:39 | Minh | MINH-01 | API ingest văn bản + phân tích tác động RIA (`/api/regulations/{id}/analyze`), mẫu `db/DOC-102.*`, `db/data-model.md` |
| #13 | 10:59 | Tài | TAI-02 | Sửa lỗi PDF viewer khi impact không có trang |
| #14 | 11:15 | Tài | TAI-06 | CI tự deploy `main` lên GCP demo VM |
| #15 | 11:27 | Tài | HUY-02 | Lưu ngày hiệu lực PDF dạng ISO để UI đọc được |
| #16 | 11:46 | Khoa | KHOA-01 | API lưu / trả eval run (`/api/eval/runs`) |
| #17 | 13:04 | Tài | TAI-06 | Qwen trên Vertex AI + bge-m3 trên GCP VM |
| #18 | 13:11 | Tài | TAI-06 | Endpoint `/v1` có key cho model trên GCP VM |
| #19 | 14:10 | Minh | MINH-01 | Reranker, lọc applicability, gộp LLM judge, cache LLM |
| #20 | 14:31 | Huy | HUY-01 | Nối frontend với backend thật (live API) |
| #21 | 14:31 | Tài | TAI-01 | Engine A `POST /draft`: patch tối thiểu đã kiểm tra + verifier |
| #22 | 14:35 | Huy | HUY-02 | Sửa import logging trong RIA LLM |
| #23 | 15:00 | Tài | TAI-02 | Biến finding RIA thành gói review HITL (`/api/analyses/{job_id}/review`) |
| #24 | 15:24 | Tài | TAI-02 | UI review đọc gói review |
| #25 | 16:02 | Tài | TAI-02 | Card review hiện đề xuất AI + accept / reject |
| #26 | 16:05 | Tài | TAI-06 | Gemini 4 Argon (chat) + Vertex semantic ranker trên GCP VM |
| #27 | 16:19 | Tài | TAI-06 | Deploy GCP tạo lại litellm + caddy để nhận config mới |

### Tổng kết theo người

| Người | PR đã merge | Task hoàn thành |
|---|---|---|
| Tài | 18 | TAI-01, TAI-02, TAI-03, TAI-06 |
| Huy | 4 | HUY-01, HUY-02 |
| Khoa | 3 | — (KHOA-01 đang làm) |
| Minh | 2 | MINH-02 (MINH-01 đang làm) |

## 3. Lệch giữa PLAN.md và code (trước PR #28)

1. HUY-01: UI đã đủ nhưng checkbox còn `[ ]`.
2. KHOA-01: 3 PR đã merge nhưng checkbox metric còn `[ ]`.
3. MINH-02: format đã dùng thực tế nhưng "Quyết định đã thống nhất" ghi `_chưa chốt_`.
4. MINH-01 "Đóng gói tool retrieve cho agent": theo Engine A agent không tự retrieve → có thể lỗi thời (chưa sửa, chờ Minh).

## 4. Quyết định trong buổi này

- Tài cập nhật checkbox HUY-01 / KHOA-01 / MINH-02 thay owner (owner kiểm tra lại trong PR #28).
- Tạm thời demo trên GCP VM; TAI-07 (GreenNode) hoãn đến khi có tài khoản.

## 5. Thay đổi trong PR #28 (`PLAN.md`)

- HUY-01 → `[x]` toàn bộ mục con.
- KHOA-01 giữ `[~]`; tick 3 nhóm metric đã code; ghi chú data contract + `/api/eval/runs`; metric hệ thống giữ `[ ]` (có hàm, chưa có nguồn đo).
- MINH-02 → `[x]`; ghi format mock vào "Quyết định đã thống nhất".
- TAI-07: ghi chú demo trên GCP VM.

## 6. Ưu tiên tiếp theo (để kịp demo)

1. Khoa: chạy eval thật trên đường RIA; làm KHOA-02 few-shot → số liệu trước/sau feedback.
2. Huy: dashboard Evaluation hiển thị run thật từ `/api/eval/runs`.
3. Minh: chốt model embedding + schema chunk, ghi vào PLAN.md.
4. Tài: TAI-04 slide, TAI-05 kịch bản demo.

## Câu hỏi chưa giải quyết

- MINH-01 mục "Đóng gói tool retrieve cho agent" còn cần không (Engine A)?
- Chốt chính thức `bge-m3` (1024 dims) làm model embedding? Code + GCP VM đang dùng nhưng PLAN.md vẫn `_chưa chốt_`.
