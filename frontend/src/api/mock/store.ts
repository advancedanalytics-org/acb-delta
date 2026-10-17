/**
 * In-memory demo store, persisted to localStorage so a page reload keeps the reviewer's decisions.
 * Only decisions are stored; impact status and VBPL counts are derived from them.
 */
import type { Decision } from '@/api/types'

import { seedDecisions } from './fixtures'

const STORAGE_KEY = 'acb-delta.demo.decisions.v1'

function load(): Decision[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as Decision[]
  } catch {
    // Storage blocked or corrupt: start from the seed.
  }
  return structuredClone(seedDecisions)
}

let decisions: Decision[] = load()

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions))
  } catch {
    // Persistence is a convenience; the in-memory state still works.
  }
}

export const store = {
  decisions: () => decisions,
  add(decision: Decision) {
    decisions = [...decisions, decision]
    save()
  },
  remove(decisionId: string) {
    decisions = decisions.filter((d) => d.id !== decisionId)
    save()
  },
  reset() {
    decisions = structuredClone(seedDecisions)
    save()
  },
}
