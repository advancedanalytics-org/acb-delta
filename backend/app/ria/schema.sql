-- RIA 3.0 schema. Follows db/data-model.md (design section 04) plus the job, reference and
-- run-lineage columns the ingest/analyze APIs need. Idempotent: applied on API startup.
CREATE EXTENSION IF NOT EXISTS vector;

-- Logical identity. One id, many versions.
CREATE TABLE IF NOT EXISTS document (
  document_id  text PRIMARY KEY,
  title        text NOT NULL,
  doc_type     text NOT NULL,          -- regulation | internal
  owner        text NOT NULL,
  doc_number   text,                   -- 91/2025/QH15
  issuer       text,                   -- QUỐC HỘI, CHÍNH PHỦ, NGÂN HÀNG NHÀ NƯỚC
  legal_form   text,                   -- LUẬT, NGHỊ ĐỊNH, THÔNG TƯ, QUYẾT ĐỊNH
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_version (
  version_id         text PRIMARY KEY,     -- REG-001@v1
  document_id        text NOT NULL REFERENCES document(document_id),
  version_label      text NOT NULL,        -- v1, v4
  status             text NOT NULL,        -- effective | superseded | pending
  valid_from         date,
  valid_to           date,
  checksum           text NOT NULL,
  -- Workflow state (design section 15): DRAFT → PARSED → RETRIEVAL_COMPLETED → AI_PROPOSED.
  processing_status  text NOT NULL DEFAULT 'DRAFT',
  issued_date        date,
  source_uri         text,                 -- immutable original in object storage
  file_name          text,
  mime_type          text,
  page_count         int,
  content            text,                 -- canonical text; clause offsets index into it
  metadata           jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, version_label)
);
CREATE UNIQUE INDEX IF NOT EXISTS document_version_checksum ON document_version (checksum);

CREATE TABLE IF NOT EXISTS clause (
  clause_id    text PRIMARY KEY,       -- REG-001@v1#A.5.2
  version_id   text NOT NULL REFERENCES document_version(version_id),
  parent_id    text REFERENCES clause(clause_id),
  numbering    text NOT NULL,
  level        text,                   -- chapter | section | article | clause | point | appendix | chunk
  heading      text,
  text         text NOT NULL,
  page         int,
  char_start   int NOT NULL,
  char_end     int NOT NULL,
  bbox         jsonb,                  -- [[page, x0, y0, x1, y1], ...] per source line
  ordinal      int NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS clause_version ON clause (version_id);

-- Cross references found while parsing. Missing targets are kept as missing_source.
CREATE TABLE IF NOT EXISTS reference_edge (
  edge_id             text PRIMARY KEY,
  source_clause_id    text NOT NULL REFERENCES clause(clause_id),
  ref_text            text NOT NULL,
  target_doc_number   text,
  target_clause_id    text REFERENCES clause(clause_id),
  status              text NOT NULL    -- resolved | missing_source
);

CREATE TABLE IF NOT EXISTS obligation (
  obligation_id      text PRIMARY KEY,
  source_clause_id   text NOT NULL REFERENCES clause(clause_id),
  subject            text NOT NULL DEFAULT '',
  action             text NOT NULL DEFAULT '',
  object             text NOT NULL DEFAULT '',
  modality           text NOT NULL,     -- must | may | must_not
  condition          text,
  deadline           text,
  exception          text,
  text               text NOT NULL,     -- the atomic proposition, verbatim
  span_start         int NOT NULL,      -- offsets inside the source clause text
  span_end           int NOT NULL,
  extraction_method  text NOT NULL      -- rule | rule+llm:<model> (refined at applicability)
);

CREATE TABLE IF NOT EXISTS obligation_clause (
  obligation_id  text NOT NULL REFERENCES obligation(obligation_id),
  clause_id      text NOT NULL REFERENCES clause(clause_id),
  role           text NOT NULL,        -- source | aligned
  PRIMARY KEY (obligation_id, clause_id)
);

CREATE TABLE IF NOT EXISTS index_view (
  view_id             text PRIMARY KEY,
  clause_id           text NOT NULL REFERENCES clause(clause_id),
  view_type           text NOT NULL,   -- raw | context | keywords
  content             text NOT NULL,
  embedding           vector(1024),
  embedding_version   text NOT NULL,   -- model id, or 'none' for sparse-only rows
  tsv                 tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  UNIQUE (clause_id, view_type, embedding_version)
);
CREATE INDEX IF NOT EXISTS index_view_tsv ON index_view USING gin (tsv);
CREATE INDEX IF NOT EXISTS index_view_embedding_hnsw
  ON index_view USING hnsw (embedding vector_cosine_ops);

-- Async work for parse / analyze. Status: queued | running | succeeded | failed.
CREATE TABLE IF NOT EXISTS job (
  job_id       text PRIMARY KEY,
  job_type     text NOT NULL,          -- parse | analyze
  document_id  text NOT NULL REFERENCES document(document_id),
  version_id   text NOT NULL REFERENCES document_version(version_id),
  status       text NOT NULL,
  stage        text,
  progress     int NOT NULL DEFAULT 0,
  params       jsonb NOT NULL DEFAULT '{}'::jsonb,
  result       jsonb,
  error        text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  started_at   timestamptz,
  finished_at  timestamptz
);
CREATE INDEX IF NOT EXISTS job_version ON job (version_id, job_type);

-- One row per obligation ↔ internal clause pair kept after retrieval. job_id = analysis run.
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id         text PRIMARY KEY,
  job_id              text REFERENCES job(job_id),
  obligation_id       text NOT NULL REFERENCES obligation(obligation_id),
  internal_clause_id  text NOT NULL REFERENCES clause(clause_id),
  span_start          int NOT NULL,
  span_end            int NOT NULL,
  span_text           text NOT NULL,
  retrieval_method    text NOT NULL,
  score               double precision NOT NULL,
  details             jsonb NOT NULL DEFAULT '{}'::jsonb   -- ranks per query view, parent context
);

CREATE TABLE IF NOT EXISTS impact_finding (
  finding_id              text PRIMARY KEY,
  job_id                  text REFERENCES job(job_id),
  regulation_version_id   text REFERENCES document_version(version_id),
  impacted_document_id    text NOT NULL REFERENCES document(document_id),
  internal_clause_id      text REFERENCES clause(clause_id),
  obligation_id           text NOT NULL REFERENCES obligation(obligation_id),
  evidence_id             text REFERENCES evidence(evidence_id),
  category                text NOT NULL,   -- VALUE_CHANGE, CONTRADICTION, ...
  rationale               text NOT NULL,
  status                  text NOT NULL,   -- AI_PROPOSED | NO_ACTION_PROPOSED | ...
  reviewer                text,
  priority                text NOT NULL,
  confidence              double precision,
  source_span             jsonb,
  target_span             jsonb,
  verification            jsonb NOT NULL DEFAULT '{}'::jsonb,
  citations               text[] NOT NULL DEFAULT '{}',
  method                  text NOT NULL,   -- rule | llm+rule
  created_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS impact_finding_job ON impact_finding (job_id);
-- One finding per (obligation, impacted document); all its evidence rows, primary first.
ALTER TABLE impact_finding ADD COLUMN IF NOT EXISTS evidence_ids text[] NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS amendment (
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

-- Obligation applicability to the bank: decided once per obligation and reused by every run.
ALTER TABLE obligation ADD COLUMN IF NOT EXISTS applicability text;          -- yes | no | uncertain
ALTER TABLE obligation ADD COLUMN IF NOT EXISTS applicability_reason text;
ALTER TABLE obligation ADD COLUMN IF NOT EXISTS applicability_method text;   -- rule | llm:<model>
-- Rule-extracted fields kept when the LLM refines them (extraction_method = rule+llm:<model>).
ALTER TABLE obligation ADD COLUMN IF NOT EXISTS rule_fields jsonb;

-- LLM answers keyed by a hash of (kind, model, extra body, prompt, payload). Changing the
-- prompt or the model changes the key, so stale answers are never reused.
CREATE TABLE IF NOT EXISTS llm_cache (
  cache_key       text PRIMARY KEY,
  kind            text NOT NULL,            -- judge_group | applicability | obligation_refine
  model           text NOT NULL,
  prompt_version  text NOT NULL,            -- sha256(system prompt)[:12]
  response        jsonb NOT NULL,
  hits            int NOT NULL DEFAULT 0,
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_hit_at     timestamptz
);

-- Document-level findings from the knowledge graph (an internal document cites a law the
-- regulation replaces) belong to no single obligation.
ALTER TABLE impact_finding ALTER COLUMN obligation_id DROP NOT NULL;

-- Fingerprint of the parser code that produced a version's clauses (internal ingest). A re-upload
-- of an unchanged PDF is parsed again when it differs; NULL (older rows) always re-parses once.
ALTER TABLE document_version ADD COLUMN IF NOT EXISTS parser_version text;
