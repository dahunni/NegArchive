"use client"

import { useEffect, useMemo, useSyncExternalStore } from "react"

import { type AppVersion, type ChangelogEntry, FRONTEND_VERSION, getAppVersion } from "@/lib/api"

/** localStorage: the last version this browser was told about. */
const SEEN_KEY = "negarchive.version.seen"
/** A tab left open across an update finds out within this long. */
const POLL_MS = 10 * 60 * 1000

export interface VersionState {
  /** What the backend says, or null until the first answer (or when it cannot be reached). */
  info: AppVersion | null
  /**
   * Set when the archive is newer than what this browser last saw: the version
   * it came from and the changelog entries in between. Cleared by `acknowledge`.
   */
  updated: { from: string; entries: ChangelogEntry[] } | null
  /** The bundle in this tab was built for a different version than the backend runs. */
  staleFrontend: boolean
  acknowledge: () => void
  /** Ask the backend again now (the dialog does this when it opens). */
  refresh: () => void
}

/*
 * Which NegArchive is this, and has it changed since the last visit? (M7)
 *
 * The backend is the source of truth (`GET /api/system/version`); this browser
 * remembers the last version it saw in localStorage. Three cases:
 *
 *   - nothing remembered → a first visit. Remember it, say nothing: a new
 *     install has nothing to be told about.
 *   - remembered < current → an update. Report it with the entries in between,
 *     and only mark it seen when the person closes the dialog.
 *   - remembered > current → a rollback, or a different archive at the same
 *     address. Remember silently; there is no "what's old".
 *
 * It re-asks when the tab comes back into view and every ten minutes, so a tab
 * left open through `docker compose pull` notices too — and since that tab is
 * still running the old bundle, `staleFrontend` says so and the dialog offers
 * a reload.
 *
 * **Why a store and not a context.** The first answer lands a few dozen
 * milliseconds after the page loads — while the streamed page body is still a
 * dehydrated Suspense boundary waiting for React to hydrate it. A context
 * value changing above that boundary makes React give up on hydrating it and
 * client-render it instead: the whole page rendered twice, briefly present
 * twice in the DOM, and the smoke test tripping over duplicated elements. A
 * module-level store read through `useSyncExternalStore` re-renders only the
 * footer, the dialog and the About card, and leaves the page alone.
 */

type Snapshot = { info: AppVersion | null; updated: VersionState["updated"] }

let snapshot: Snapshot = { info: null, updated: null }
const SERVER_SNAPSHOT: Snapshot = { info: null, updated: null }
const listeners = new Set<() => void>()
let inflight = false
let polling = 0

function emit(next: Snapshot) {
  snapshot = next
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

async function check(): Promise<void> {
  if (inflight) return
  inflight = true
  try {
    const next = await getAppVersion()
    const seen = readSeen()
    let updated = snapshot.updated
    if (seen === null) {
      writeSeen(next.version)
    } else if (compareVersions(next.version, seen) > 0) {
      updated = { from: seen, entries: next.changelog.filter((entry) => compareVersions(entry.version, seen) > 0) }
    } else if (seen !== next.version) {
      writeSeen(next.version)
    }
    emit({ info: next, updated })
  } catch {
    // Offline, or the password gate is up: the footer just shows nothing.
  } finally {
    inflight = false
  }
}

function acknowledge() {
  if (snapshot.info) writeSeen(snapshot.info.version)
  emit({ ...snapshot, updated: null })
}

function refresh() {
  void check()
}

/** Started once by the shell: the first check, the poll and the visibility re-check. */
export function useVersionPolling(): void {
  useEffect(() => {
    polling += 1
    if (polling > 1) return () => void (polling -= 1)
    void check()
    const timer = window.setInterval(() => void check(), POLL_MS)
    const onVisible = () => {
      if (document.visibilityState === "visible") void check()
    }
    document.addEventListener("visibilitychange", onVisible)
    return () => {
      polling -= 1
      window.clearInterval(timer)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [])
}

/** The footer, the dialog and Settings read the store from here; only they re-render. */
export function useAppVersion(): VersionState {
  const { info, updated } = useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => SERVER_SNAPSHOT,
  )
  const staleFrontend = Boolean(info && FRONTEND_VERSION && info.version !== FRONTEND_VERSION)
  return useMemo(() => ({ info, updated, staleFrontend, acknowledge, refresh }), [info, updated, staleFrontend])
}

function readSeen(): string | null {
  try {
    return window.localStorage.getItem(SEEN_KEY)
  } catch {
    return null
  }
}

function writeSeen(version: string): void {
  try {
    window.localStorage.setItem(SEEN_KEY, version)
  } catch {
    // No storage: the dialog will show again next time, which is the honest fallback.
  }
}

/** `"0.10.0"` vs `"0.9.1"` numerically; a pre-release suffix sorts below its release. */
export function compareVersions(a: string, b: string): number {
  const ka = versionKey(a)
  const kb = versionKey(b)
  for (let i = 0; i < Math.max(ka.length, kb.length); i += 1) {
    const diff = (ka[i] ?? 0) - (kb[i] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}

function versionKey(version: string): number[] {
  const match = /^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(-.+)?$/.exec((version || "").trim())
  if (!match) return [-1]
  return [Number(match[1]), Number(match[2] ?? 0), Number(match[3] ?? 0), match[4] ? 0 : 1]
}
