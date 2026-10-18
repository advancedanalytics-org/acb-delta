import { liveApi } from '@/api/live'
import type {
  AuditEntry,
  Decision,
  DecisionInput,
  EvalRun,
  HealthReport,
  Impact,
  IngestDocumentResult,
  InternalDocument,
  Reviewer,
  UploadVbplInput,
  Vbpl,
} from '@/api/types'

/** Everything the screens need from the backend. Live API queries the real database and AI pipelines. */
export interface ApiClient {
  listVbpls(): Promise<Vbpl[]>
  uploadVbpl(input: UploadVbplInput): Promise<IngestDocumentResult>
  listImpacts(vbplId: string): Promise<Impact[]>
  listDocuments(): Promise<InternalDocument[]>
  /** Newest first. */
  listAuditTrail(): Promise<AuditEntry[]>
  decide(input: DecisionInput): Promise<Decision>
  undoDecision(decisionId: string): Promise<void>
  listReviewers(): Promise<Reviewer[]>
  listEvalRuns(): Promise<EvalRun[]>
  /** Always the real backend. */
  getHealth(): Promise<HealthReport>
  /** Restore the seeded demo state. */
  resetDemo(): Promise<void>
}

export const apiMode: 'mock' | 'live' = 'live'

export const api: ApiClient = liveApi
