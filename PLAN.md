# Kế hoạch dự án – Document Evaluation for Legal Transformation Analysis

> AI Hackathon – Bank Summit · Đánh giá tác động của VBPL mới lên văn bản nội bộ

## Quy ước theo dõi

- `[ ]` chưa làm · `[~]` đang làm · `[x]` hoàn thành · `[!]` bị chặn (ghi lý do bên cạnh)
- Mỗi task có **ID** (vd. `TAI-01`). Ghi ID vào commit message / PR title, vd. `feat(HUY-02): chunk theo Điều/Khoản`.
- Cập nhật trạng thái bằng cách sửa checkbox trong file này và commit cùng thay đổi liên quan.
- Task phụ thuộc nhau được ghi ở mục **Phụ thuộc**.

---

## Quyết định kỹ thuật

Triển khai 2 giai đoạn: **Phase 1** chạy trên server riêng của team trong lúc chờ tài khoản GreenNode, **Phase 2** chuyển sang GreenNode. Mọi thành phần Phase 1 phải đổi được sang Phase 2 **chỉ bằng biến môi trường**, không sửa code.

| Hạng mục | Phase 1 – Server team | Phase 2 – GreenNode | Cách giữ tương thích |
|---|---|---|---|
| Database + Vector DB | Container `pgvector/pgvector` (Postgres + pgvector) | **vDB PostgreSQL** + pgvector | Cùng major version Postgres; migrate bằng `pg_dump` / `pg_restore`; `DATABASE_URL` |
| Agent | Container LangGraph, HTTP port **8080** | **AgentBase Agent Runtime** | Viết sẵn theo hợp đồng AgentBase (container, port 8080); lớp wrap `greennode-agentbase` thêm ở Phase 2 |
| LLM | Endpoint OpenAI-compatible (vLLM local hoặc provider khác) | **GreenNode MaaS** | Chỉ gọi qua `OPENAI_BASE_URL` + `LLM_MODEL`; khuyến nghị đặt LiteLLM proxy phía trước |
| Embedding | Cùng model sẽ dùng ở Phase 2, chạy local (vd. BGE-M3 qua TEI) | **GreenNode MaaS** (nếu có model đó) | **Chốt model trước khi index**; đổi model = phải re-embed toàn bộ (có script `reindex`) |
| Lưu PDF | **MinIO** (S3-compatible, image `cgr.dev/chainguard/minio`) | **vStorage** | Client S3 + `S3_ENDPOINT` |
| Monitor / Eval | **Langfuse Cloud** (gói Hobby), không chạy container | Langfuse Cloud (giữ nguyên) | `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`; để trống = tắt tracing |
| Backend API | **FastAPI** | **FastAPI** trên vServer | Không đổi |
| Frontend | **React + TS + Vite**, **shadcn/ui + Tailwind** | Như Phase 1, trên vServer | Gọi `/api` tương đối qua nginx; `VITE_API_MODE=mock\|live` |
| Cache | ~~Redis~~ | ~~Redis~~ | Bỏ; chỉ thêm nếu cần job queue cho ingestion |
| Hạ tầng | 1 file `docker-compose.yml` cho toàn bộ | vServer (FE + FastAPI) · Langfuse Cloud · AgentBase · vDB · MaaS | Không dùng VKS |

Thư viện dùng chung: PDF parser **PyMuPDF** (bắt buộc giữ `page` + `bbox` cho từng chunk) · PDF viewer `react-pdf` + lớp highlight tự vẽ theo bbox (`react-pdf-highlighter-extended` chưa hỗ trợ React 19) · diff `react-diff-viewer-continued` · TanStack Query/Table · Recharts · font Be Vietnam Pro / Inter.

**Rủi ro khi chuyển phase:**
- MaaS không có đúng model embedding đang dùng → phải re-embed và chạy lại eval retrieval.
- Model LLM trên MaaS khác Phase 1 → prompt và kết quả eval có thể lệch; chạy lại `KHOA-01` sau khi chuyển.
- Dữ liệu demo nằm trên server team → không được để dữ liệu thật của ngân hàng trên đó, chỉ dữ liệu mock.

### Phạm vi

- **Làm thật:** ingestion có bbox, graph đánh giá tác động, màn hình review, log HITL, 1 lượt eval trước/sau feedback.
- **Giả lập / bỏ qua:** auth (dùng user switcher), corpus văn bản nội bộ, PDF scan/OCR (mock tạo từ DOCX → PDF có text layer), multi-tenant.
- **"RLHF"** = feedback loop: few-shot động từ quyết định HITL (demo được) + export dữ liệu preference cho DPO (roadmap). Trên slide gọi là *learning from human feedback*.

---

## Tổng quan theo người phụ trách

| Người | Mảng chính |
|---|---|
| Tài | Agent gợi ý chỉnh sửa, HITL, dữ liệu mock + ground truth, slide, thuyết trình, deploy GreenNode |
| Khoa | Evaluation pipeline, feedback loop (RLHF) |
| Huy | UI (4 màn hình), pipeline xử lý PDF NHNN |
| Minh | pgvector: embed + search + metadata, format tài liệu mock |

---

## Tài

- [x] **TAI-01** – Agent gợi ý chỉnh sửa (LangGraph)
  - [x] Node `extract_changes`: tách điều khoản mới / sửa đổi / bãi bỏ từ VBPL (structured output)
  - [x] Fan-out theo từng thay đổi (LangGraph `Send`) → gọi retrieve qua adapter `agent/agent/retriever.py` (tạm khớp từ khoá trên corpus demo; retrieve + rerank thật thuộc `MINH-01`)
  - [x] Node `judge_impact`: có bị ảnh hưởng không, loại (mâu thuẫn / tham chiếu lỗi thời / nghĩa vụ mới), mức độ, lý do, đoạn trích dẫn
  - [x] Node `draft_amendment`: văn bản gốc → văn bản đề xuất
  - [x] Pydantic schema cho output mọi node LLM
  - [x] Engine A (RIA 4.0 M04): endpoint `POST /draft` nhận một finding RIA → patch tối thiểu (`REPLACE` / `INSERT` / `DELETE`) đã kiểm tra với văn bản gốc + verifier độc lập (`docs/amendment-review-contract.md`)
- [x] **TAI-02** – HITL
  - [x] Graph chạy hết (không dùng `interrupt()`); backend lưu impact vào Postgres trạng thái `pending`, quyết định Accept / Edit / Reject / Undo ghi qua API
  - [x] Bảng Postgres lưu quyết định: thay đổi, chunk, output model, hành động, text đã sửa, reason tag, người duyệt (audit trail)
  - [x] API FastAPI cho accept / edit / reject
  - [x] Engine A (RIA 4.0 M05 backend): `POST /api/analyses/{job_id}/review` biến finding RIA thành gói review (`vbpls` + `impacts` có patch before/after); lỗi một bản nháp không làm hỏng cả gói
  - [x] `GET /api/feedback`: nhãn HITL (quyết định còn hiệu lực) cho `KHOA-02`
  - [~] UI review (`frontend/src/api/live`) đọc gói review: inbox đếm theo gói, trang review hiện bản sửa agent đã soạn; bỏ đường tạo impact từ finding id trong `POST /api/decisions`
  - [x] Chạy E2E thật trên model GCP (`qwen3-next-80b`): VBPL → RIA → bản nháp → quyết định → audit + feedback (`plans/reports/tester-261018-1419-ria-review-live.md`)
- [x] **TAI-03** – Tài liệu VBPL & fake dữ liệu văn bản nội bộ
  - [x] Thu thập VBPL mẫu (bản cũ + bản sửa đổi)
  - [x] Sinh văn bản nội bộ giả lập theo format đã chốt (`MINH-02`), xuất DOCX → PDF
  - [x] **Cài cố ý các điểm mâu thuẫn** và ghi lại → ground truth cho eval (`KHOA-01`)
- [ ] **TAI-04** – Slide (gồm slide roadmap DPO / fine-tune)
- [ ] **TAI-05** – Thuyết trình + kịch bản demo
- [x] **TAI-06** – Deploy Phase 1: server team — dừng ở stack local; không dựng server team vì có tài khoản GreenNode, phần còn lại chuyển sang `TAI-07`
  - [x] `docker-compose.yml`: postgres-pgvector, minio, agent (port 8080), fastapi, frontend. Langfuse dùng Cloud (không container); embedding server chờ chốt model (`MINH-01`)
  - [x] `.env.example` liệt kê đủ biến cấu hình (DB, LLM, embedding, S3, Langfuse); không commit `.env`
  - [x] Healthcheck cho từng service; README chạy 1 lệnh (`docker compose up -d --build --wait`)
- [ ] **TAI-07** – Deploy Phase 2: chuyển sang GreenNode (khi có tài khoản)
  - [ ] Tạo Service Account IAM, cấp quyền AgentBase
  - [ ] Endpoint LLM OpenAI-compatible trên MaaS (chuyển từ `TAI-06`)
  - [ ] Script `seed` (nạp VBPL + mock) và `reindex` (re-embed toàn bộ) (chuyển từ `TAI-06`)
  - [ ] Kiểm tra catalog MaaS: có model embedding / LLM đang dùng không
  - [ ] Wrap agent bằng `greennode-agentbase`, build image → Container Registry → Agent Runtime
  - [ ] vDB PostgreSQL + bật pgvector, migrate dữ liệu (`pg_dump` / `pg_restore`)
  - [ ] PDF từ MinIO → vStorage
  - [ ] vServer: frontend + FastAPI (Langfuse giữ trên Cloud)
  - [ ] Chuyển biến môi trường sang MaaS; re-embed nếu đổi model
  - [ ] Chạy lại eval (`KHOA-01`) để xác nhận không bị tụt metric

## Khoa

- [~] **KHOA-01** – Evaluation pipeline
  - [ ] Họp với Minh + Tài thống nhất luồng dữ liệu cho evaluate
  - [ ] Dựng Langfuse dataset từ ground truth của `TAI-03`
  - [ ] Metric từng bước:
    - [ ] Tách thay đổi: Precision / Recall
    - [ ] Retrieval: Recall@k, MRR
    - [ ] Phát hiện tác động: Precision / Recall / F1 (ưu tiên Recall)
    - [ ] Gợi ý chỉnh sửa: LLM-as-judge rubric (đúng, sửa tối thiểu, nhất quán pháp lý) + tỉ lệ accept từ HITL
    - [ ] Hệ thống: độ trễ, chi phí / văn bản (AgentBase Usage)
  - [ ] Cơ chế enrich test set: mỗi reject / edit từ HITL tự động thành dataset item mới
  - [ ] Script chạy experiment và xuất bảng kết quả cho dashboard (`HUY-01`)
- [ ] **KHOA-02** – Feedback loop (RLHF)
  - [ ] Họp với Tài thống nhất luồng dữ liệu
  - [ ] Vòng ngắn: lấy quyết định accept / edit làm few-shot động cho `judge_impact` và `draft_amendment`; reject làm ví dụ âm
  - [ ] Đo metric trước / sau feedback (số liệu cho demo)
  - [ ] Vòng dài: export cặp preference (chosen / rejected) dạng dataset DPO

## Huy

- [ ] **HUY-01** – UI
  - Đã có prototype đủ 5 màn hình chạy trên dữ liệu demo trong `frontend/` (làm cùng skeleton `TAI-06`). Phần còn lại của HUY-01: nối API thật (`VITE_API_MODE=live`, hợp đồng trong `frontend/src/api/types.ts`), PDF thật từ vStorage, hoàn thiện giao diện.
  - [x] Khởi tạo Vite + React + TS + Tailwind + shadcn/ui, design token màu trạng thái, dark mode, font hỗ trợ tiếng Việt
  - [ ] Màn hình **Review workspace** (ưu tiên số 1)
    - [ ] Trái: danh sách impact theo văn bản nội bộ, badge mức độ
    - [ ] Giữa: PDF viewer với highlight theo bbox, màu theo trạng thái (pending / accepted / rejected), click card → scroll tới highlight
    - [ ] Phải: điều khoản VBPL mới vs đoạn bị ảnh hưởng, lý do, diff đề xuất, nút Accept / Edit / Reject + reason chip
    - [ ] Phím tắt `A` / `E` / `R`, `J` / `K`
  - [ ] Màn hình **Inbox**: danh sách VBPL mới, trạng thái xử lý, số impact chờ duyệt
  - [ ] Màn hình **Evaluation dashboard**: metric theo bước, so sánh trước / sau feedback
  - [ ] Màn hình **Audit trail**
  - [ ] Chất lượng production: skeleton, empty state, toast có Undo, optimistic update, user switcher
- [x] **HUY-02** – Luồng xử lý dữ liệu NHNN
  - [x] PDF → text bằng PyMuPDF, giữ `page` + `bbox`
  - [x] Chunk theo cấu trúc pháp lý (Chương / Mục / Điều / Khoản / Điểm)
  - [x] Gắn metadata theo schema đã chốt (`MINH-01`)
  - [x] Embedding qua MaaS → ghi vào pgvector (sử dụng LangChain `langchain-postgres` và `langchain-openai`)
  - [x] Upload PDF gốc lên vStorage / MinIO S3

## Minh

- [~] **MINH-01** – Embed + search + metadata trên pgvector
  - [ ] Chọn và test model embedding tiếng Việt trên MaaS (đã chạy thử `baai/bge-m3` qua OpenRouter, chưa thử MaaS)
  - [ ] Chốt schema chunk: `doc_id, doc_type, issuer, effective_date, article_path, page, bbox, text, embedding`
  - [x] Hybrid search: vector + keyword (Postgres full-text), filter theo metadata — `POST /api/regulations/{id}/analyze`, xem `docs/ria-ingest-analyze.md`
  - [x] Rerank (tùy chọn nếu còn thời gian) — `qwen/qwen3-reranker-8b` qua OpenRouter, ngưỡng 0.2; kèm lọc nghĩa vụ không áp dụng, gộp lời gọi LLM theo nghĩa vụ và cache LLM
  - [ ] Đóng gói thành tool / hàm retrieve cho agent (`TAI-01`)
- [ ] **MINH-02** – Làm việc với Tài để thống nhất document format cho tài liệu mock

---

## Phụ thuộc & điểm đồng bộ

| Task | Phụ thuộc / phối hợp | Ghi chú |
|---|---|---|
| TAI-03 (mock data) | MINH-02 | Chốt format trước khi sinh dữ liệu |
| HUY-02 (metadata) | MINH-01 (schema) | Dùng chung schema chunk |
| TAI-01 (retrieve) | MINH-01, HUY-02 | Cần dữ liệu đã index |
| KHOA-01 | TAI-03, MINH-01 | Ground truth + retrieval để đo |
| KHOA-02 | TAI-02 | Dữ liệu quyết định HITL là đầu vào |
| HUY-01 (highlight) | HUY-02 (bbox), TAI-02 (API) | |
| HUY-01 (eval dashboard) | KHOA-01 | Format kết quả experiment |
| TAI-04, TAI-05 | Luồng chính chạy end-to-end | |
| Mọi task code | TAI-06 | Cần môi trường Phase 1 chạy được để tích hợp |
| TAI-07 | Tài khoản GreenNode, TAI-06 | Chạy lại KHOA-01 sau khi chuyển |

---

## Quyết định đã thống nhất

> Ghi kết quả các buổi thống nhất để cả nhóm tham chiếu.

- **Document format tài liệu mock** (MINH-02): _chưa chốt_
- **Schema chunk / metadata** (MINH-01): _chưa chốt_
- **Model embedding** (MINH-01): _chưa chốt_ — phải chạy được cả trên server team và GreenNode MaaS
- **Endpoint LLM** (TAI-07): GreenNode MaaS. Trước khi có tài khoản, code chỉ đọc `OPENAI_BASE_URL` + `LLM_MODEL` nên dùng tạm bất kỳ endpoint OpenAI-compatible nào; bỏ server team Phase 1
- **HITL** (TAI-02): không dùng `interrupt()`. Graph chạy hết, impact lưu Postgres trạng thái `pending`, mỗi quyết định (accept / edit / reject / undo) là một dòng mới trong bảng quyết định (không sửa đè) → nguồn dữ liệu cho audit trail và `KHOA-02`
- **Engine phân tích tác động** (TAI-01, MINH-01, 2026-10-18): phương án **A** theo blueprint RIA 4.0 (`docs/ACB_RIA_4_0_Final_E2E_6_Modules_6_Owners.html`). RIA (M01–M03, `MINH-01`) tìm finding; agent (M04, `TAI-01`) chỉ soạn patch. M05 backend (quyết định, audit, feedback) = `TAI-02`, M05 UI = `HUY-01`, M06 = `KHOA-01/02`. Luồng `/invoke` cũ giữ nguyên tới khi `KHOA-01` chuyển sang đường RIA. Không ghi bảng `amendment` của RIA; patch nằm ở `impacts.patch`. Hợp đồng: `docs/amendment-review-contract.md`
- **Duyệt HITL** (TAI-02): một bước duyệt (accept / edit / reject / undo) + audit append-only; duyệt nhiều cấp / maker-checker để roadmap. Redline = dữ liệu before/after trên đúng span trong API, không xuất DOCX
- **Luồng dữ liệu Evaluate + enrich test set** (KHOA-01): _chưa chốt_
- **Luồng dữ liệu feedback loop** (KHOA-02, chốt 2026-10-18 bởi Tài): `KHOA-02` đọc `GET /api/feedback` theo định dạng ở `docs/amendment-review-contract.md` §4 — mỗi impact một dòng theo quyết định còn hiệu lực; `edit` → (chosen = bản người sửa, rejected = đề xuất AI), `reject` → (chosen = văn bản gốc, rejected = đề xuất AI), `accept` → chosen = đề xuất AI; bản nháp lỗi/bỏ qua → rejected = null; quyết định đã undo không vào feedback
