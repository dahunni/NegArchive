/*
 * NegArchive service worker — hand written, no build step, no dependency.
 *
 * Roadmap M3. The scope is deliberately small: **the lookup you do standing at
 * the shelf**. You are holding a binder, the archive server is in another room
 * and the wifi does not reach, and you want to know which roll this is and what
 * is on it. Everything else — uploading, editing, generating a contact sheet —
 * needs the server and says so.
 *
 * So this caches, read-only:
 *
 *   - the app shell (the HTML and the JS/CSS chunks Next.js serves),
 *   - the roll list and the roll pages you have actually visited,
 *   - the `GET /api/...` responses behind them,
 *   - the preview thumbnails you have already seen.
 *
 * Strategies, and why:
 *
 *   navigation & API   network first, falling back to the cache. An archive is a
 *                      record: showing yesterday's answer when today's is
 *                      available would be worse than a short wait.
 *   static chunks      cache first. They are content-hashed by Next, so a cached
 *                      one can never be stale.
 *   previews           cache first. They are immutable per (id, width, mtime).
 *
 * Nothing that changes data is ever cached or replayed: a POST, PUT or DELETE
 * that happens offline fails, visibly, and the person retries it in front of the
 * machine. A queue that silently applies edits hours later to an archive is a
 * good way to lose the link between paper and record.
 */

const VERSION = "v1"
const SHELL_CACHE = `negarchive-shell-${VERSION}`
const PAGE_CACHE = `negarchive-pages-${VERSION}`
const API_CACHE = `negarchive-api-${VERSION}`
const IMAGE_CACHE = `negarchive-images-${VERSION}`

const KNOWN_CACHES = [SHELL_CACHE, PAGE_CACHE, API_CACHE, IMAGE_CACHE]

/** Pages worth having before you ever go offline. */
const SHELL_URLS = ["/", "/images", "/manifest.webmanifest", "/icons/icon-192.png"]

/** Keep the caches from growing without bound on a phone. */
const LIMITS = { [PAGE_CACHE]: 60, [API_CACHE]: 120, [IMAGE_CACHE]: 300 }

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // One at a time and never fatal: a shell URL that 401s because a password
      // is set must not stop the worker installing.
      .then((cache) => Promise.all(SHELL_URLS.map((url) => cache.add(url).catch(() => undefined))))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((name) => !KNOWN_CACHES.includes(name)).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting()
})

async function trim(cacheName) {
  const limit = LIMITS[cacheName]
  if (!limit) return
  const cache = await caches.open(cacheName)
  const keys = await cache.keys()
  // Oldest first: `keys()` returns insertion order.
  for (const key of keys.slice(0, Math.max(0, keys.length - limit))) {
    await cache.delete(key)
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName)
  const hit = await cache.match(request)
  if (hit) return hit
  const response = await fetch(request)
  if (response.ok) {
    await cache.put(request, response.clone())
    trim(cacheName)
  }
  return response
}

async function networkFirst(request, cacheName, fallbackUrl) {
  const cache = await caches.open(cacheName)
  try {
    const response = await fetch(request)
    // Only ever cache a real answer. A 401 (the archive is password protected)
    // or a 500 must not become the offline copy.
    if (response.ok) {
      await cache.put(request, response.clone())
      trim(cacheName)
    }
    return response
  } catch (error) {
    const hit = await cache.match(request)
    if (hit) {
      // Let the page tell the person what they are looking at.
      const headers = new Headers(hit.headers)
      headers.set("X-NegArchive-Offline", "1")
      return new Response(hit.body, { status: hit.status, statusText: hit.statusText, headers })
    }
    if (fallbackUrl) {
      const shell = await caches.open(SHELL_CACHE)
      const fallback = await shell.match(fallbackUrl)
      if (fallback) return fallback
    }
    throw error
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request
  if (request.method !== "GET") return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  // Previews and catalog art: immutable, so the cache is always right.
  if (url.pathname.startsWith("/static/") || url.pathname.includes("/preview")) {
    event.respondWith(cacheFirst(request, IMAGE_CACHE))
    return
  }

  // Next's own build output is content-hashed.
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request, SHELL_CACHE))
    return
  }

  // Never cache the "am I online / who am I" endpoints: the whole point of them
  // is to answer for right now.
  if (url.pathname === "/api/health" || url.pathname === "/api/system/info") return

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(request, API_CACHE))
    return
  }

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, PAGE_CACHE, "/"))
  }
})
