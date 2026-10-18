# Luồng xử lý `POST /api/regulations` và `POST /api/regulations/{id}/analyze`

Hiện thực mục 05–16 của `ACB_RIA_3_0_Full_Technical_Design.html` trong `backend/app/ria/`. Bảng theo `db/data-model.md`, tạo bởi `backend/app/ria/schema.sql` khi API khởi động. Script dùng `IF NOT EXISTS`, nên chạy lại nhiều lần vẫn an toàn.

## Trạng thái

```
upload ──► DRAFT ──parse job──► PARSED ──analyze job──► RETRIEVAL_COMPLETED ──► AI_PROPOSED
             │                                   (Engine 1 xong)          (Engine 2 xong)
             └─ parse lỗi: version giữ DRAFT, job failed, upload lại đúng file = chạy lại parse
```

`document_version.status` là hiệu lực pháp lý: `effective`, `pending` (chưa tới `valid_from`), `superseded` hoặc `unknown`. `processing_status` là bước workflow. Job lưu ở bảng `job` và chạy trên thread pool trong process API, vì Phase 1 không có queue. Theo dõi job qua `GET /api/jobs/{job_id}`: `status`, `stage`, `progress`, `result`, `error`.

## 1. `POST /api/regulations`: tạo văn bản pháp quy và job parse

`multipart/form-data`: `file` (PDF, bắt buộc). Các trường tùy chọn ghi đè giá trị đọc từ PDF: `title`, `doc_number`, `owner`, `valid_from`.

Phần đồng bộ, chạy trong request (`ingest.create_regulation`):

1. Kiểm tra định dạng: file rỗng → 422, lớn hơn `MAX_UPLOAD_MB` → 413, không có header `%PDF-` → 415, PDF hỏng hoặc có mật khẩu → 422.
2. Tính `sha256`. Đọc số hiệu ở trang 1, ví dụ `91/2025/QH15`, rồi suy ra `document_id = REG-91-2025-QH15`.
3. Kiểm tra trùng theo checksum. File đã có → trả **200** `duplicate: true` cùng trạng thái hiện tại. Nếu lần parse trước lỗi, API tạo job parse mới.
4. Cùng số hiệu nhưng checksum khác → tạo version mới (`@v2`…), không ghi đè version cũ.
5. Lưu bản gốc bất biến vào S3/MinIO, hoặc thư mục local khi dev, tại `regulations/{document_id}/{vN}/{sha}.pdf`.
6. Tạo `document`, `document_version` (`DRAFT`) và `job` (`parse`), rồi trả **202**:

```json
{"regulation_id": "REG-91-2025-QH15", "version_id": "REG-91-2025-QH15@v1", "version_label": "v1",
 "job_id": "JOB-…", "status": "DRAFT", "duplicate": false,
 "checks": [{"check": "format", "status": "pass"}, {"check": "checksum", "status": "pass"},
            {"check": "malware_scan", "status": "skipped", "detail": "no scanner configured"}]}
```

Job parse (`ingest.run_parse`) chạy trong một transaction, lỗi ở bước nào thì rollback toàn bộ:

| Bước | Module | Kết quả |
|---|---|---|
| PDF → dòng có `page` + `bbox`, bỏ header/footer lặp và rác in trình duyệt | `legal_parser.extract_lines` | canonical text |
| Quá ít chữ (PDF scan, chưa có OCR) | `legal_parser.parse_pdf` | **job failed** (fail closed) |
| Chương → Mục → Điều → Khoản → Điểm, phụ lục chia chunk L3, phần ký/nơi nhận | `legal_parser.parse_structure` | `clause` với `char_start/char_end`, đảm bảo `content[start:end] == text` |
| Metadata: số hiệu, cơ quan ban hành, loại văn bản, ngày ban hành, ngày hiệu lực, văn bản bị thay thế | `legal_parser.extract_metadata` | `document`, `document_version` |
| Dẫn chiếu tới văn bản khác hoặc tới điều khoản nội tại | `legal_parser.extract_references` | `reference_edge` (`resolved` / `missing_source`) |
| Tách nghĩa vụ nguyên tử: chủ thể, hành động, đối tượng, mức bắt buộc, điều kiện, thời hạn, ngoại lệ; kế thừa lead-in "… có trách nhiệm sau đây:" | `obligations.extract_obligations` | `obligation` + `obligation_clause(role=source)` |
| Index đa view: `raw` / `context` / `keywords` (FTS `simple`) | `indexing.build_index_views` | `index_view` |
| Giải quyết phiên bản: version cũ và văn bản bị thay thế chuyển `superseded` | `ingest._supersede` | |

## 2. `POST /api/regulations/{id}/analyze`: khởi chạy phân tích tác động

`{id}` là `document_id` (lấy version mới nhất) hoặc `version_id` (`REG-…@v2`). Body JSON có thể bỏ trống. Mọi tham số đều có mặc định và là hyperparameter để benchmark (mục 07, 20), không phải hằng số đã tinh chỉnh.

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| `internal_document_ids` | tất cả văn bản nội bộ `effective` | phạm vi corpus (ACL) |
| `modalities` | `must`, `must_not`, `may` | lọc nghĩa vụ |
| `use_llm`, `max_llm_pairs` | `true`, `200` | dùng LLM judge khi đã cấu hình `LLM_MODEL` |
| `rrf_k`, `candidates_per_query` | `60`, `20` | RRF và số candidate mỗi truy vấn |
| `min_shared_bigrams`, `min_idf_score`, `min_term_idf` | `2`, `6.0`, `2.0` | lexical gate |
| `dense_min_score`, `dense_strong_score` | `0.55`, `0.7` | gate dense: dưới mức strong phải có thêm ≥ 1 thuật ngữ đặc trưng chung |
| `relative_cutoff` | `0.6` | bỏ đuôi candidate yếu |
| `evidence_per_obligation`, `max_documents`, `alpha` | `3`, `20`, `0.7` | evidence và aggregation |

Phần đồng bộ (`analysis.start_analysis`):

- Không tìm thấy regulation → 404.
- Version chưa `PARSED` → 409.
- Không tách được nghĩa vụ nào → 422.
- Chưa có văn bản nội bộ hiệu lực trong phạm vi → 409.
- Đã có job analyze `queued`/`running` → trả **200** kèm job đó, không chạy trùng.
- Còn lại: tạo job và trả **202** `{"job_id", "regulation_id", "version_id", "status": "queued"}`.

Job phân tích (`analysis.run_analysis`):

1. **Lọc nghĩa vụ.** Bỏ nghĩa vụ của cơ quan nhà nước (Bộ, Chính phủ…). Các điều khoản ủy quyền như "Chính phủ quy định chi tiết…" đã bị loại từ bước parse.
2. **Engine 1, mục 07–09** (`retrieval.py`):
   - Mỗi nghĩa vụ sinh 3–4 query view: nguyên văn, mệnh đề chuẩn hóa, chủ đề (tên Điều), giá trị/điều kiện.
   - Chạy sparse search (Postgres FTS trên bigram âm tiết) và dense search (pgvector, nếu có `EMBEDDING_*`).
   - Gộp bằng RRF `Σ 1/(k + rank)`.
   - Lexical gate dùng IDF tính trên toàn corpus đã index. Từ chủ đề phủ khắp văn bản như "dữ liệu cá nhân" không được tính là bằng chứng.
   - Aggregation cấp tài liệu `S(D,Q) = α·max + (1−α)·mean(TopK)`, kèm coverage và số section trúng.
   - Mở rộng ngữ cảnh: điều khoản cha và điều khoản anh em chứa ngoại lệ.
   - Kết quả ghi vào `evidence`, có rank theo từng query, truy vấn đã chạy và parent context. Version chuyển `RETRIEVAL_COMPLETED`.
3. **Engine 2, mục 10–11, 14** (`compare.py`), xét từng cặp nghĩa vụ ↔ điều khoản:
   - Rule giá trị: tách số/thời hạn tiếng Việt ("tối đa 12 tháng", "mười lăm ngày làm việc", "năm năm") và so theo cận max/min. Vượt cận → `VALUE_CHANGE`, nằm trong cận → `EQUIVALENT`.
   - Rule mức bắt buộc: nguồn "phải"/"không được" nhưng nội bộ "có thể"/"được phép" cho cùng hành động → `CONTRADICTION`.
   - Còn lại → `INDIRECT_IMPACT`.
   - LLM judge (tùy chọn) trả nhãn kèm trích dẫn. Trích dẫn phải có nguyên văn trong nguồn (source grounding). Không khớp thì hỏi lại một lần; vẫn không khớp thì giữ kết quả rule và gắn `BLOCKED`, chi tiết check lưu câu trả lời của LLM.
   - LLM không được hạ một xung đột mà rule đã phát hiện xuống `EQUIVALENT`/`INDIRECT_IMPACT` (fail closed, chống false-safe). Khi LLM đồng ý với rule thì giữ span chính xác của rule ("24 tháng") để làm patch tối thiểu.
   - Các cặp được gọi LLM song song (`LLM_CONCURRENCY`). Ngân sách `max_llm_pairs` dành cho các cặp có điểm retrieval cao nhất.
4. **Finding:** một finding cho mỗi cặp (nghĩa vụ, tài liệu nội bộ), theo mô hình mục 04.
   - Cặp đại diện chọn theo thứ tự: xung đột > đã đáp ứng > khác biệt cụ thể nhất.
   - `evidence_ids` và `citations` liệt kê mọi điều khoản liên quan, điều khoản chính đứng đầu.
   - `verification.checks` gồm: `deterministic_values`, `modality`, `source_grounding`, `temporal_validity`, `scope_exceptions`, `human_approval: pending`.
   - Status `AI_PROPOSED`, hoặc `NO_ACTION_PROPOSED` khi `EQUIVALENT`. Version chuyển `AI_PROPOSED`.
5. **`job.result`:** tham số đã dùng, phương thức retrieval, model, số nghĩa vụ và coverage, xếp hạng tài liệu, số finding theo loại/ưu tiên, danh sách `uncovered_obligations`. Danh sách này nghĩa là "chưa tìm thấy bằng chứng", không phải kết luận vi phạm.

Ví dụ finding với thông tư giả định trong `backend/tests/ria_fixtures.py`, tương ứng RIA-001 trong mục 16:

```json
{"category": "VALUE_CHANGE", "priority": "high", "internal_clause_id": "DOC-102@v4#5.2",
 "source_span": {"text": "tối đa\n12 tháng", "start": 75, "end": 90},
 "target_span": {"text": "24 tháng", "start": 50, "end": 58},
 "verification": {"status": "NEEDS_HUMAN_REVIEW", "checks": ["…"]},
 "citations": ["REG-99-2026-TT-NHNN@v1#2.1", "DOC-102@v4#5.2", "…"]}
```

Không có bước nào sửa tài liệu nội bộ. Bản sửa (`amendment`) do `/api/findings/{id}/amendments` sinh ở bước sau.

## Cấu hình model

Ví dụ với OpenRouter, đặt trong `.env`. `OPENAI_API_KEY` và `EMBEDDING_API_KEY` là key, không phải URL.

```sh
OPENAI_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=qwen/qwen3-32b                              # ứng viên Qwen3-32B, mục 17
LLM_EXTRA_BODY='{"reasoning":{"enabled":false}}'      # tắt thinking: ~5 lần nhanh hơn
LLM_CONCURRENCY=6
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_MODEL=baai/bge-m3                           # 1024 chiều, đa ngôn ngữ
```

Đổi `EMBEDDING_MODEL` thì phải chạy lại seed. Vector cũ vẫn nằm trong bảng dưới `embedding_version` cũ và không bị trộn với vector mới.

## Chạy thử

```sh
# Nạp kho nội bộ: DATABASE_URL trỏ tới Postgres của stack
cd backend && DATABASE_URL=postgresql+psycopg://acb:<mật khẩu>@127.0.0.1:5432/acb_delta \
  uv run python -m app.ria.seed ../db/DOC-102.parsed.json

curl -F file=@../data/91.pdf http://localhost:8000/api/regulations          # → job_id
curl http://localhost:8000/api/jobs/<job_id>                                 # chờ succeeded
curl -X POST http://localhost:8000/api/regulations/REG-91-2025-QH15/analyze  # → job_id
curl http://localhost:8000/api/jobs/<job_id>                                 # result
```

## Giới hạn hiện tại

- **Chỉ có sparse và rule.** Khi chưa cấu hình embedding và LLM, độ chính xác thấp với văn bản khác lĩnh vực. Ví dụ: "phân loại rủi ro" của hệ thống AI vẫn khớp với "phân loại rủi ro" rửa tiền. Phần lớn kết quả khi đó là `INDIRECT_IMPACT` ưu tiên thấp. Dense retrieval, LLM judge và reranker là các bước cắm thêm qua biến môi trường. Nên chạy thí nghiệm A–F (mục 20) trên gold set trước khi chốt ngưỡng.
- **Tách nghĩa vụ dựa trên rule.** Chủ thể/hành động chỉ là xấp xỉ. Phần trích dẫn và span luôn là nguyên văn.
- **Chưa có OCR, chưa quét malware.** PDF scan bị từ chối (fail closed); `malware_scan` được ghi là `skipped`.
- **Embedding phải 1024 chiều**, vì cột là `vector(1024)` như `db/data-model.md`.
