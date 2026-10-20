import { liveApi } from '@/api/live'
import type {
  AuditEntry,
  Decision,
  DecisionInput,
  DocumentDetailResponse,
  EvalRun,
  ExampleSet,
  FeedbackStatus,
  HealthReport,
  Impact,
  IngestDocumentResult,
  IngestInternalResult,
  IngestInternalStatus,
  InternalDocument,
  Reviewer,
  UploadVbplInput,
  Vbpl,
} from '@/api/types'

/** Everything the screens need from the backend. Live API queries the real database and AI pipelines. */
export interface ApiClient {
  listVbpls(): Promise<Vbpl[]>
  uploadVbpl(input: UploadVbplInput): Promise<IngestDocumentResult>
  /** Delete a VBPL whose processing failed, so its file can be uploaded again. */
  deleteVbpl(vbpl: Vbpl): Promise<void>
  listImpacts(vbplId: string): Promise<Impact[]>
  listDocuments(): Promise<InternalDocument[]>
  /** Newest first. */
  listAuditTrail(): Promise<AuditEntry[]>
  decide(input: DecisionInput): Promise<Decision>
  undoDecision(decisionId: string): Promise<void>
  listReviewers(): Promise<Reviewer[]>
  listEvalRuns(): Promise<EvalRun[]>
  /** Get clauses, hierarchy, and metadata of an internal document. */
  getDocumentClauses(docId: string): Promise<DocumentDetailResponse>
  /** Ingest an internal document PDF using RIA legal parser and indexing. */
  ingestInternalDocument(file: File): Promise<IngestInternalResult>
  /** Check live status of background internal document ingest. */
  getIngestInternalStatus(): Promise<IngestInternalStatus>
  /** Ingest all internal PDFs from data/ directory. */
  ingestInternalDataDir(): Promise<IngestInternalResult[]>
  /** DPO feedback readiness (KHOA-02); null when the backend has no data yet. */
  getFeedbackStatus(): Promise<FeedbackStatus | null>
  /** Few-shot examples built from reviewer decisions (KHOA-02); null when the backend is unreachable. */
  getEvalExamples(task: 'draft' | 'judge'): Promise<ExampleSet | null>
  /** Always the real backend. */
  getHealth(): Promise<HealthReport>
  /** Restore the seeded demo state. */
  resetDemo(): Promise<void>
}

export const apiMode: 'mock' | 'live' = 'live'

export const api: ApiClient = liveApi
