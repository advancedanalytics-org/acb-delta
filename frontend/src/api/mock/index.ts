import type { ApiClient } from '@/api/client'
import { fetchHealth } from '@/api/live'
import type { AuditEntry, Decision, Impact, ImpactStatus, Vbpl } from '@/api/types'

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
  return vbplSeeds.map(({ processing, ...seed }) => {
    const own = impacts.filter((impact) => impact.vbplId === seed.id)
    const pendingCount = own.filter((impact) => impact.status === 'pending').length
    const status = processing ? 'processing' : pendingCount > 0 ? 'awaiting_review' : 'done'
    return { ...seed, status, impactCount: own.length, pendingCount }
  })
}

function buildAuditTrail(): AuditEntry[] {
  return [...store.decisions()].reverse().map((decision) => {
    const impact = impactSeeds.find((seed) => seed.id === decision.impactId)
    return {
      ...decision,
      vbplNumber: vbplSeeds.find((v) => v.id === decision.vbplId)?.number ?? decision.vbplId,
      documentCode: documents.find((d) => d.id === decision.documentId)?.code ?? decision.documentId,
      location: impact?.location ?? '',
      originalText: impact?.affectedText ?? '',
      suggestedText: impact?.suggestedText ?? '',
    }
  })
}

export const mockApi: ApiClient = {
  listVbpls: () => delay(buildVbpls()),
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
