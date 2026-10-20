# Luồng xử lý `POST /api/regulations` và `POST /api/regulations/{id}/analyze`

Hiện thực mục 05–16 của `ACB_RIA_3_0_Full_Technical_Design.html` trong `backend/app/ria/`. Bảng theo `db/data-model.md`, tạo bởi `backend/app/ria/schema.sql` khi API khởi động. Script dùng `IF NOT EXISTS`, nên chạy lại nhiều lần vẫn an toàn.

## Trạng thái

```
upload ──► DRAFT ──parse job──► PARSED ──analyze job──► RETRIEVAL_COMPLETED ──► AI_PROPOSED
             │                                   (Engine 1 xong)          (Engine 2 xong)
             └─ parse lỗi: version giữ DRAFT, job failed, upload lại đúng file = chạy lại parse
```

Version lỗi (Hộp thư hiện `failed`) có thể xóa bằng `DELETE /api/regulations/{version_id}`, xem mục 4.

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
| `use_llm`, `max_llm_calls` | `true`, `150` | dùng LLM judge khi đã cấu hình `LLM_MODEL`; một lần gọi cho mỗi nghĩa vụ |
| `filter_not_applicable` | `true` | bỏ nghĩa vụ không ràng buộc ngân hàng (rule + LLM, lưu theo nghĩa vụ) |
| `refresh_llm_cache` | `false` | hỏi lại LLM thay vì dùng câu trả lời đã cache |
| `use_rerank`, `rerank_candidates`, `rerank_min_score` | `true`, `20`, `0.2` | reranker chấm 20 ứng viên đầu sau RRF; dưới ngưỡng thì loại |
| `rrf_k`, `candidates_per_query` | `60`, `20` | RRF và số candidate mỗi truy vấn |
| `min_shared_bigrams`, `min_idf_score`, `min_term_idf` | `2`, `6.0`, `2.0` | lexical gate, chỉ dùng khi không có reranker |
| `dense_min_score`, `dense_strong_score` | `0.55`, `0.7` | gate dense (khi không có reranker): dưới mức strong phải có thêm ≥ 1 thuật ngữ đặc trưng chung |
| `relative_cutoff` | `0.6` | bỏ đuôi candidate yếu |
| `evidence_per_obligation`, `max_documents`, `alpha` | `5`, `20`, `0.7` | evidence và aggregation |
| `article_candidates` | `3` | số Điều khớp theo vector gộp (DICE) cho mỗi truy vấn dense; `0` = tắt |

Phần đồng bộ (`analysis.start_analysis`):

- Không tìm thấy regulation → 404.
- Version chưa `PARSED` → 409.
- Không tách được nghĩa vụ nào → 422.
- Chưa có văn bản nội bộ hiệu lực trong phạm vi → 409.
- Đã có job analyze `queued`/`running` → trả **200** kèm job đó, không chạy trùng.
- Còn lại: tạo job và trả **202** `{"job_id", "regulation_id", "version_id", "status": "queued"}`.

Job phân tích (`analysis.run_analysis`):

1. **Lọc nghĩa vụ không áp dụng** (`applicability.py`):
   - Rule xử lý các trường hợp rõ: cơ quan nhà nước, chủ thể dữ liệu/công dân → `no`; tổ chức tín dụng, ngân hàng, bên kiểm soát/xử lý dữ liệu, "cơ quan, tổ chức, cá nhân" → `yes`.
   - Phần còn lại gửi LLM theo lô 20 nghĩa vụ.
   - Kết quả lưu vào cột `obligation.applicability`, nên các lần chạy sau dùng lại.
   - `uncertain` vẫn giữ nghĩa vụ lại (ưu tiên không bỏ sót). Câu trả lời không hợp lệ hoặc LLM lỗi cũng giữ lại nhưng không lưu, để lần sau hỏi lại.
   - Điều khoản ủy quyền như "Chính phủ quy định chi tiết…" đã bị loại từ bước parse.
2. **Engine 1, mục 07–09** (`retrieval.py`):
   - Mỗi nghĩa vụ sinh 3–4 query view: nguyên văn, mệnh đề chuẩn hóa, chủ đề (tên Điều), giá trị/điều kiện.
   - Chạy sparse search (Postgres FTS trên bigram âm tiết) và dense search (pgvector, nếu có `EMBEDDING_*`).
   - **Khớp cấp Điều (DICE, Document Inference via Chunk Evidence):** text của một Điều không gồm các khoản con, nên trước đây không có vector nào đại diện cho cả Điều. Lúc index, mỗi Điều có từ 2 khoản/điểm đã index trở lên được thêm view `article` = trung bình các vector `context` của chúng (chuẩn hóa lại để dùng cosine; không gọi thêm embedding). Dense search lấy `article_candidates` Điều gần nhất, rồi đưa các khoản của chúng vào RRF thành list `article:<view>`: xếp theo hạng Điều, trong cùng Điều theo độ tương đồng riêng của từng khoản. Điểm này được tính là bằng chứng dense. Corpus index trước khi có view này được bổ sung ở đầu lần phân tích, từ vector đã lưu. Evidence ghi `article` (điểm của Điều) trong `details`, và `retrieval_method` có `article`.
   - Gộp bằng RRF `Σ 1/(k + rank)`.
   - **Reranker** (mục 05.6, nếu có `RERANK_*`): chấm 20 ứng viên đầu theo cặp (nghĩa vụ, điều khoản kèm ngữ cảnh), song song theo `RERANK_CONCURRENCY`. Điểm rerank thay cho gate và là điểm của ứng viên. Reranker lỗi với một nghĩa vụ thì nghĩa vụ đó quay về gate.
   - **Đồ thị tri thức** (FalkorDB, nếu có `FALKORDB_URL`), xem mục "Đồ thị tri thức" bên dưới:
     - Tài liệu nội bộ có liên kết pháp lý với văn bản đang phân tích được nới ngưỡng (`graph_relax` = 0,6 × ngưỡng thường) và luôn được giữ trong shortlist.
     - Điều khoản dẫn chiếu tới một điều khoản evidence (hoặc tới Điều chứa nó) được thêm làm evidence `graph:refers_to`, tối đa `graph_neighbors` = 3 mỗi nghĩa vụ; Engine 2 phán quyết như mọi evidence khác. Nó vẫn phải qua lexical gate ở mức `graph_relax` × ngưỡng thường (dẫn chiếu chứng minh phụ thuộc, không chứng minh cùng chủ đề), và không bao giờ là điều khoản khung.
   - **Điều khoản khung** (`retrieval.is_framing`): khối quyết định (`QD`, `QD.n`: "Ban hành kèm theo Quyết định này…"), phần căn cứ/kết, và các Điều Phạm vi điều chỉnh / Đối tượng áp dụng / Giải thích từ ngữ. Chúng trùng từ chủ đề với mọi nghĩa vụ nên điểm bị nhân `framing_penalty` = 0,5 trước bước cắt đuôi.
   - Không có reranker thì dùng lexical gate: IDF tính trên toàn corpus đã index, nên từ chủ đề phủ khắp văn bản như "dữ liệu cá nhân" không được tính là bằng chứng.
   - Aggregation cấp tài liệu `S(D,Q) = α·max + (1−α)·mean(TopK)`, kèm coverage và số section trúng.
   - Mở rộng ngữ cảnh: điều khoản cha và điều khoản anh em chứa ngoại lệ.
   - Kết quả ghi vào `evidence`, có rank theo từng query, truy vấn đã chạy và parent context. Version chuyển `RETRIEVAL_COMPLETED`.
3. **Engine 2, mục 10–11, 14** (`compare.py`). Rule xét từng cặp; LLM xét **mỗi nghĩa vụ một lần** cùng mọi điều khoản ứng viên của nó, và chọn điều khoản khớp nhất (`best`, mục 06.1):
   - Rule giá trị: tách số/thời hạn tiếng Việt ("tối đa 12 tháng", "mười lăm ngày làm việc", "năm năm") và so theo cận max/min. Vượt cận → `VALUE_CHANGE`, nằm trong cận → `EQUIVALENT`.
   - Rule mức bắt buộc: nguồn "phải"/"không được" nhưng nội bộ "có thể"/"được phép" cho cùng hành động → `CONTRADICTION`.
   - **Span detection** (`spans.py`): tách từ và gán từ loại bằng model CRF của `underthesea`, gán nhãn span ACTOR / ACTION / OBJECT / MODALITY / NEGATION / VALUE (thời hạn, tiền, %) / FREQUENCY / CONDITION / EXCEPTION, rồi căn chỉnh nghĩa vụ với câu gần nhất của điều khoản nội bộ theo từng từ (difflib). Kết quả:
     - check `span_diff` trong finding (độ tương đồng, span chỉ có ở một bên, các vùng khác nhau kèm loại);
     - rule `SCOPE_CHANGE`: hai câu tương đồng ≥ 0,5 nhưng điều kiện/ngoại lệ chỉ có ở một bên;
     - gợi ý `khac_biet_span` gửi kèm cho LLM judge;
     - thu hẹp trích dẫn rộng của LLM về đúng span khác biệt (ví dụ "24"), để `target_span` của finding đủ hẹp cho patch tối thiểu.
     - Tắt bằng `SPAN_DETECTION_ENABLED=false`. Model không tải được thì tách theo âm tiết.
   - Còn lại → `INDIRECT_IMPACT`.
   - LLM judge (tùy chọn) trả nhãn kèm trích dẫn. Trích dẫn phải có nguyên văn trong nguồn (source grounding). Không khớp thì hỏi lại một lần; vẫn không khớp thì giữ kết quả rule và gắn `BLOCKED`, chi tiết check lưu câu trả lời của LLM.
   - **Căn span (SLeDoC / LegDiff, Rykov et al., ACL SRW và SIGIR 2026):** với mỗi điều khoản, LLM còn trả `alignments`: các cặp đoạn nguyên văn (nghĩa vụ ↔ nội bộ) gán `equivalent` / `contradiction` / `addition`. Đoạn mâu thuẫn được trích ở mức tối thiểu ("12 tháng" ↔ "24 tháng"). Đoạn `addition` chỉ có ở nguồn kèm `anchor`, là cụm trong điều khoản nội bộ mà yêu cầu mới gắn vào. Kết quả nằm trong check `span_alignment`:
     - Mỗi đoạn phải tìm thấy nguyên văn như trích dẫn; đoạn không khớp bị bỏ (`dropped`, status `warn`).
     - **Kiểm tra độ phủ trước khi nhận `EQUIVALENT`:** `EQUIVALENT` chỉ được giữ khi các đoạn `equivalent` phủ ≥ 50% từng phần hành động / đối tượng / thời hạn / điều kiện / ngoại lệ của nghĩa vụ (chủ thể không xét, vì nội bộ hay viết "Đơn vị …"). Có cặp mâu thuẫn → `CONTRADICTION` (hoặc `VALUE_CHANGE` nếu hai bên đều có số liệu); có đoạn chỉ ở nguồn → `ADDITION`; còn phần chưa được phủ (kể cả khi LLM không trả `alignments`) → `INDIRECT_IMPACT`. Status `fail`, confidence ≤ 0,5.
     - `target_span`: với `CONTRADICTION` / `VALUE_CHANGE` / `SCOPE_CHANGE` là đoạn mâu thuẫn tối thiểu; với `ADDITION` là `anchor`, đúng chỗ agent `INSERT` (sau `target_span`, `docs/amendment-review-contract.md`). Khi LLM đồng ý với xung đột rule tìm ra, vẫn giữ span của rule.
   - LLM không được hạ một xung đột mà rule đã phát hiện xuống `EQUIVALENT`/`INDIRECT_IMPACT` (fail closed, chống false-safe). Khi LLM đồng ý với rule thì giữ span chính xác của rule ("24 tháng") để làm patch tối thiểu.
   - Các nghĩa vụ được gọi LLM song song (`LLM_CONCURRENCY`). Ngân sách `max_llm_calls` dành cho các nghĩa vụ có điểm retrieval cao nhất.
   - **Cache** (`llm_cache`): khóa là sha256 của (loại lời gọi, model, `LLM_EXTRA_BODY`, system prompt, payload). Đổi prompt, model hay nội dung điều khoản thì khóa đổi theo. Lần hỏi lại vì trích dẫn sai sẽ bỏ qua cache và ghi đè. `refresh_llm_cache: true` buộc hỏi lại; `LLM_CACHE_ENABLED=false` tắt cache.
   - Gọi LLM và reranker có retry với backoff khi gặp 429/5xx/timeout.
4. **Finding:** một finding cho mỗi cặp (nghĩa vụ, tài liệu nội bộ), theo mô hình mục 04.
   - Cặp đại diện chọn theo thứ tự: xung đột > đã đáp ứng > khác biệt cụ thể nhất; nếu ngang nhau thì ưu tiên điều khoản LLM chọn là khớp nhất, rồi đến điểm retrieval.
   - `evidence_ids` và `citations` liệt kê mọi điều khoản liên quan, điều khoản chính đứng đầu.
   - `verification.checks` gồm: `deterministic_values`, `modality`, `source_grounding`, `temporal_validity`, `scope_exceptions`, `human_approval: pending`.
   - Status `AI_PROPOSED`, hoặc `NO_ACTION_PROPOSED` khi `EQUIVALENT`. Version chuyển `AI_PROPOSED`.
5. **`job.result`:** tham số đã dùng, phương thức retrieval, model, `llm_calls` và `llm_cache_hits`, số nghĩa vụ (kèm phân bố applicability) và coverage, xếp hạng tài liệu, số finding theo loại/ưu tiên, danh sách `uncovered_obligations`. Danh sách này nghĩa là "chưa tìm thấy bằng chứng", không phải kết luận vi phạm.

Ví dụ finding với thông tư giả định trong `backend/tests/ria_fixtures.py`, tương ứng RIA-001 trong mục 16:

```json
{"category": "VALUE_CHANGE", "priority": "high", "internal_clause_id": "DOC-102@v4#5.2",
 "source_span": {"text": "tối đa\n12 tháng", "start": 75, "end": 90},
 "target_span": {"text": "24 tháng", "start": 50, "end": 58},
 "verification": {"status": "NEEDS_HUMAN_REVIEW", "checks": ["…"]},
 "citations": ["REG-99-2026-TT-NHNN@v1#2.1", "DOC-102@v4#5.2", "…"]}
```

Không có bước nào sửa tài liệu nội bộ. Bản sửa do agent soạn từ finding (`docs/amendment-review-contract.md`).

Finding cấp văn bản từ đồ thị (`method = "graph"`, `obligation_id = null`): tài liệu nội bộ dẫn chiếu chính văn bản đang phân tích, hoặc văn bản bị nó thay thế (ưu tiên cao), hoặc cùng căn cứ pháp lý với một điều khoản của nó (ưu tiên thấp). `job.result.graph` liệt kê các liên kết, số điều khoản phụ thuộc đã thêm và số finding đồ thị.

## 3. Đọc finding (đầu ra M03)

| API | Phương thức | Mục đích |
|---|---|---|
| `/api/findings` | GET | Danh sách finding, nghiêm trọng trước; lọc theo `job_id`, `regulation_id`, `regulation_version_id`, `impacted_document_id`, `category`, `status`, `priority`, `method`; phân trang `limit`/`offset` |
| `/api/findings/{id}` | GET | Một finding |
| `/api/findings/{id}/evidence` | GET | Evidence pack: nghĩa vụ nguồn, điều khoản nội bộ, mọi evidence kèm trace truy hồi (rank, truy vấn, ngữ cảnh cha) |

## 4. `DELETE /api/regulations/{version_id}`: xóa văn bản bị lỗi

`{version_id}` là id version đầy đủ (`REG-…@v1`). Chỉ xóa được version mà Hộp thư (`GET /api/regulations`) đang hiện `failed`: parse lỗi (`Đọc văn bản thất bại`), phân tích lỗi, hoặc soạn gói review lỗi. Mã trả về:

- **200** `{regulation_id, version_id, document_removed, warnings}`.
- **409** khi version chưa ở trạng thái lỗi, còn job `queued`/`running`, hoặc đã có quyết định duyệt (audit trail không bị xóa).
- **404** khi không tìm thấy version.

Code ở `backend/app/ria/removal.py`. Một transaction xóa gói review HITL (cùng `impacts`), `amendment`, `impact_finding`, `evidence`, nghĩa vụ, `index_view`, dẫn chiếu, `clause`, `job` và `document_version`. Khi document không còn version nào, transaction xóa luôn `document`. Dẫn chiếu từ văn bản khác tới điều khoản bị xóa vẫn được giữ, nhưng `target_clause_id` đặt về `null`. Sau khi commit, API xóa thêm file gốc trong storage và các node trong đồ thị tri thức. Hai bước này không chặn việc xóa: nếu lỗi, chúng được ghi vào `warnings`. Xóa xong thì checksum được giải phóng, nên upload lại đúng file sẽ tạo version mới thay vì trả `duplicate`.

Soạn patch và duyệt (M04/M05) không thuộc RIA: agent `POST /draft` (TAI-01) và gói review HITL (TAI-02), theo `docs/amendment-review-contract.md`.

## Đồ thị tri thức (FalkorDB)

Postgres vẫn là nguồn dữ liệu gốc; FalkorDB (`graph.py`) là chỉ mục dẫn xuất để duyệt quan hệ, được đồng bộ sau khi parse văn bản pháp quy, sau seed tài liệu nội bộ, và đầu mỗi lần phân tích cho phiên bản chưa đồng bộ.

```
(:Doc)<-[:OF]-(:Version)<-[:IN]-(:Clause)-[:PART_OF]->(:Clause)
(:Clause)-[:REFERS_TO]->(:Clause)          "khoản 6 Điều 5 Quy định này", "tại Điều 5"
(:Clause|:Doc)-[:CITES]->(:LegalRef)       số hiệu "no:14/2022/QH15" hoặc tên "title:luật phòng chống rửa tiền"
(:Doc)-[:IDENTIFIED_BY|SUPERSEDES]->(:LegalRef)
(:Obligation)-[:FROM]->(:Clause)
```

Phần "Căn cứ …" của quyết định nội bộ thường không thuộc điều khoản nào, nên trích dẫn cũng được đọc từ phần văn bản nằm ngoài các điều khoản. Đồ thị lỗi không làm hỏng parse hay phân tích: kết quả ghi cảnh báo và chạy tiếp như không có đồ thị.

## Cấu hình model

Ví dụ với OpenRouter, đặt trong `.env`. `OPENAI_API_KEY` và `EMBEDDING_API_KEY` là key, không phải URL.

```sh
OPENAI_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=qwen/qwen3-32b                              # ứng viên Qwen3-32B, mục 17
LLM_EXTRA_BODY='{"reasoning":{"enabled":false}}'      # tắt thinking: ~5 lần nhanh hơn
LLM_CONCURRENCY=6
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_MODEL=baai/bge-m3                           # 1024 chiều, đa ngôn ngữ
RERANK_BASE_URL=https://openrouter.ai/api/v1
RERANK_MODEL=qwen/qwen3-reranker-8b                   # họ Qwen3-Reranker, mục 05.6
RERANK_API_KEY=<cùng key OpenRouter>
```

Reranker mặc định là TypeSafe Jev (`RERANK_BACKEND=jev`), gọi qua OpenRouter Decisions API:

```sh
JEV_BASE_URL=https://openrouter.ai/api/alpha        # POST {base}/decisions
JEV_MODEL=typesafe/jev-1.14
JEV_API_KEY=<cùng key OpenRouter>
RERANK_BACKEND=jev
FALKORDB_URL=redis://falkordb:6379                  # compose tự đặt cho api
```

Jev không có endpoint `/rerank` hay `/chat/completions`; mỗi lần gọi chấm 20 ứng viên bằng 20 câu hỏi `choice` (cùng hoạt động / chỉ cùng lĩnh vực / không liên quan), điểm là P(cùng hoạt động); ~1–2 giây, ~$0,00004 mỗi lần. Hiệu chỉnh trên 39 cặp đã gán nhãn (thông tư giả định ↔ DOC-102 đúng; Luật 91/Nghị định 13 ↔ điều khoản KYC sai):
- Câu hỏi đúng/sai ("có liên quan không") quá dễ dãi: cặp sai lên tới 0,95, cao hơn cặp đúng thấp nhất (0,94).
- Câu hỏi 3 lựa chọn, gửi điều khoản không kèm tên tài liệu: cặp đúng ≥ 0,75, cặp sai ≤ 0,74.
- Ngưỡng mặc định 0,5 ưu tiên không bỏ sót: các cặp 0,5–0,74 phần lớn là tác động gián tiếp thật (ví dụ "thu thập phải được sự đồng ý" ↔ Điều 4.1).

Với cross-encoder (`RERANK_BACKEND=rerank`), ngưỡng `rerank_min_score = 0.2` được chọn sau khi đo trên dữ liệu thật:
- Cặp đúng cùng lĩnh vực (thông tư KYC giả định ↔ DOC-102): mọi ứng viên ≥ 0,38.
- Luật 91 và Nghị định 13 ↔ DOC-102 (khác lĩnh vực): 90% nghĩa vụ có điểm tốt nhất < 0,17–0,27.
- Các tác động gián tiếp thật của Luật 91, như "thu thập phải được sự đồng ý trước khi thu thập" ↔ Điều 4.1, nằm quanh 0,22. Ngưỡng 0,3 sẽ loại các cặp này.

Cần đo lại trên gold set (mục 19) trước khi chốt.

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
