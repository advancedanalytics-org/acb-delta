import { useEffect, useLayoutEffect, useRef } from 'react'

export type ShortcutHandlers = Partial<Record<'a' | 'e' | 'r' | 'j' | 'k' | '?', () => void>>

function isTyping(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

/** Single-key review shortcuts. Ignored while typing or when a modifier key is held. */
export function useReviewShortcuts(handlers: ShortcutHandlers, enabled = true) {
  // Keep the latest handlers without re-binding the listener on every render.
  const latest = useRef(handlers)
  useLayoutEffect(() => {
    latest.current = handlers
  })

  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.repeat || event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target)) return
      // Leave keys alone while a menu or dialog has focus.
      if (document.querySelector('[role="dialog"], [role="menu"]')) return
      const key = event.key === '?' ? '?' : event.key.toLowerCase()
      const handler = latest.current[key as keyof ShortcutHandlers]
      if (!handler) return
      event.preventDefault()
      handler()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled])
}
