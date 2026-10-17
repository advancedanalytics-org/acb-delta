import { liveApi } from '@/api/live'
import { mockApi } from '@/api/mock'
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

/** Everything the screens need from the backend. Mock and live implement the same interface. */
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
  /** Always the real backend, in both modes. */
  getHealth(): Promise<HealthReport>
  /** Restore the seeded demo state. Mock only; live is a no-op. */
  resetDemo(): Promise<void>
}

export const apiMode: 'mock' | 'live' = import.meta.env.VITE_API_MODE === 'live' ? 'live' : 'mock'

export const api: ApiClient = apiMode === 'live' ? liveApi : mockApi
