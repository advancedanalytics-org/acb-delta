import { createContext, useContext, useState, type ReactNode } from 'react'

import type { Reviewer } from '@/api/types'
import { useReviewers } from '@/hooks/queries'

/** Demo user switcher in place of auth (out of scope, see PLAN.md "Phạm vi"). */
const STORAGE_KEY = 'acb-delta.reviewer'

interface CurrentUser {
  reviewer: Reviewer | undefined
  reviewers: Reviewer[]
  setReviewerId: (id: string) => void
}

const CurrentUserContext = createContext<CurrentUser | null>(null)

function savedReviewerId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function CurrentUserProvider({ children }: { children: ReactNode }) {
  const { data: reviewers = [] } = useReviewers()
  const [reviewerId, setId] = useState<string | null>(savedReviewerId)

  const setReviewerId = (id: string) => {
    setId(id)
    try {
      localStorage.setItem(STORAGE_KEY, id)
    } catch {
      // ignore blocked storage
    }
  }

  const reviewer = reviewers.find((r) => r.id === reviewerId) ?? reviewers[0]
  return <CurrentUserContext value={{ reviewer, reviewers, setReviewerId }}>{children}</CurrentUserContext>
}

export function useCurrentUser() {
  const value = useContext(CurrentUserContext)
  if (!value) throw new Error('useCurrentUser must be used inside CurrentUserProvider')
  return value
}
