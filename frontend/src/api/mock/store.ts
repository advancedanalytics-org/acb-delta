/**
 * In-memory demo store, persisted to localStorage so a page reload keeps the reviewer's decisions.
 * Only decisions are stored; impact status and VBPL counts are derived from them.
 */
import type { Decision, Impact, Vbpl } from '@/api/types'

import { reviewers, seedDecisions } from './fixtures'

const STORAGE_KEY = 'acb-delta.demo.decisions.v1'
const VBPL_STORAGE_KEY = 'acb-delta.demo.vbpls.v1'
const IMPACTS_STORAGE_KEY = 'acb-delta.demo.impacts.v1'

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

function loadImpacts(): Impact[] {
  try {
    const raw = localStorage.getItem(IMPACTS_STORAGE_KEY)
    if (raw) return JSON.parse(raw) as Impact[]
  } catch {
    // Storage blocked or corrupt
  }
  return []
}

let decisions: Decision[] = load()
let vbpls: Vbpl[] = loadVbpls()
let impacts: Impact[] = loadImpacts()

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions))
    localStorage.setItem(VBPL_STORAGE_KEY, JSON.stringify(vbpls))
    localStorage.setItem(IMPACTS_STORAGE_KEY, JSON.stringify(impacts))
  } catch {
    // Persistence is a convenience; the in-memory state still works.
  }
}

export const store = {
  decisions: () => decisions,
  vbpls: () => vbpls,
  impacts: () => impacts,
  add(decision: Decision) {
    decisions = [...decisions, decision]
    save()
  },
  addVbpl(vbpl: Vbpl) {
    vbpls = [vbpl, ...vbpls.filter((v) => v.id !== vbpl.id)]
    save()
  },
  removeVbpl(id: string) {
    vbpls = vbpls.filter((v) => v.id !== id)
    save()
  },
  updateVbpl(id: string, updates: Partial<Vbpl>) {
    vbpls = vbpls.map((v) => (v.id === id ? { ...v, ...updates } : v))
    save()
  },
  addImpacts(newImpacts: Impact[]) {
    const existingIds = new Set(impacts.map((i) => i.id))
    const toAdd = newImpacts.filter((i) => !existingIds.has(i.id))
    if (toAdd.length > 0) {
      impacts = [...impacts, ...toAdd]
      save()
    }
  },
  remove(decisionId: string) {
    decisions = decisions.filter((d) => d.id !== decisionId)
    save()
  },
  reset() {
    decisions = structuredClone(seedDecisions)
    vbpls = []
    impacts = []
    save()
  },
}
