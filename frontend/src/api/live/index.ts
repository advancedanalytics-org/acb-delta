import type { ApiClient } from '@/api/client'
import type { HealthReport } from '@/api/types'

/** Raised for endpoints whose backend task is not built yet. Shown in the screen's error state. */
export class ApiNotAvailableError extends Error {
  constructor(owner: string) {
    super(`Chưa có API (${owner})`)
    this.name = 'ApiNotAvailableError'
  }
}

const notYet = (owner: string) => () => Promise.reject(new ApiNotAvailableError(owner))

/** Readiness returns 503 with the same JSON body when a dependency fails, so read the body anyway. */
export async function fetchHealth(): Promise<HealthReport> {
  const response = await fetch('/api/health/ready')
  const body = await response.json().catch(() => null)
  if (!body?.checks) throw new Error(`Backend trả về HTTP ${response.status}`)
  return body as HealthReport
}

export const liveApi: ApiClient = {
  listVbpls: notYet('TAI-02'),
  listImpacts: notYet('TAI-02'),
  listDocuments: notYet('MINH-01 / HUY-02'),
  listAuditTrail: notYet('TAI-02'),
  decide: notYet('TAI-02'),
  undoDecision: notYet('TAI-02'),
  listReviewers: notYet('TAI-02'),
  listEvalRuns: notYet('KHOA-01'),
  getHealth: fetchHealth,
  resetDemo: () => Promise.resolve(),
}
