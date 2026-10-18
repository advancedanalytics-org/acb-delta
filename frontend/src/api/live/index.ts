import type { ApiClient } from '@/api/client'
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
          return regs.map((d: {
            document_id: string
            title?: string
            doc_number?: string
            issuer?: string
            owner?: string
            version_id?: string
            processing_status?: string
            page_count?: number
            created_at?: string
            impact_count?: number
            pending_count?: number
          }) => {
            const isDone = d.processing_status === 'AI_PROPOSED' || d.processing_status === 'PROPOSED'
            const isFailed = d.processing_status === 'FAILED'
            const impactCount = d.impact_count || 0
            const pendingCount = d.pending_count ?? impactCount
            let status: Vbpl['status'] = 'processing'
            if (isDone) {
              if (impactCount === 0) {
                status = 'not_found'
              } else if (pendingCount === 0) {
                status = 'done'
              } else {
                status = 'awaiting_review'
              }
            } else if (isFailed) {
              status = 'failed'
            } else {
              status = 'processing'
            }

            return {
              id: d.document_id,
              number: d.doc_number || d.document_id,
              title: d.title || d.doc_number || d.document_id,
              issuer: d.issuer || d.owner || 'Ngân hàng Nhà nước Việt Nam',
              issuedDate: d.created_at ? d.created_at.slice(0, 10) : '',
              effectiveDate: d.created_at ? d.created_at.slice(0, 10) : '',
              receivedAt: d.created_at || new Date().toISOString(),
              summary: isDone
                ? impactCount === 0
                  ? 'AI không tìm thấy tác động nào đến văn bản nội bộ.'
                  : `Đã hoàn thành phân tích tác động pháp lý (${impactCount} điểm tác động).`
                : isFailed
                  ? 'Không thể bóc tách nghĩa vụ hoặc phân tích tác động.'
                  : 'Đang xử lý phân tích tác động...',
              status,
              impactCount,
              pendingCount,
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
    // 1. Try RIA regulations impacts endpoint
    try {
      const res = await fetch(`/api/regulations/${encodeURIComponent(vbplId)}/impacts`)
      if (res.ok) {
        const data = await res.json()
        if (Array.isArray(data)) {
          return data as Impact[]
        }
      }
    } catch {
      // Check vbpls impacts below
    }

    // 2. Try HITL vbpls impacts endpoint
    try {
      const vbplImpactRes = await fetch(`/api/vbpls/${encodeURIComponent(vbplId)}/impacts`)
      if (vbplImpactRes.ok) {
        const data = await vbplImpactRes.json()
        if (Array.isArray(data)) {
          return data as Impact[]
        }
      }
    } catch {
      // Empty
    }

    return []
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
            effective_date?: string
            page_count?: number
            pdf_url?: string
          }) => ({
            id: d.id,
            code: d.code || d.id,
            title: d.title || d.code || d.id,
            department: d.issuer || 'Khối Pháp chế & Tuân thủ',
            version: '1.0',
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

  getHealth: fetchHealth,

  resetDemo: () => Promise.resolve(),
}
