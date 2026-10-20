/**
 * API contracts used by the UI.
 *
 * PROPOSED shapes for the prototype. The final shapes are owned by:
 * - Impact, Decision, Reviewer: TAI-02 (HITL API)
 * - InternalDocument, page/bbox location: MINH-01 (chunk schema) + HUY-02 (ingestion)
 * - EvalRun: KHOA-01 (experiment output)
 * When those are agreed, change this file and the mock fixtures; screens follow via TS errors.
 */

export type VbplStatus = 'processing' | 'awaiting_review' | 'done' | 'failed' | 'not_found'

export interface Vbpl {
  id: string
  number: string
  title: string
  issuer: string
  issuedDate: string
  effectiveDate: string
  receivedAt: string
  summary: string
  status: VbplStatus
  impactCount: number
  pendingCount: number
  /** Why the analysis failed; set only when status is 'failed'. */
  error?: string
  /** RIA document version (REG-…@v1) behind this row; the id used to delete it. */
  versionId?: string
}

export interface InternalDocument {
  id: string
  code: string
  title: string
  department: string
  version: string
  effectiveDate: string
  pdfUrl: string
  pageCount: number
}

export type ImpactType = 'conflict' | 'outdated_reference' | 'new_obligation'
export type Severity = 'high' | 'medium' | 'low'
export type ImpactStatus = 'pending' | 'accepted' | 'rejected'

/** [x0, y0, x1, y1] in PDF points, origin top-left (PyMuPDF convention). */
export type BBox = [number, number, number, number]

export interface Impact {
  id: string
  vbplId: string
  documentId: string
  /** Human-readable location in the internal document, e.g. "Điều 3, khoản 1". */
  location: string
  /** Clause of the new VBPL that causes the impact. */
  changeClause: string
  citation: string
  affectedText: string
  /** Null until PDF ingestion (HUY-02) gives chunks a page; no highlight is drawn then. */
  page: number | null
  bboxes: BBox[]
  type: ImpactType
  severity: Severity
  reasoning: string
  suggestedText: string
  /** RIA review packages: how the agent's draft went. No suggestion when 'failed' or 'skipped'. */
  draftStatus?: 'review_required' | 'failed' | 'skipped'
  draftError?: string
  status: ImpactStatus
  /** Text the reviewer approved: suggestedText on accept, the edited text on edit. */
  finalText?: string
  /** Latest decision, if any. */
  decision?: Decision
}

export type DecisionAction = 'accept' | 'edit' | 'reject'

export interface Reviewer {
  id: string
  name: string
  role: string
}

export interface Decision {
  id: string
  impactId: string
  vbplId: string
  documentId: string
  action: DecisionAction
  editedText?: string
  reasonTags: string[]
  reviewer: Reviewer
  at: string
}

/** A decision joined with what the reviewer saw, as listed in the audit trail. */
export interface AuditEntry extends Decision {
  vbplNumber: string
  documentCode: string
  location: string
  originalText: string
  suggestedText: string
}

export interface DecisionInput {
  impactId: string
  action: DecisionAction
  editedText?: string
  reasonTags: string[]
  reviewerId: string
}

export interface EvalMetrics {
  extraction: { precision: number; recall: number }
  retrieval: { recallAtK: number; k: number; mrr: number }
  impact: { precision: number; recall: number; f1: number }
  /**
   * `null` means not measured, which is not the same as zero. `judgeScore` needs an LLM judge,
   * `hitlAcceptRate` needs someone to have reviewed that run, and cost needs token accounting the
   * pipeline does not record yet. Showing 0 would read as "measured and bad".
   */
  amendment: { judgeScore: number | null; hitlAcceptRate: number | null }
  system: { latencySeconds: number; costUsdPerDocument: number | null }
}

export interface EvalRun {
  id: string
  label: string
  createdAt: string
  datasetSize: number
  note: string
  metrics: EvalMetrics
}

/** DPO long-loop readiness: how much reviewer feedback has been gathered (KHOA-02). */
export interface FeedbackStatus {
  decisionsRead: number
  /** Decisions that contrast two texts (edit / reject with an AI draft): one DPO pair each. */
  pairsUsable: number
  byAction: { accept: number; edit: number; reject: number }
  /** Drafts that failed or were skipped: no AI text, so never a preference pair. */
  draftFailures: number
  /** Threshold a build checks against; `ready` once `pairsUsable` reaches it. */
  minPairs: number
  ready: boolean
  draftExamples: { positiveAvailable: number; negativeAvailable: number }
  judgeExamples: { positiveAvailable: number; negativeAvailable: number }
}

export interface HealthReport {
  status: 'ok' | 'degraded'
  checks: Record<string, string>
}

export interface UploadVbplInput {
  file: File
  code?: string
  title?: string
  issuer?: string
  effectiveDate?: string
}

export interface IngestDocumentResult {
  status: string
  document: {
    id: string
    code?: string
    title?: string
    doc_type: string
    issuer?: string
    effective_date?: string
    page_count: number
    pdf_url?: string
    created_at?: string
  }
  chunk_count: number
  chunks: Array<{
    id: string
    article_path?: string
    page: number
    bbox: BBox[]
    text: string
  }>
}

export interface DocumentClause {
  clause_id: string
  version_id: string
  parent_id?: string | null
  numbering: string
  level?: string | null
  heading?: string | null
  text: string
  page?: number | null
  char_start: number
  char_end: number
  bbox?: BBox[] | null
  ordinal: number
}

export interface DocumentObligation {
  obligation_id: string
  source_clause_id: string
  subject: string
  action: string
  object: string
  modality: string
  condition?: string | null
  deadline?: string | null
  exception?: string | null
  text: string
}

export interface DocumentDetailResponse {
  document: {
    document_id: string
    title: string
    doc_type: string
    owner?: string
    doc_number?: string
    issuer?: string
    legal_form?: string
    version_id?: string
    version_label?: string
    status?: string
    valid_from?: string
    valid_to?: string
    page_count?: number
    source_uri?: string
    created_at?: string
  }
  clauses: DocumentClause[]
  obligations: DocumentObligation[]
  total_clauses: number
  total_obligations: number
}

export interface IngestInternalResult {
  status: string
  message?: string
  filename?: string
  document_id?: string
  version_id?: string
  title?: string
  clauses?: number
  obligations?: number
  views_indexed?: number
}

export interface IngestInternalStatus {
  is_processing: boolean
  filename: string | null
  status: 'idle' | 'processing' | 'completed' | 'failed'
  message: string | null
  error: string | null
  progress?: string | null
  started_at?: string | null
  completed_at?: string | null
  result?: IngestInternalResult | null
}


