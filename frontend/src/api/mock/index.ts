import type { ApiClient } from '@/api/client'
import { fetchHealth } from '@/api/live'
import type {
  AuditEntry,
  Decision,
  Impact,
  ImpactStatus,
  IngestDocumentResult,
  Vbpl,
  VbplStatus,
} from '@/api/types'

import { documents, evalRuns, impactSeeds, reviewers, vbplSeeds } from './fixtures'
import { store } from './store'

/** Simulated network latency so loading states are visible. */
function delay<T>(value: T): Promise<T> {
  const ms = 200 + Math.random() * 400
  return new Promise((resolve) => setTimeout(() => resolve(structuredClone(value)), ms))
}

/** crypto.randomUUID needs HTTPS or localhost; the team server is plain HTTP on an IP. */
const newId = () =>
  typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

const STATUS_BY_ACTION: Record<Decision['action'], ImpactStatus> = {
  accept: 'accepted',
  edit: 'accepted',
  reject: 'rejected',
}

function latestDecisions(): Map<string, Decision> {
  const latest = new Map<string, Decision>()
  for (const decision of store.decisions()) latest.set(decision.impactId, decision)
  return latest
}

function getAllImpactSeeds(): Omit<Impact, 'status'>[] {
  return [...impactSeeds, ...store.impacts()]
}

function buildImpacts(): Impact[] {
  const latest = latestDecisions()
  return getAllImpactSeeds().map((seed) => {
    const decision = latest.get(seed.id)
    if (!decision) return { ...seed, status: 'pending' }
    return {
      ...seed,
      status: STATUS_BY_ACTION[decision.action],
      finalText: decision.action === 'edit' ? decision.editedText : decision.action === 'accept' ? seed.suggestedText : undefined,
      decision,
    }
  })
}

function buildVbpls(): Vbpl[] {
  const impacts = buildImpacts()
  const customVbpls = store.vbpls().map((vbpl) => {
    const own = impacts.filter((impact) => impact.vbplId === vbpl.id)
    if (vbpl.status === 'processing') return vbpl
    if (own.length === 0) {
      return { ...vbpl, status: 'not_found' as const, impactCount: 0, pendingCount: 0 }
    }
    const pendingCount = own.filter((impact) => impact.status === 'pending').length
    const status: VbplStatus = pendingCount > 0 ? 'awaiting_review' : 'done'
    return { ...vbpl, status, impactCount: own.length, pendingCount }
  })
  const base: Vbpl[] = vbplSeeds.map(({ processing, ...seed }) => {
    const own = impacts.filter((impact) => impact.vbplId === seed.id)
    const pendingCount = own.filter((impact) => impact.status === 'pending').length
    const status: VbplStatus = processing ? 'processing' : own.length === 0 ? 'not_found' : pendingCount > 0 ? 'awaiting_review' : 'done'
    return { ...seed, status, impactCount: own.length, pendingCount }
  })
  return [...customVbpls, ...base]
}

function buildAuditTrail(): AuditEntry[] {
  const allSeeds = getAllImpactSeeds()
  return [...store.decisions()].reverse().map((decision) => {
    const impact = allSeeds.find((seed) => seed.id === decision.impactId)
    const reviewerObj =
      typeof decision.reviewer === 'object' && decision.reviewer && decision.reviewer.name
        ? decision.reviewer
        : reviewers.find((r) => r.id === (decision.reviewer?.id ?? decision.reviewer)) ?? reviewers[0]
    return {
      ...decision,
      action: decision.action ?? 'accept',
      reasonTags: Array.isArray(decision.reasonTags) ? decision.reasonTags : [],
      reviewer: reviewerObj,
      at: decision.at && !isNaN(Date.parse(decision.at)) ? decision.at : new Date().toISOString(),
      vbplNumber: vbplSeeds.find((v) => v.id === decision.vbplId)?.number ?? decision.vbplId ?? '',
      documentCode: documents.find((d) => d.id === decision.documentId)?.code ?? decision.documentId ?? '',
      location: impact?.location ?? '',
      originalText: impact?.affectedText ?? '',
      suggestedText: impact?.suggestedText ?? '',
    }
  })
}

export const mockApi: ApiClient = {
  listVbpls: () => delay(buildVbpls()),
  uploadVbpl: async (input) => {
    const formData = new FormData()
    formData.append('file', input.file)
    if (input.code) formData.append('doc_number', input.code)
    if (input.title) formData.append('title', input.title)
    if (input.issuer) formData.append('owner', input.issuer)
    if (input.effectiveDate) formData.append('valid_from', input.effectiveDate)

    let regulationId = `REG-${newId().toUpperCase()}`
    try {
      // 1. Call POST /api/regulations (create) in backend/app/routers/regulations.py
      const response = await fetch('/api/regulations', {
        method: 'POST',
        body: formData,
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err.detail || `Tải lên thất bại (HTTP ${response.status})`)
      }
      const data = (await response.json()) as { regulation_id?: string }
      if (data.regulation_id) {
        regulationId = data.regulation_id
      }
    } catch (err) {
      if (err instanceof Error && !err.message.includes('Failed to fetch')) {
        throw err
      }
    }

    // 2. Call POST /api/regulations/{regulation_id}/analyze
    const triggerAnalyze = async () => {
      for (let i = 0; i < 5; i++) {
        try {
          const res = await fetch(`/api/regulations/${encodeURIComponent(regulationId)}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
          })
          if (res.ok) break
          if (res.status === 409) {
            // Wait for parse job to reach PARSED
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

    // 3. Show document in UI with status "Đang xử lý" (processing)
    const newVbpl: Vbpl = {
      id: regulationId,
      number: input.code || regulationId,
      title: input.title || input.file.name,
      issuer: input.issuer || 'Ngân hàng Nhà nước Việt Nam',
      issuedDate: input.effectiveDate || new Date().toISOString().slice(0, 10),
      effectiveDate: input.effectiveDate || new Date().toISOString().slice(0, 10),
      receivedAt: new Date().toISOString(),
      summary: 'Hệ thống đang bóc tách điều khoản và phân tích tác động...',
      status: 'processing',
      impactCount: 0,
      pendingCount: 0,
    }
    store.addVbpl(newVbpl)

    // Pre-create impacts for this new regulation
    const newImpacts: Impact[] = impactSeeds.slice(0, 8).map((seed, idx) => ({
      ...seed,
      id: `${regulationId}-imp-${idx + 1}`,
      vbplId: regulationId,
      status: 'pending' as const,
    }))
    store.addImpacts(newImpacts)

    // 4. When processing completes, transition to "Chờ duyệt" (awaiting_review)
    setTimeout(() => {
      store.updateVbpl(regulationId, {
        status: 'awaiting_review',
        summary: 'Đã hoàn thành phân tích tác động pháp lý.',
        impactCount: newImpacts.length,
        pendingCount: newImpacts.length,
      })
    }, 3500)

    const result: IngestDocumentResult = {
      status: 'processing',
      document: {
        id: regulationId,
        code: input.code || regulationId,
        title: input.title || input.file.name,
        doc_type: 'vbpl',
        issuer: input.issuer || 'Ngân hàng Nhà nước Việt Nam',
        effective_date: input.effectiveDate || new Date().toISOString().slice(0, 10),
        page_count: 1,
        created_at: new Date().toISOString(),
      },
      chunk_count: newImpacts.length,
      chunks: [],
    }

    return delay(result)
  },
  listImpacts: (vbplId) => {
    let items = buildImpacts().filter((impact) => impact.vbplId === vbplId)
    // If no impacts exist for this uploaded vbpl, auto-generate them so review screen always works
    if (items.length === 0) {
      const vbpl = store.vbpls().find((v) => v.id === vbplId)
      if (vbpl) {
        const autoImpacts: Impact[] = impactSeeds.slice(0, 8).map((seed, idx) => ({
          ...seed,
          id: `${vbplId}-imp-${idx + 1}`,
          vbplId: vbplId,
          status: 'pending' as const,
        }))
        store.addImpacts(autoImpacts)
        items = buildImpacts().filter((impact) => impact.vbplId === vbplId)
      }
    }
    return delay(items)
  },
  listDocuments: () => delay(documents),
  listAuditTrail: () => delay(buildAuditTrail()),
  listReviewers: () => delay(reviewers),
  listEvalRuns: () => delay(evalRuns),

  decide(input) {
    const impact = getAllImpactSeeds().find((seed) => seed.id === input.impactId)
    const reviewer = reviewers.find((r) => r.id === input.reviewerId)
    if (!impact || !reviewer) return Promise.reject(new Error('Không tìm thấy tác động hoặc người duyệt'))
    const decision: Decision = {
      id: `dec-${newId()}`,
      impactId: impact.id,
      vbplId: impact.vbplId,
      documentId: impact.documentId,
      action: input.action,
      editedText: input.action === 'edit' ? input.editedText : undefined,
      reasonTags: input.reasonTags,
      reviewer,
      at: new Date().toISOString(),
    }
    store.add(decision)
    return delay(decision)
  },

  undoDecision(decisionId) {
    store.remove(decisionId)
    return delay(undefined)
  },

  getHealth: fetchHealth,

  resetDemo() {
    store.reset()
    return delay(undefined)
  },
}
