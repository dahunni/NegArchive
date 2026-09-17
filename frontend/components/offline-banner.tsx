"use client"

import { useEffect, useState } from "react"
import { CloudOff } from "lucide-react"

/**
 * Registers the service worker, and says so when the archive is unreachable.
 *
 * Roadmap M3. The PWA's job is the lookup you do standing at the shelf, so the
 * honest thing to do offline is not to pretend: the shell and the pages you have
 * already visited still work, and this banner says that everything else does not.
 * `navigator.onLine` alone is not enough — a phone on the house wifi with the
 * server switched off is very much "online" — so this also asks the backend.
 */
const HEALTH_INTERVAL_MS = 20000

export function OfflineBanner() {
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    if ("serviceWorker" in navigator) {
      // `catch` and move on: an unregistrable worker (http on a non-localhost
      // host, say) must not break the page it is meant to make more useful.
      navigator.serviceWorker.register("/sw.js").catch(() => undefined)
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    async function probe() {
      if (typeof navigator !== "undefined" && !navigator.onLine) {
        if (!cancelled) setOffline(true)
        return
      }
      try {
        const res = await fetch("/api/health", { cache: "no-store" })
        // A 401 means the archive is there and asking for the password, which is
        // a different problem; the login sheet handles that one.
        if (!cancelled) setOffline(!res.ok && res.status !== 401)
      } catch {
        if (!cancelled) setOffline(true)
      }
    }

    probe()
    const timer = window.setInterval(probe, HEALTH_INTERVAL_MS)
    window.addEventListener("online", probe)
    window.addEventListener("offline", probe)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      window.removeEventListener("online", probe)
      window.removeEventListener("offline", probe)
    }
  }, [])

  if (!offline) return null

  return (
    <div
      role="status"
      data-testid="offline-banner"
      className="flex items-center justify-center gap-2 border-b border-border bg-secondary px-4 py-2 text-center type-meta text-secondary-foreground"
    >
      <CloudOff className="h-4 w-4 shrink-0" aria-hidden />
      <span>
        Offline — showing the rolls you have already looked at. Uploading and editing need the archive.
      </span>
    </div>
  )
}
