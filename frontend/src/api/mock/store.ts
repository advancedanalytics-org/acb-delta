/**
 * In-memory demo store, persisted to localStorage so a page reload keeps the reviewer's decisions.
 * Only decisions are stored; impact status and VBPL counts are derived from them.
 */
import type { Decision, Vbpl } from '@/api/types'

import { reviewers, seedDecisions } from './fixtures'

const STORAGE_KEY = 'acb-delta.demo.decisions.v1'
const VBPL_STORAGE_KEY = 'acb-delta.demo.vbpls.v1'

function load(): Decision[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        return parsed.map((item) => {
          const reviewerObj =
            typeof item.reviewer === 'object' && item.reviewer && item.reviewer.name
              ? item.reviewer
              : reviewers.find((r) => r.id === (item.reviewer?.id ?? item.reviewer)) ?? reviewers[0]
          return {
            ...item,
            action: item.action ?? 'accept',
            reasonTags: Array.isArray(item.reasonTags) ? item.reasonTags : [],
            reviewer: reviewerObj,
            at: item.at && !isNaN(Date.parse(item.at)) ? item.at : new Date().toISOString(),
          }
        })
      }
    }
  } catch {
    // Storage blocked or corrupt: start from the seed.
  }
  return structuredClone(seedDecisions)
}

function loadVbpls(): Vbpl[] {
  try {
    const raw = localStorage.getItem(VBPL_STORAGE_KEY)
    if (raw) return JSON.parse(raw) as Vbpl[]
  } catch {
    // Storage blocked or corrupt
  }
  return []
}

let decisions: Decision[] = load()
let vbpls: Vbpl[] = loadVbpls()

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions))
    localStorage.setItem(VBPL_STORAGE_KEY, JSON.stringify(vbpls))
  } catch {
    // Persistence is a convenience; the in-memory state still works.
  }
}

export const store = {
  decisions: () => decisions,
  vbpls: () => vbpls,
  add(decision: Decision) {
    decisions = [...decisions, decision]
    save()
  },
  addVbpl(vbpl: Vbpl) {
    vbpls = [vbpl, ...vbpls.filter((v) => v.id !== vbpl.id)]
    save()
  },
  remove(decisionId: string) {
    decisions = decisions.filter((d) => d.id !== decisionId)
    save()
  },
  reset() {
    decisions = structuredClone(seedDecisions)
    vbpls = []
    save()
  },
}
