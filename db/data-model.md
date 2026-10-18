# Mô hình dữ liệu RIA 3.0

Đề xuất bảng cho Postgres + pgvector, bám mục 04 của `ACB_RIA_3_0_Full_Technical_Design.html`. `db/init/01-init.sql` chỉ bật extension `vector`. Các bảng dưới đây được API tạo khi khởi động từ `backend/app/ria/schema.sql`. File đó còn có thêm cột phục vụ ingest/analyze (`processing_status`, `content`, `level`, `bbox`, `job_id`…) và các bảng `job`, `reference_edge`; xem `docs/ria-ingest-analyze.md`.

Vector embedding nằm ở cột `index_view.embedding`. Các bảng còn lại giữ văn bản, quan hệ và điểm xếp hạng.

`document_version` tách danh tính logic (`document_id`) khỏi bản hiệu lực (`version_id`). `obligation_clause` hiện thực quan hệ N–N giữa nghĩa vụ và điều khoản. Đổi model embedding thì thêm dòng `index_view` mới, không ghi đè vector cũ.

Ví dụ xuyên suốt là finding `RIA-001`: thông tư giả định yêu cầu đối chiếu tối đa 12 tháng, quy định nội bộ đang ghi 24 tháng. Số liệu là giả định kỹ thuật, không phải trích dẫn văn bản thật.

## Bảng

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Danh tính logic. Một mã, nhiều phiên bản.
CREATE TABLE document (
  document_id  text PRIMARY KEY,
  title        text NOT NULL,
  doc_type     text NOT NULL,          -- regulation | internal
  owner        text NOT NULL
);

-- Trường version, status, hiệu lực, checksum của thực thể Document.
CREATE TABLE document_version (
  version_id     text PRIMARY KEY,     -- REG-001@v1
  document_id    text NOT NULL REFERENCES document(document_id),
  version_label  text NOT NULL,        -- v1, v4
  status         text NOT NULL,        -- effective | superseded
  valid_from     date,
  valid_to       date,
  checksum       text NOT NULL,
  UNIQUE (document_id, version_label)
);

-- Section/Clause. Nguyên văn nằm ở đây, không embed.
CREATE TABLE clause (
  clause_id    text PRIMARY KEY,       -- REG-001@v1#A.5.2
  version_id   text NOT NULL REFERENCES document_version(version_id),
  parent_id    text REFERENCES clause(clause_id),
  numbering    text NOT NULL,
  text         text NOT NULL,
  page         int,
  char_start   int NOT NULL,
  char_end     int NOT NULL
);

-- Obligation. source_clause_id là điều khoản sinh ra nghĩa vụ.
CREATE TABLE obligation (
  obligation_id     text PRIMARY KEY,
  source_clause_id  text NOT NULL REFERENCES clause(clause_id),
  subject           text NOT NULL,
  action            text NOT NULL,
  object            text NOT NULL,
  modality          text NOT NULL,     -- must | may | must_not
  condition         text,
  deadline          text,
  exception         text
);

-- N–N: một nghĩa vụ khớp nhiều điều, một điều đáp ứng nhiều nghĩa vụ.
CREATE TABLE obligation_clause (
  obligation_id  text NOT NULL REFERENCES obligation(obligation_id),
  clause_id      text NOT NULL REFERENCES clause(clause_id),
  role           text NOT NULL,        -- source | aligned
  PRIMARY KEY (obligation_id, clause_id)
);

-- IndexView. Cột embedding là vector.
CREATE TABLE index_view (
  view_id             text PRIMARY KEY,
  clause_id           text NOT NULL REFERENCES clause(clause_id),
  view_type           text NOT NULL,   -- raw | summary | keywords | obligation
  content             text NOT NULL,
  embedding           vector(1024),
  embedding_version   text NOT NULL,   -- model + phiên bản không gian vector
  UNIQUE (clause_id, view_type, embedding_version)
);

CREATE INDEX index_view_embedding_hnsw
  ON index_view USING hnsw (embedding vector_cosine_ops);

-- Một dòng = một cặp nghĩa vụ ↔ điều khoản nội bộ (N–N).
CREATE TABLE evidence (
  evidence_id         text PRIMARY KEY,
  obligation_id       text NOT NULL REFERENCES obligation(obligation_id),
  internal_clause_id  text NOT NULL REFERENCES clause(clause_id),
  span_start          int NOT NULL,
  span_end            int NOT NULL,
  span_text           text NOT NULL,
  retrieval_method    text NOT NULL,
  score               double precision NOT NULL
);

-- ImpactFinding. N–1 tài liệu bị tác động.
CREATE TABLE impact_finding (
  finding_id              text PRIMARY KEY,
  impacted_document_id    text NOT NULL REFERENCES document(document_id),
  obligation_id           text NOT NULL REFERENCES obligation(obligation_id),
  category                text NOT NULL,   -- VALUE_CHANGE, ...
  rationale               text NOT NULL,
  status                  text NOT NULL,
  reviewer                text,
  priority                text NOT NULL
);

-- Amendment. N–1 finding.
CREATE TABLE amendment (
  patch_id      text PRIMARY KEY,
  finding_id    text NOT NULL REFERENCES impact_finding(finding_id),
  clause_id     text NOT NULL REFERENCES clause(clause_id),
  target_start  int NOT NULL,
  target_end    int NOT NULL,
  operation     text NOT NULL,          -- REPLACE | INSERT | DELETE
  before_text   text NOT NULL,
  after_text    text NOT NULL,
  validation    text NOT NULL,
  approval      text NOT NULL
);
```

## Dữ liệu mẫu — finding RIA-001

Offset `54–62` trong câu điều 5.2 là đoạn `24 tháng`. Offset `102–117` trong câu A.5.2 là đoạn `tối đa 12 tháng`.

### document

| document_id | title | doc_type | owner |
|---|---|---|---|
| REG-001 | Thông tư giả định về nhận biết khách hàng | regulation | Ngân hàng Nhà nước |
| DOC-102 | Quy định nội bộ rà soát hồ sơ khách hàng | internal | Khối Tuân thủ |

### document_version

| version_id | document_id | version_label | status | valid_from | valid_to | checksum |
|---|---|---|---|---|---|---|
| REG-001@v1 | REG-001 | v1 | effective | 2026-07-01 | | sha256:aaa111 |
| DOC-102@v4 | DOC-102 | v4 | effective | 2024-01-15 | | sha256:bbb222 |

### clause

| clause_id | version_id | parent_id | numbering | text | page | char_start | char_end |
|---|---|---|---|---|---|---|---|
| REG-001@v1#A.5 | REG-001@v1 | | A.5 | Chương định kỳ cập nhật thông tin khách hàng. | 12 | 900 | 979 |
| REG-001@v1#A.5.2 | REG-001@v1 | REG-001@v1#A.5 | A.5.2 | Ngân hàng phải đối chiếu thông tin khách hàng tối đa 12 tháng một lần. | 12 | 980 | 1100 |
| DOC-102@v4#5 | DOC-102@v4 | | 5 | Rà soát hồ sơ định kỳ. | 8 | 1 | 39 |
| DOC-102@v4#5.2 | DOC-102@v4 | DOC-102@v4#5 | 5.2 | Đơn vị thực hiện rà soát hồ sơ khách hàng định kỳ 24 tháng. | 8 | 40 | 120 |

### obligation

| obligation_id | source_clause_id | subject | action | object | modality | condition | deadline | exception |
|---|---|---|---|---|---|---|---|---|
| OBL-12M | REG-001@v1#A.5.2 | ngân hàng | đối chiếu | thông tin khách hàng | must | khách hàng đang quan hệ | tối đa 12 tháng một lần | |

### obligation_clause

| obligation_id | clause_id | role |
|---|---|---|
| OBL-12M | REG-001@v1#A.5.2 | source |
| OBL-12M | DOC-102@v4#5.2 | aligned |

### index_view

Mỗi dòng một vector. Cùng `embedding_version = bge-m3@2026-10`. Truy vấn dense chỉ lấy các dòng cùng phiên bản này. Giá trị `embedding` viết tắt.

| view_id | clause_id | view_type | content | embedding |
|---|---|---|---|---|
| IV-A52-RAW | REG-001@v1#A.5.2 | raw | Ngân hàng phải đối chiếu thông tin khách hàng tối đa 12 tháng một lần. | `[0.021, -0.114, …]` |
| IV-A52-OBL | REG-001@v1#A.5.2 | obligation | subject=ngân hàng; action=đối chiếu; object=thông tin khách hàng; modality=must; deadline=12 tháng | `[0.188, 0.042, …]` |
| IV-52-RAW | DOC-102@v4#5.2 | raw | Đơn vị thực hiện rà soát hồ sơ khách hàng định kỳ 24 tháng. | `[0.017, -0.098, …]` |
| IV-52-OBL | DOC-102@v4#5.2 | obligation | subject=đơn vị; action=rà soát; object=hồ sơ khách hàng; frequency=24 tháng | `[0.173, 0.051, …]` |

### evidence

`score` là điểm sau hybrid / RRF / rerank, không phải vector.

| evidence_id | obligation_id | internal_clause_id | span_start | span_end | span_text | retrieval_method | score |
|---|---|---|---|---|---|---|---|
| EV-001 | OBL-12M | DOC-102@v4#5.2 | 54 | 62 | 24 tháng | dense+bm25+rrf | 0.86 |

### impact_finding

| finding_id | impacted_document_id | obligation_id | category | rationale | status | reviewer | priority |
|---|---|---|---|---|---|---|---|
| RIA-001 | DOC-102 | OBL-12M | VALUE_CHANGE | Nội bộ 24 tháng, nguồn tối đa 12 tháng, cùng phạm vi hồ sơ khách hàng. | AI_PROPOSED | | high |

### amendment

| patch_id | finding_id | clause_id | target_start | target_end | operation | before_text | after_text | validation | approval |
|---|---|---|---|---|---|---|---|---|---|
| PATCH-001 | RIA-001 | DOC-102@v4#5.2 | 54 | 62 | REPLACE | 24 tháng | tối đa 12 tháng | NEEDS_HUMAN_REVIEW | pending |

## Cách đọc một finding

`PATCH-001` thuộc `RIA-001` trên `DOC-102`, căn cứ `OBL-12M` tại `REG-001@v1#A.5.2`. Bằng chứng `EV-001` trỏ đúng span `24 tháng` của `DOC-102@v4#5.2`. Vector dùng để tìm ra điều 5.2 nằm ở `IV-52-RAW` và `IV-52-OBL`.
