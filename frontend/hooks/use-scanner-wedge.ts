"use client"

import { useEffect, useRef } from "react"

/**
 * Detect a keyboard-wedge barcode scanner anywhere in the app (roadmap M4).
 *
 * A USB or Bluetooth scanner "types" the code as keystrokes and finishes with
 * Enter, far faster than a person can. This hook watches keydown events that land
 * outside a text input, collects characters that arrive within `gapMs` of each
 * other, and fires `onScan` with the buffer when Enter follows at least
 * `minLength` characters. Typing by hand never triggers it: a human pause resets
 * the buffer.
 *
 * Inputs and textareas are left alone on purpose — a scan into the search box is
 * handled by the search box.
 */
export function useScannerWedge(
  onScan: (code: string) => void,
  { gapMs = 60, minLength = 4, enabled = true }: { gapMs?: number; minLength?: number; enabled?: boolean } = {},
) {
  const buffer = useRef("")
  const last = useRef(0)
  const handler = useRef(onScan)
  handler.current = onScan

  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target) {
        const tag = target.tagName
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable) return
      }
      const now = performance.now()
      if (now - last.current > gapMs) buffer.current = ""
      last.current = now

      if (event.key === "Enter") {
        const code = buffer.current.trim()
        buffer.current = ""
        if (code.length >= minLength) {
          event.preventDefault()
          handler.current(code)
        }
        return
      }
      if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
        buffer.current += event.key
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [enabled, gapMs, minLength])
}
