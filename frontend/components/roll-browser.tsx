"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Film as FilmIcon, Images, MapPin, Pencil, Plus, Printer, Search, Trash2, X } from "lucide-react"

import {
  type Camera,
  type Film,
  type FilmQuery,
  type Filmstock,
  type Lens,
  type Location,
  type Page,
  ROLL_STATUSES,
  WORK_BUCKETS,
  type WorkLists,
  deleteFilm,
  errorMessage,
  getFilmsPage,
  getPreviewUrl,
} from "@/lib/api"
import { formatDateRange, formatStorage, pluralize } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { EmptyState } from "@/components/empty-state"
import { ErrorState } from "@/components/error-state"
import { MoveRollDialog } from "@/components/move-roll-dialog"
import { RollEditSheet } from "@/components/roll-edit-sheet"
import { RollWizard } from "@/components/roll-wizard"
import { StatusBadge } from "@/components/status-stepper"
import { useToast } from "@/hooks/use-toast"

const ANY = "__any__"

/** How long to wait after the last keystroke before asking the server. */
const DEBOUNCE_MS = 250

/**
 * The gear filters work on ids (M2, R#14). A `?camera=` from an older bookmark
 * still carries a name, so it is resolved against the catalog once on load — and
 * the API accepts either, so the server-rendered first page is right too.
 */
function initialGearFilter(raw: string | number | null | undefined, catalog: { id: number; name: string }[]): string {
  if (raw === null || raw === undefined || raw === "") return ANY
  const value = String(raw)
  if (/^\d+$/.test(value)) return value
  const match = catalog.find((item) => item.name.toLowerCase() === value.toLowerCase())
  return match ? String(match.id) : ANY
}

/**
 * The home page: every roll, with the four things you look for (film, camera, when,
 * where it is filed) and the frames you shot. The old separate Search page is these
 * four filters.
 *
 * **M3 (R#20): the filtering happens in Postgres, not here.** The first page is
 * server-rendered from the URL's query string — so a filtered list can be
 * bookmarked and shared — and every change after that asks the API for a fresh
 * page. An archive with 800 rolls used to ship all 800 to the browser on every
 * page load; now it ships 24 and a total.
 */
export function RollBrowser({
  initial,
  initialQuery,
  openWizard = false,
  focusSearch = false,
  cameras,
  lenses,
  filmstocks,
  locations = [],
  work = null,
}: {
  initial: Page<Film>
  initialQuery: FilmQuery
  /** `/?new=1` and the `/films/new` redirect open the wizard straight away. */
  openWizard?: boolean
  /** `/?focus=search`: land with the search box focused (the `/` shortcut, M4). */
  focusSearch?: boolean
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
  /** M4: the storage tree, for the forms and the move dialog. */
  locations?: Location[]
  /** M4: the four work lists with counts, shown as chips above the filters. */
  work?: WorkLists | null
}) {
  const router = useRouter()
  const { toast } = useToast()

  const [query, setQuery] = useState(initialQuery.q ?? "")
  const [camera, setCamera] = useState(() =>
    initialGearFilter(initialQuery.camera_id ?? initialQuery.camera, cameras),
  )
  const [film, setFilm] = useState(() =>
    initialGearFilter(initialQuery.film_stock_id ?? initialQuery.film_type, filmstocks),
  )
  const [from, setFrom] = useState(initialQuery.from ?? "")
  const [to, setTo] = useState(initialQuery.to ?? "")
  const [status, setStatus] = useState(initialQuery.status ?? "")
  const [bucket, setBucket] = useState(initialQuery.bucket ?? "")
  const [moving, setMoving] = useState<Film | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (focusSearch) searchRef.current?.focus()
  }, [focusSearch])

  const [items, setItems] = useState<Film[]>(initial.items)
  const [total, setTotal] = useState(initial.total)
  const [hasMore, setHasMore] = useState(initial.has_more)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [wizardOpen, setWizardOpen] = useState(openWizard)
  const [editing, setEditing] = useState<Film | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Film | null>(null)

  const filtersActive = Boolean(query || from || to || camera !== ANY || film !== ANY || status || bucket)

  const filters: FilmQuery = useMemo(
    () => ({
      q: query.trim() || undefined,
      // Ids from here on: the selects hold catalog ids, and the API filters on the
      // foreign key rather than on a name that a rename would invalidate.
      camera_id: camera === ANY ? undefined : Number(camera),
      film_stock_id: film === ANY ? undefined : Number(film),
      from: from || undefined,
      to: to || undefined,
      status: status || undefined,
      bucket: bucket || undefined,
    }),
    [query, camera, film, from, to, status, bucket],
  )

  const fetchPage = useCallback(
    async (offset: number, append: boolean) => {
      setLoading(true)
      try {
        const page = await getFilmsPage({ ...filters, offset })
        setItems((current) => (append ? [...current, ...page.items] : page.items))
        setTotal(page.total)
        setHasMore(page.has_more)
        setLoadError(null)
      } catch (error) {
        setLoadError(errorMessage(error, "Could not load the rolls."))
      } finally {
        setLoading(false)
      }
    },
    [filters],
  )

  // The first page came from the server; do not immediately fetch it again.
  const hydrated = useRef(false)
  useEffect(() => {
    if (!hydrated.current) {
      hydrated.current = true
      return
    }
    const handle = window.setTimeout(() => fetchPage(0, false), DEBOUNCE_MS)
    return () => window.clearTimeout(handle)
  }, [fetchPage])

  const clearFilters = () => {
    setQuery("")
    setCamera(ANY)
    setFilm(ANY)
    setFrom("")
    setTo("")
    setStatus("")
    setBucket("")
  }

  const confirmDelete = async ({ keepFiles }: { keepFiles: boolean }) => {
    if (!pendingDelete) return
    try {
      await deleteFilm(pendingDelete.id, keepFiles)
      toast({
        title: "Roll deleted",
        description: keepFiles
          ? `“${pendingDelete.title}” is gone from the archive; its files are still on disk.`
          : `“${pendingDelete.title}” and its scans are gone.`,
      })
      setPendingDelete(null)
      await fetchPage(0, false)
      router.refresh()
    } catch (error) {
      toast({ title: "Could not delete", description: errorMessage(error), variant: "destructive" })
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="type-page">Rolls</h1>
          <p className="mt-1 type-body text-muted-foreground">
            {filtersActive
              ? `${pluralize(total, "roll")} match${total === 1 ? "es" : ""} these filters`
              : `${pluralize(total, "roll")} in the archive`}
            {items.length < total ? ` · showing ${items.length}` : ""}
          </p>
        </div>
        <Button onClick={() => setWizardOpen(true)} className="min-h-11" data-testid="new-roll">
          <Plus className="mr-2 h-4 w-4" />
          New roll
        </Button>
      </div>

      {work ? (
        <div className="flex flex-wrap gap-2" data-testid="work-lists">
          {WORK_BUCKETS.map((entry) => {
            const total = work[entry.value].total
            const active = bucket === entry.value
            return (
              <button
                key={entry.value}
                type="button"
                onClick={() => {
                  setStatus("")
                  setBucket(active ? "" : entry.value)
                }}
                aria-pressed={active}
                data-testid={`work-${entry.value}`}
                className={cn(
                  "flex min-h-10 items-center gap-2 rounded-full border px-4 text-sm font-medium transition-colors",
                  active
                    ? "border-primary bg-primary text-primary-foreground"
                    : total > 0
                      ? "border-border bg-card hover:bg-secondary/60"
                      : "border-border text-muted-foreground",
                )}
              >
                {entry.label}
                <span className="type-numeric rounded-full bg-background/70 px-1.5 text-foreground">{total}</span>
              </button>
            )
          })}
          {work.needs_label > 0 ? (
            <Link
              href="/print/queue"
              className="flex min-h-10 items-center gap-2 rounded-full border border-dashed border-border px-4 text-sm font-medium text-muted-foreground hover:bg-secondary/60"
              data-testid="work-print-queue"
            >
              <Printer className="h-4 w-4" />
              {pluralize(work.needs_label, "label")} to print
            </Link>
          ) : null}
        </div>
      ) : null}

      <div className="rounded-lg border border-border bg-card p-3 sm:p-4">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5 lg:col-span-2">
            <Label htmlFor="roll-search">Search</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                ref={searchRef}
                id="roll-search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Title, notes, serial… or scan a code"
                className="h-11 pl-9"
                data-testid="roll-search"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="roll-camera">Camera</Label>
            <Select value={camera} onValueChange={setCamera}>
              <SelectTrigger id="roll-camera" className="h-11 w-full">
                <SelectValue placeholder="Any camera" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Any camera</SelectItem>
                {cameras.map((item) => (
                  <SelectItem key={item.id} value={String(item.id)}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="roll-film">Film</Label>
            <Select value={film} onValueChange={setFilm}>
              <SelectTrigger id="roll-film" className="h-11 w-full">
                <SelectValue placeholder="Any film" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Any film</SelectItem>
                {filmstocks.map((item) => (
                  <SelectItem key={item.id} value={String(item.id)}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="roll-from">Shot after</Label>
            <Input
              id="roll-from"
              type="date"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
              className="h-11"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="roll-to">Shot before</Label>
            <Input
              id="roll-to"
              type="date"
              value={to}
              onChange={(event) => setTo(event.target.value)}
              className="h-11"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="roll-status">Status</Label>
            <Select
              value={status || ANY}
              onValueChange={(value) => {
                setBucket("")
                setStatus(value === ANY ? "" : value)
              }}
            >
              <SelectTrigger id="roll-status" className="h-11 w-full">
                <SelectValue placeholder="Any status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Any status</SelectItem>
                {ROLL_STATUSES.map((step) => (
                  <SelectItem key={step.value} value={step.value}>
                    {step.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {filtersActive ? (
            <div className="flex items-end lg:col-span-2">
              <Button variant="ghost" onClick={clearFilters} className="min-h-11">
                <X className="mr-2 h-4 w-4" />
                Clear filters
              </Button>
            </div>
          ) : null}
        </div>
      </div>

      {loadError ? (
        <ErrorState
          title="Could not load the rolls"
          error={new Error(loadError)}
          reset={() => fetchPage(0, false)}
        />
      ) : items.length === 0 ? (
        filtersActive ? (
          <EmptyState
            icon={Search}
            title="No roll matches these filters"
            description="Try a different camera or film, or widen the date range."
            action={
              <Button variant="outline" onClick={clearFilters}>
                Clear filters
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={FilmIcon}
            title="No rolls yet"
            description="A roll is the unit of work: create one, then drop its scans in and number the frames."
            action={
              <Button onClick={() => setWizardOpen(true)}>
                <Plus className="mr-2 h-4 w-4" />
                New roll
              </Button>
            }
          />
        )
      ) : (
        <>
          <ul className="space-y-3" data-testid="roll-list">
            {items.map((roll) => (
              <li
                key={roll.id}
                className="rounded-lg border border-border bg-card p-3 transition-colors hover:border-muted-foreground/40 sm:p-4"
                data-testid="roll-row"
                data-frames={roll.image_count}
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-4">
                  <RollStrip roll={roll} />

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/films/${roll.id}`}
                        className="type-section truncate hover:underline"
                        data-testid="roll-title"
                      >
                        {roll.title}
                      </Link>
                      {roll.archive_serial ? (
                        <Badge variant="outline" className="type-numeric">
                          {roll.archive_serial}
                        </Badge>
                      ) : null}
                      <StatusBadge status={roll.status} />
                    </div>

                    <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-4">
                      <Meta label="Film" value={roll.film_type} />
                      <Meta label="Camera" value={roll.camera} />
                      <Meta label="Shot" value={formatDateRange(roll.start_date, roll.end_date)} />
                      <Meta label="Stored" value={formatStorage(roll)} />
                    </dl>
                  </div>

                  <div className="flex items-center gap-2 sm:flex-col sm:items-end">
                    <Badge variant="secondary" className="type-numeric whitespace-nowrap">
                      <Images className="mr-1 h-3 w-3" />
                      {pluralize(roll.image_count, "frame")}
                    </Badge>
                    <div className="ml-auto flex gap-1 sm:ml-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-10 w-10"
                        aria-label={`Move ${roll.title}`}
                        onClick={() => setMoving(roll)}
                      >
                        <MapPin className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-10 w-10"
                        aria-label={`Edit ${roll.title}`}
                        onClick={() => setEditing(roll)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-10 w-10"
                        aria-label={`Delete ${roll.title}`}
                        onClick={() => setPendingDelete(roll)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>

          {hasMore ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                className="min-h-11"
                disabled={loading}
                onClick={() => fetchPage(items.length, true)}
                data-testid="load-more-rolls"
              >
                {loading ? "Loading…" : `Load more (${total - items.length} left)`}
              </Button>
            </div>
          ) : null}
        </>
      )}

      <RollWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        cameras={cameras}
        lenses={lenses}
        filmstocks={filmstocks}
        locations={locations}
      />
      <RollEditSheet
        film={editing}
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        cameras={cameras}
        lenses={lenses}
        filmstocks={filmstocks}
        locations={locations}
      />
      <MoveRollDialog
        open={moving !== null}
        onOpenChange={(open) => !open && setMoving(null)}
        rolls={moving ? [moving] : []}
        locations={locations}
        onMoved={() => {
          void fetchPage(0, false)
          router.refresh()
        }}
      />
      <DeleteConfirmationDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        onConfirm={confirmDelete}
        offerKeepFiles
        title="Delete this roll?"
        description={`“${pendingDelete?.title}” and its ${pluralize(
          pendingDelete?.image_count ?? 0,
          "frame record",
        )} are removed from the archive, and the scan files are deleted with them.`}
      />
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="min-w-0">
      <dt className="type-meta uppercase tracking-wide">{label}</dt>
      <dd className="truncate type-body">{value || "—"}</dd>
    </div>
  )
}

/** Up to four real thumbnails per row; the ids come from `GET /api/films`. */
function RollStrip({ roll }: { roll: Film }) {
  const ids = roll.cover_image_ids?.length
    ? roll.cover_image_ids
    : roll.cover_image_id
      ? [roll.cover_image_id]
      : []

  if (ids.length === 0) {
    return (
      <div className="flex h-20 w-full shrink-0 items-center justify-center rounded-md border border-dashed border-border sm:w-44">
        <span className="type-meta">No scans yet</span>
      </div>
    )
  }

  return (
    <Link
      href={`/films/${roll.id}`}
      className="flex shrink-0 gap-1 rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      aria-label={`Open ${roll.title}`}
    >
      {ids.map((id, index) => (
        <span
          key={id}
          className={cn(
            "frame-cell h-20 w-[4.5rem] border border-border",
            index > 1 ? "hidden sm:block" : "",
          )}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={getPreviewUrl(id, 240)} alt="" loading="lazy" decoding="async" />
        </span>
      ))}
    </Link>
  )
}
