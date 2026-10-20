import type { ApiClient } from '@/api/client'
import type {
  AuditEntry,
  Decision,
  DecisionInput,
  DocumentDetailResponse,
  EvalRun,
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

/** Readiness returns 503 with the same JSON body when a dependency fails, so read the body anyway. */
export async function fetchHealth(): Promise<HealthReport> {
  const response = await fetch('/api/health/ready')
  const body = await response.json().catch(() => null)
  if (!body?.checks) throw new Error(`Backend trả về HTTP ${response.status}`)
  return body as HealthReport
}

export const liveApi: ApiClient = {
  listVbpls: async (): Promise<Vbpl[]> => {
    // 1. Try /api/regulations (RIA regulations pipeline)
    try {
      const regRes = await fetch('/api/regulations')
      if (regRes.ok) {
        const regs = await regRes.json()
        if (Array.isArray(regs) && regs.length > 0) {
          // Status and counts come from the regulation's HITL review package (backend).
          return regs.map((d: {
            id?: string
            document_id: string
            version_id?: string
            vbpl_id?: string
            title?: string
            doc_number?: string
            issuer?: string
            owner?: string
            created_at?: string
            status: Vbpl['status']
            error?: string | null
            impact_count?: number
            pending_count?: number
          }) => {
            const impactCount = d.impact_count || 0
            const summary = {
              processing: 'Đang phân tích tác động và soạn đề xuất chỉnh sửa...',
              failed: d.error
                ? `${d.error}. Có thể xóa và tải lại văn bản.`
                : 'Không thể phân tích tác động hoặc soạn đề xuất chỉnh sửa.',
              not_found: 'AI không tìm thấy tác động nào đến văn bản nội bộ.',
            }[d.status as string] ?? `Đã hoàn thành phân tích tác động pháp lý (${impactCount} điểm tác động).`
            const uniqueId = d.vbpl_id || d.id || d.version_id || d.document_id
            return {
              id: uniqueId,
              number: d.doc_number || d.document_id,
              title: d.title || d.doc_number || d.document_id,
              issuer: d.issuer || d.owner || 'Ngân hàng Nhà nước Việt Nam',
              issuedDate: d.created_at ? d.created_at.slice(0, 10) : '',
              effectiveDate: d.created_at ? d.created_at.slice(0, 10) : '',
              receivedAt: d.created_at || new Date().toISOString(),
              summary,
              status: d.status,
              error: d.error ?? undefined,
              versionId: d.version_id,
              impactCount,
              pendingCount: d.pending_count ?? impactCount,
            }
          })
        }
      }
    } catch {
      // Fallback to /api/vbpls below
    }

    // 2. Try /api/vbpls (HITL vbpls)
    try {
      const vbplRes = await fetch('/api/vbpls')
      if (vbplRes.ok) {
        const vbpls = await vbplRes.json()
        if (Array.isArray(vbpls)) {
          return vbpls as Vbpl[]
        }
      }
    } catch {
      // Fallback
    }

    return []
  },

  deleteVbpl: async (vbpl: Vbpl): Promise<void> => {
    const versionId = vbpl.versionId ?? vbpl.id
    const response = await fetch(`/api/regulations/${encodeURIComponent(versionId)}`, { method: 'DELETE' })
    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      throw new Error(err.detail || `Xóa thất bại (HTTP ${response.status})`)
    }
  },

  uploadVbpl: async (input: UploadVbplInput): Promise<IngestDocumentResult> => {
    const formData = new FormData()
    formData.append('file', input.file)
    if (input.code) formData.append('doc_number', input.code)
    if (input.title) formData.append('title', input.title)
    if (input.issuer) formData.append('owner', input.issuer)
    if (input.effectiveDate) formData.append('valid_from', input.effectiveDate)

    const response = await fetch('/api/regulations', {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      throw new Error(err.detail || `Tải lên thất bại (HTTP ${response.status})`)
    }

    const data = (await response.json()) as { regulation_id: string; version_id: string; page_count: number }
    const regulationId = data.regulation_id

    // Trigger analysis
    const triggerAnalyze = async () => {
      for (let i = 0; i < 10; i++) {
        try {
          const res = await fetch(`/api/regulations/${encodeURIComponent(regulationId)}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
          })
          if (res.ok) break
          if (res.status === 409) {
            await new Promise((r) => setTimeout(r, 600))
            continue
          }
          break
        } catch {
          break
        }
      }
    }
    triggerAnalyze()

    return {
      status: 'processing',
      document: {
        id: regulationId,
        code: input.code || regulationId,
        title: input.title || input.file.name,
        doc_type: 'vbpl',
        issuer: input.issuer || 'Ngân hàng Nhà nước Việt Nam',
        effective_date: input.effectiveDate || new Date().toISOString().slice(0, 10),
        page_count: data.page_count || 1,
        created_at: new Date().toISOString(),
      },
      chunk_count: 0,
      chunks: [],
    }
  },

  listImpacts: async (vbplId: string): Promise<Impact[]> => {
    // 1. Direct fetch if vbplId is already a review package ID (/api/vbpls/{vbplId}/impacts)
    try {
      const direct = await fetch(`/api/vbpls/${encodeURIComponent(vbplId)}/impacts`)
      if (direct.ok) {
        const impacts = (await direct.json()) as Impact[]
        return impacts.map((impact) => ({
          ...impact,
          vbplId,
          decision: impact.decision && { ...impact.decision, vbplId },
        }))
      }
    } catch {
      // Fallback
    }

    // 2. Otherwise request or build the review package via /api/regulations/{vbplId}/review
    const review = await fetch(`/api/regulations/${encodeURIComponent(vbplId)}/review`, { method: 'POST' })
    let packageId = vbplId
    if (review.ok) {
      packageId = ((await review.json()) as { vbpl_id: string }).vbpl_id
    } else if (review.status === 409) {
      return []
    } else if (review.status !== 404) {
      throw new Error(`Không tải được gói duyệt (HTTP ${review.status})`)
    }
    // 404: not a RIA regulation but a VBPL posted to /api/vbpls (agent /invoke path).
    const res = await fetch(`/api/vbpls/${encodeURIComponent(packageId)}/impacts`)
    if (res.status === 404) return []
    if (!res.ok) throw new Error(`Không tải được tác động (HTTP ${res.status})`)
    const impacts = (await res.json()) as Impact[]
    // The UI keys caches and routes by the unique ID
    return impacts.map((impact) => ({
      ...impact,
      vbplId,
      decision: impact.decision && { ...impact.decision, vbplId },
    }))
  },

  listDocuments: async (): Promise<InternalDocument[]> => {
    try {
      const response = await fetch('/api/documents?doc_type=internal')
      if (response.ok) {
        const docs = await response.json()
        if (Array.isArray(docs)) {
          return docs.map((d: {
            id: string
            code?: string
            title?: string
            issuer?: string
            version_label?: string
            effective_date?: string
            page_count?: number
            pdf_url?: string
          }) => ({
            id: d.id,
            code: d.code || d.id,
            title: d.title || d.code || d.id,
            department: d.issuer || 'Khối Pháp chế & Tuân thủ',
            version: d.version_label || '1.0',
            effectiveDate: d.effective_date || '',
            pdfUrl: `/api/documents/${encodeURIComponent(d.id)}/pdf`,
            pageCount: d.page_count || 1,
          }))
        }
      }
    } catch {
      // Fallback
    }
    return []
  },

  listAuditTrail: async (): Promise<AuditEntry[]> => {
    try {
      const res = await fetch('/api/audit')
      if (res.ok) {
        return (await res.json()) as AuditEntry[]
      }
    } catch {
      // Fallback
    }
    return []
  },

  decide: async (input: DecisionInput): Promise<Decision> => {
    const res = await fetch('/api/decisions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Lỗi lưu quyết định (HTTP ${res.status})`)
    }
    return (await res.json()) as Decision
  },

  undoDecision: async (decisionId: string): Promise<void> => {
    const res = await fetch(`/api/decisions/${encodeURIComponent(decisionId)}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Lỗi hoàn tác quyết định (HTTP ${res.status})`)
    }
  },

  listReviewers: async (): Promise<Reviewer[]> => {
    try {
      const res = await fetch('/api/reviewers')
      if (res.ok) {
        return (await res.json()) as Reviewer[]
      }
    } catch {
      // Fallback
    }
    return []
  },

  listEvalRuns: async (): Promise<EvalRun[]> => {
    try {
      const res = await fetch('/api/eval/runs')
      if (res.ok) {
        return (await res.json()) as EvalRun[]
      }
    } catch {
      // Not yet implemented on backend
    }
    return []
  },

  getDocumentClauses: async (docId: string): Promise<DocumentDetailResponse> => {
    const res = await fetch(`/api/documents/${encodeURIComponent(docId)}/clauses`)
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Lỗi tải chi tiết văn bản (HTTP ${res.status})`)
    }
    return (await res.json()) as DocumentDetailResponse
  },

  ingestInternalDocument: async (file: File): Promise<IngestInternalResult> => {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch('/api/documents/ingest-internal', {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Lỗi nạp văn bản nội bộ (HTTP ${res.status})`)
    }
    return (await res.json()) as IngestInternalResult
  },

  getIngestInternalStatus: async (): Promise<IngestInternalStatus> => {
    try {
      const res = await fetch('/api/documents/ingest-internal-status')
      if (res.ok) {
        return (await res.json()) as IngestInternalStatus
      }
    } catch {
      // Fallback
    }
    return {
      is_processing: false,
      filename: null,
      status: 'idle',
      message: null,
      error: null,
    }
  },

  ingestInternalDataDir: async (): Promise<IngestInternalResult[]> => {
    const res = await fetch('/api/documents/ingest-internal-data-dir', {
      method: 'POST',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Lỗi quét dữ liệu data/ (HTTP ${res.status})`)
    }
    return (await res.json()) as IngestInternalResult[]
  },

  getFeedbackStatus: async (): Promise<FeedbackStatus | null> => {
    try {
      const res = await fetch('/api/eval/feedback-status')
      if (res.ok) {
        return (await res.json()) as FeedbackStatus
      }
    } catch {
      // Backend unreachable; the section renders an empty state.
    }
    return null
  },

  getHealth: fetchHealth,

  resetDemo: () => Promise.resolve(),
}
