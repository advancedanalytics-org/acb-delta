import type { ApiClient } from '@/api/client'
import type { HealthReport, IngestDocumentResult, UploadVbplInput, Vbpl } from '@/api/types'

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
  listVbpls: async (): Promise<Vbpl[]> => {
    const response = await fetch('/api/documents?doc_type=vbpl')
    if (response.ok) {
      const docs = await response.json()
      return docs.map((d: {
        id: string
        code?: string
        title?: string
        issuer?: string
        effective_date?: string
        created_at?: string
        page_count: number
      }) => ({
        id: d.id,
        number: d.code || d.id,
        title: d.title || d.code || d.id,
        issuer: d.issuer || 'Ngân hàng Nhà nước Việt Nam',
        issuedDate: d.effective_date || '',
        effectiveDate: d.effective_date || '',
        receivedAt: d.created_at || new Date().toISOString(),
        summary: `Văn bản đã được chunking và ingest vào Vector DB (${d.page_count} trang).`,
        status: 'awaiting_review' as const,
        impactCount: 0,
        pendingCount: 0,
      }))
    }
    throw new ApiNotAvailableError('TAI-02')
  },
  uploadVbpl: async (input: UploadVbplInput): Promise<IngestDocumentResult> => {
    const formData = new FormData()
    formData.append('file', input.file)
    formData.append('doc_type', 'vbpl')
    if (input.code) formData.append('code', input.code)
    if (input.title) formData.append('title', input.title)
    if (input.issuer) formData.append('issuer', input.issuer)
    if (input.effectiveDate) formData.append('effective_date', input.effectiveDate)

    const response = await fetch('/api/documents/upload', {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      throw new Error(err.detail || `Tải lên thất bại (HTTP ${response.status})`)
    }

    return response.json()
  },
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

