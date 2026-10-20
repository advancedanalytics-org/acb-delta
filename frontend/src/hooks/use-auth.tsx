import { createContext, useContext, useState, type ReactNode } from 'react'

/**
 * DEMO-ONLY login gate for the hackathon demo.
 *
 * This is NOT real authentication: the credentials below are hardcoded and checked in the
 * browser, so anyone reading the bundle can see them. It only exists to put a branded login
 * screen in front of the demo. Do not use this for anything real — real auth is out of scope
 * (see PLAN.md "Phạm vi").
 */
const DEMO_USERNAME = 'acb'
const DEMO_PASSWORD = 'acb@2026'

/** Shown on the login screen so whoever runs the demo knows what to type. */
export const demoCredentials = { username: DEMO_USERNAME, password: DEMO_PASSWORD }

// Per-tab so a fresh demo session starts at the login screen; survives reloads within the tab.
const STORAGE_KEY = 'acb-delta.authed'

interface Auth {
  isAuthenticated: boolean
  /** Returns true on success; the caller shows an error on false. */
  login: (username: string, password: string) => boolean
  logout: () => void
}

const AuthContext = createContext<Auth | null>(null)

function savedAuthed(): boolean {
  try {
    return sessionStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setAuthed] = useState(savedAuthed)

  const login = (username: string, password: string) => {
    const ok = username.trim().toLowerCase() === DEMO_USERNAME && password === DEMO_PASSWORD
    if (ok) {
      setAuthed(true)
      try {
        sessionStorage.setItem(STORAGE_KEY, '1')
      } catch {
        // ignore blocked storage; the in-memory state still gates the app this session
      }
    }
    return ok
  }

  const logout = () => {
    setAuthed(false)
    try {
      sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      // ignore blocked storage
    }
  }

  return <AuthContext value={{ isAuthenticated, login, logout }}>{children}</AuthContext>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
