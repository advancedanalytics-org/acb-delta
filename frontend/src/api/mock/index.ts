import type { ApiClient } from '@/api/client'
import { fetchHealth } from '@/api/live'
import type { AuditEntry, Decision, Impact, ImpactStatus, Vbpl, VbplStatus } from '@/api/types'

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

function buildImpacts(): Impact[] {
  const latest = latestDecisions()
  return impactSeeds.map((seed) => {
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
  const base: Vbpl[] = vbplSeeds.map(({ processing, ...seed }) => {
    const own = impacts.filter((impact) => impact.vbplId === seed.id)
    const pendingCount = own.filter((impact) => impact.status === 'pending').length
    const status: VbplStatus = processing ? 'processing' : pendingCount > 0 ? 'awaiting_review' : 'done'
    return { ...seed, status, impactCount: own.length, pendingCount }
  })
  return [...store.vbpls(), ...base]
}

function buildAuditTrail(): AuditEntry[] {
  return [...store.decisions()].reverse().map((decision) => {
    const impact = impactSeeds.find((seed) => seed.id === decision.impactId)
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
    formData.append('doc_type', 'vbpl')
    if (input.code) formData.append('code', input.code)
    if (input.title) formData.append('title', input.title)
    if (input.issuer) formData.append('issuer', input.issuer)
    if (input.effectiveDate) formData.append('effective_date', input.effectiveDate)

    let result
    try {
      const response = await fetch('/api/documents/upload', {
        method: 'POST',
        body: formData,
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err.detail || `Tải lên thất bại (HTTP ${response.status})`)
      }
      result = await response.json()
    } catch {
      result = {
        status: 'success',
        document: {
          id: `vbpl-${newId()}`,
          code: input.code || input.file.name.replace(/\.pdf$/i, ''),
          title: input.title || input.file.name,
          doc_type: 'vbpl',
          issuer: input.issuer || 'Ngân hàng Nhà nước Việt Nam',
          effective_date: input.effectiveDate || new Date().toISOString().slice(0, 10),
          page_count: 1,
          created_at: new Date().toISOString(),
        },
        chunk_count: 8,
        chunks: [],
      }
    }

    const newVbpl: Vbpl = {
      id: result.document.id,
      number: result.document.code || result.document.id,
      title: result.document.title || result.document.code || input.file.name,
      issuer: result.document.issuer || 'Ngân hàng Nhà nước Việt Nam',
      issuedDate: result.document.effective_date || new Date().toISOString().slice(0, 10),
      effectiveDate: result.document.effective_date || new Date().toISOString().slice(0, 10),
      receivedAt: result.document.created_at || new Date().toISOString(),
      summary: `Đã chunking ${result.chunk_count} đoạn quy phạm pháp luật vào Vector DB.`,
      status: 'awaiting_review',
      impactCount: 0,
      pendingCount: 0,
    }
    store.addVbpl(newVbpl)

    return delay(result)
  },
  listImpacts: (vbplId) => delay(buildImpacts().filter((impact) => impact.vbplId === vbplId)),
  listDocuments: () => delay(documents),
  listAuditTrail: () => delay(buildAuditTrail()),
  listReviewers: () => delay(reviewers),
  listEvalRuns: () => delay(evalRuns),

  decide(input) {
    const impact = impactSeeds.find((seed) => seed.id === input.impactId)
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
