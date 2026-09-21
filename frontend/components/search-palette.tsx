"use client"

import { useRouter } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Aperture, Camera, Film, History, Images, MapPin, Package, Search, X } from "lucide-react"

import {
  type SearchGroup,
  type SearchHit,
  type SearchKind,
  type SearchResult,
  errorMessage,
  getPreviewUrl,
  searchArchive,
} from "@/lib/api"
import { formatDateRange, pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"

/** How long to wait after the last keystroke before asking the server. */
const DEBOUNCE_MS = 150
/** Results per group in the palette; "See all" goes to the full list. */
const PER_GROUP = 5
const RECENT_KEY = "negarchive.search.recent"
const RECENT_MAX = 8

/**
 * The search box that is one keystroke away from anywhere (M7).
 *
 * `⌘K` / `Ctrl+K`, the button in the header, or `/` on a page without its own
 * search box opens it. It asks `GET /api/search` for everything that matches —
 * rolls, frames, gear, locations — and shows the best few of each, ranked, with
 * the arrow keys walking the list and `Enter` opening the one under the cursor.
 * "See all" rows lead into the roll list and the frames page with the query
 * carried over, so the palette is a way in, not a dead end.
 *
 * It never fetches on mount, only on typing: the archive's search is cheap but
 * a dialog that hits the API to show an empty state is silly. Recent searches
 * are kept in localStorage, wrapped in try/catch like every other read of it.
 */
export function SearchPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter()
  const [query, setQuery] = useState("")
  const [result, setResult] = useState<SearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState(0)
  const [recent, setRecent] = useState<string[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const request = useRef(0)
  const controller = useRef<AbortController | null>(null)

  // Every opening starts empty, with the recent searches on offer: the last
  // query is one click away in that list, and a palette that reopens on stale
  // results looks like it has not noticed you typed.
  useEffect(() => {
    if (!open) return
    setQuery("")
    setResult(null)
    setError(null)
    setActive(0)
    setRecent(readRecent())
    // Radix moves focus into the dialog; the input has to be there first.
    const handle = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(handle)
  }, [open])

  // Ask the server after a pause, and only ever show the newest answer.
  useEffect(() => {
    if (!open) return
    const trimmed = query.trim()
    if (!trimmed) {
      controller.current?.abort()
      setResult(null)
      setLoading(false)
      setError(null)
      return
    }
    const ticket = (request.current += 1)
    const handle = window.setTimeout(async () => {
      controller.current?.abort()
      const abort = new AbortController()
      controller.current = abort
      setLoading(true)
      try {
        const payload = await searchArchive(trimmed, { limit: PER_GROUP, signal: abort.signal })
        if (ticket !== request.current) return
        setResult(payload)
        setError(null)
        setActive(0)
      } catch (err) {
        if (abort.signal.aborted || ticket !== request.current) return
        setError(errorMessage(err, "Could not search the archive."))
      } finally {
        if (ticket === request.current) setLoading(false)
      }
    }, DEBOUNCE_MS)
    return () => window.clearTimeout(handle)
  }, [query, open])

  /** Everything the arrow keys can land on, in the order it is drawn. */
  const rows = useMemo<Row[]>(() => {
    if (!result) return []
    const out: Row[] = []
    for (const group of result.groups) {
      if (group.items.length === 0) continue
      for (const hit of group.items) out.push({ kind: "hit", hit, group })
      const more = seeAllUrl(group, result.query)
      if (more && group.total > group.items.length) {
        out.push({ kind: "more", group, url: more })
      }
    }
    return out
  }, [result])

  const close = useCallback(() => onOpenChange(false), [onOpenChange])

  const go = useCallback(
    (url: string) => {
      const trimmed = query.trim()
      if (trimmed) setRecent(remember(trimmed))
      close()
      router.push(url)
    },
    [query, router, close],
  )

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault()
      setActive((index) => (rows.length ? (index + 1) % rows.length : 0))
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      setActive((index) => (rows.length ? (index - 1 + rows.length) % rows.length : 0))
    } else if (event.key === "Enter") {
      const row = rows[active]
      if (row) {
        event.preventDefault()
        go(row.kind === "hit" ? row.hit.url : row.url)
      } else if (query.trim()) {
        // Nothing came back yet, or nothing matched: the roll list is the fallback.
        event.preventDefault()
        go(`/?q=${encodeURIComponent(query.trim())}`)
      }
    } else if (event.key === "Home" && rows.length) {
      event.preventDefault()
      setActive(0)
    } else if (event.key === "End" && rows.length) {
      event.preventDefault()
      setActive(rows.length - 1)
    }
  }

  // Keep the active row in view when the keyboard moves it.
  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)
    node?.scrollIntoView({ block: "nearest" })
  }, [active])

  const trimmed = query.trim()
  const terms = useMemo(() => {
    const parsed = result?.parsed
    return parsed ? [...parsed.terms, ...parsed.phrases, ...Object.values(parsed.qualifiers).flat()] : []
  }, [result])
  const nothing = result !== null && trimmed !== "" && !loading && rows.length === 0

  let rowIndex = -1

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="top-[8vh] flex max-h-[84vh] w-[calc(100%-1.5rem)] translate-y-0 flex-col gap-0 overflow-hidden p-0 sm:top-[12vh] sm:max-w-2xl"
        data-testid="search-palette"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          inputRef.current?.focus()
        }}
      >
        <DialogTitle className="sr-only">Search the archive</DialogTitle>
        <DialogDescription className="sr-only">
          Type to find rolls, frames, gear and locations. Use the arrow keys to move and Enter to open.
        </DialogDescription>

        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search rolls, frames, gear, locations…"
            className="h-12 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground sm:h-14"
            role="combobox"
            aria-expanded={rows.length > 0}
            aria-controls="search-palette-results"
            aria-activedescendant={rows.length ? `search-row-${active}` : undefined}
            aria-autocomplete="list"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="go"
            data-testid="search-input"
          />
          {query ? (
            <button
              type="button"
              onClick={() => {
                setQuery("")
                inputRef.current?.focus()
              }}
              className="rounded-md p-1 text-muted-foreground hover:text-foreground"
              aria-label="Clear the search"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
          <kbd className="hidden rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground sm:inline">
            esc
          </kbd>
        </div>

        <div
          ref={listRef}
          id="search-palette-results"
          role="listbox"
          aria-label="Search results"
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2"
        >
          {!trimmed ? (
            <Idle recent={recent} onPick={(value) => setQuery(value)} onClear={() => setRecent(remember(null))} />
          ) : error ? (
            <p className="px-3 py-6 text-center type-body text-destructive" role="alert">
              {error}
            </p>
          ) : nothing ? (
            <div className="px-3 py-8 text-center">
              <p className="type-body">Nothing matches “{trimmed}”.</p>
              <p className="mt-1 type-meta">
                Try fewer words, or a different spelling
                {result?.fuzzy ? " — small typos are already forgiven" : ""}.
              </p>
            </div>
          ) : (
            result?.groups.map((group) => {
              if (group.items.length === 0) return null
              const more = seeAllUrl(group, result.query)
              return (
                <section key={group.kind} className="mb-2" aria-label={group.label}>
                  <h3 className="flex items-baseline justify-between px-3 pt-2 pb-1 type-meta uppercase tracking-wide">
                    <span>{group.label}</span>
                    <span className="type-numeric normal-case tracking-normal">
                      {group.total > group.items.length ? `${group.items.length} of ${group.total}` : group.total}
                    </span>
                  </h3>
                  <ul className="space-y-0.5">
                    {group.items.map((hit) => {
                      rowIndex += 1
                      const index = rowIndex
                      return (
                        <li key={`${hit.kind}-${hit.id}`}>
                          <ResultRow
                            hit={hit}
                            terms={terms}
                            active={index === active}
                            index={index}
                            onHover={() => setActive(index)}
                            onPick={() => go(hit.url)}
                          />
                        </li>
                      )
                    })}
                    {more && group.total > group.items.length
                      ? (() => {
                          rowIndex += 1
                          const index = rowIndex
                          return (
                            <li key={`${group.kind}-more`}>
                              <button
                                type="button"
                                id={`search-row-${index}`}
                                role="option"
                                aria-selected={index === active}
                                data-index={index}
                                data-testid="search-see-all"
                                onMouseEnter={() => setActive(index)}
                                onClick={() => go(more)}
                                className={cn(
                                  "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm text-muted-foreground",
                                  index === active ? "bg-secondary text-secondary-foreground" : "hover:bg-secondary/50",
                                )}
                              >
                                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-dashed border-border">
                                  <Search className="h-4 w-4" aria-hidden />
                                </span>
                                See all {pluralize(group.total, group.label.toLowerCase().replace(/s$/, ""))} matching “
                                {result.query}”
                              </button>
                            </li>
                          )
                        })()
                      : null}
                  </ul>
                </section>
              )
            })
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-3 py-2 type-meta">
          <span className="hidden sm:inline">
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> to move · <Kbd>↵</Kbd> to open
          </span>
          <span className="truncate">
            <code className="rounded bg-secondary px-1">camera:</code> <code className="rounded bg-secondary px-1">film:</code>{" "}
            <code className="rounded bg-secondary px-1">year:</code> <code className="rounded bg-secondary px-1">status:</code>{" "}
            <code className="rounded bg-secondary px-1">in:</code> narrow a word to one field
          </span>
          {loading ? <span className="ml-auto animate-pulse">Searching…</span> : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}

type Row = { kind: "hit"; hit: SearchHit; group: SearchGroup } | { kind: "more"; group: SearchGroup; url: string }

/** Where "See all" goes: the two lists that take `?q=`. Gear and locations have no filter of their own. */
function seeAllUrl(group: SearchGroup, query: string): string | null {
  const q = encodeURIComponent(query)
  if (group.kind === "roll") return `/?q=${q}`
  if (group.kind === "frame") return `/images?q=${q}`
  return null
}

function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="mx-0.5 rounded border border-border px-1 text-[10px]">{children}</kbd>
}

function Idle({ recent, onPick, onClear }: { recent: string[]; onPick: (value: string) => void; onClear: () => void }) {
  return (
    <div className="px-3 py-3">
      {recent.length > 0 ? (
        <>
          <div className="flex items-baseline justify-between pb-1">
            <h3 className="type-meta uppercase tracking-wide">Recent</h3>
            <button type="button" onClick={onClear} className="type-meta hover:underline">
              Clear
            </button>
          </div>
          <ul className="space-y-0.5" data-testid="search-recent">
            {recent.map((value) => (
              <li key={value}>
                <button
                  type="button"
                  onClick={() => onPick(value)}
                  className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm hover:bg-secondary/50"
                >
                  <History className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="truncate">{value}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="py-4 text-center type-meta">
          A title, a serial, a note on a frame, a camera, a film, a year, a binder — anything the archive knows.
        </p>
      )}
    </div>
  )
}

const KIND_ICON: Record<SearchKind, typeof Film> = {
  roll: Film,
  frame: Images,
  camera: Camera,
  lens: Aperture,
  film_stock: Package,
  location: MapPin,
}

function ResultRow({
  hit,
  terms,
  active,
  index,
  onHover,
  onPick,
}: {
  hit: SearchHit
  terms: string[]
  active: boolean
  index: number
  onHover: () => void
  onPick: () => void
}) {
  const Icon = KIND_ICON[hit.kind]
  const thumb = thumbnailFor(hit)
  const subtitle = subtitleFor(hit)
  return (
    <button
      type="button"
      id={`search-row-${index}`}
      role="option"
      aria-selected={active}
      data-index={index}
      data-testid="search-result"
      data-kind={hit.kind}
      onMouseEnter={onHover}
      onClick={onPick}
      className={cn(
        "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left",
        active ? "bg-secondary text-secondary-foreground" : "hover:bg-secondary/50",
      )}
    >
      <span className="frame-cell flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-md border border-border bg-card">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" className="h-full w-full object-cover" loading="lazy" decoding="async" />
        ) : (
          <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-sm font-medium">
            <Highlight text={hit.title} terms={terms} />
          </span>
          {hit.kind === "roll" && hit.serial ? (
            <span className="type-numeric shrink-0 rounded border border-border px-1 text-[11px] text-muted-foreground">
              <Highlight text={hit.serial} terms={terms} />
            </span>
          ) : null}
        </span>
        {subtitle ? (
          <span className="block truncate type-meta">
            <Highlight text={subtitle} terms={terms} />
          </span>
        ) : null}
      </span>
      <span className="hidden shrink-0 type-meta sm:inline">{kindLabel(hit)}</span>
    </button>
  )
}

function thumbnailFor(hit: SearchHit): string | null {
  if (hit.kind === "roll") return hit.cover_image_id ? getPreviewUrl(hit.cover_image_id, 120, undefined, hit.cover_version) : null
  if (hit.kind === "frame") return getPreviewUrl(hit.id, 120, undefined, hit.preview_version)
  if (hit.kind === "location") return null
  return hit.image_url
}

function subtitleFor(hit: SearchHit): string | null {
  if (hit.kind === "roll") {
    const when = formatDateRange(hit.start_date, hit.end_date)
    const bits = [hit.film_type, hit.camera, when === "—" ? null : when, hit.location_path]
    return bits.filter(Boolean).join(" · ") || null
  }
  if (hit.kind === "frame") {
    return [hit.notes, hit.original_filename].filter(Boolean).join(" · ") || null
  }
  if (hit.kind === "location") {
    const path = hit.path && hit.path !== hit.title ? hit.path : null
    return [path, hit.roll_count ? pluralize(hit.roll_count, "roll") : null].filter(Boolean).join(" · ") || null
  }
  return hit.subtitle
}

function kindLabel(hit: SearchHit): string {
  switch (hit.kind) {
    case "roll":
      return hit.status_label ?? "Roll"
    case "frame":
      return "Frame"
    case "camera":
      return "Camera"
    case "lens":
      return "Lens"
    case "film_stock":
      return "Film"
    case "location":
      return hit.kind_label
  }
}

/** The matched words in bold, so the eye lands on why this row is here. */
function Highlight({ text, terms }: { text: string; terms: string[] }) {
  const needles = terms.map((term) => term.trim()).filter((term) => term.length > 0)
  if (needles.length === 0) return <>{text}</>
  const pattern = new RegExp(`(${needles.map(escapeRegExp).join("|")})`, "ig")
  const parts = text.split(pattern)
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <mark key={index} className="rounded-sm bg-transparent font-semibold text-foreground underline decoration-primary/60 underline-offset-2">
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  )
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function readRecent(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string").slice(0, RECENT_MAX) : []
  } catch {
    return []
  }
}

/** Push a query to the front of the recent list (or clear it with null) and return the list. */
function remember(value: string | null): string[] {
  const next = value === null ? [] : [value, ...readRecent().filter((v) => v !== value)].slice(0, RECENT_MAX)
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    // Private mode, quota, or storage disabled: the palette still works.
  }
  return next
}
