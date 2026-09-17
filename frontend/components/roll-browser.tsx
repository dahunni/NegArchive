"use client"

import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { useMemo, useState } from "react"
import { Film as FilmIcon, Images, Pencil, Plus, Search, Trash2, X } from "lucide-react"

import {
  type Camera,
  type Film,
  type Filmstock,
  type Lens,
  deleteFilm,
  errorMessage,
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
import { RollEditSheet } from "@/components/roll-edit-sheet"
import { RollWizard } from "@/components/roll-wizard"
import { useToast } from "@/hooks/use-toast"

const ANY = "__any__"

/** Overlap test between the roll's shooting dates and the filter range. */
function withinRange(film: Film, from: string, to: string): boolean {
  if (!from && !to) return true
  const start = film.start_date || film.end_date
  const end = film.end_date || film.start_date
  if (!start || !end) return false
  if (from && end < from) return false
  if (to && start > to) return false
  return true
}

function matchesText(film: Film, needle: string): boolean {
  if (!needle) return true
  const haystack = [
    film.title,
    film.camera,
    film.lens,
    film.film_type,
    film.notes,
    film.building,
    film.folder,
    film.archive_serial,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
  return needle
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => haystack.includes(term))
}

/**
 * The home page: every roll, with the four things you look for (film, camera, when,
 * where it is filed) and the frames you shot. The old separate Search page is these
 * four filters.
 */
export function RollBrowser({
  films,
  cameras,
  lenses,
  filmstocks,
}: {
  films: Film[]
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
}) {
  const router = useRouter()
  const params = useSearchParams()
  const { toast } = useToast()

  const [query, setQuery] = useState(params.get("q") ?? "")
  const [camera, setCamera] = useState(params.get("camera") ?? ANY)
  const [film, setFilm] = useState(params.get("film") ?? ANY)
  const [from, setFrom] = useState(params.get("from") ?? "")
  const [to, setTo] = useState(params.get("to") ?? "")

  const [wizardOpen, setWizardOpen] = useState(params.get("new") === "1")
  const [editing, setEditing] = useState<Film | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Film | null>(null)

  const filtersActive = Boolean(query || from || to || camera !== ANY || film !== ANY)

  const visible = useMemo(
    () =>
      films.filter(
        (roll) =>
          matchesText(roll, query) &&
          (camera === ANY || roll.camera === camera) &&
          (film === ANY || roll.film_type === film) &&
          withinRange(roll, from, to),
      ),
    [films, query, camera, film, from, to],
  )

  const clearFilters = () => {
    setQuery("")
    setCamera(ANY)
    setFilm(ANY)
    setFrom("")
    setTo("")
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    try {
      await deleteFilm(pendingDelete.id)
      toast({ title: "Roll deleted", description: `“${pendingDelete.title}” is gone from the archive.` })
      setPendingDelete(null)
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
            {pluralize(films.length, "roll")} in the archive
            {filtersActive ? ` · ${visible.length} shown` : ""}
          </p>
        </div>
        <Button onClick={() => setWizardOpen(true)} className="min-h-11" data-testid="new-roll">
          <Plus className="mr-2 h-4 w-4" />
          New roll
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-card p-3 sm:p-4">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5 lg:col-span-2">
            <Label htmlFor="roll-search">Search</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="roll-search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Title, notes, serial, folder…"
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
                  <SelectItem key={item.id} value={item.name}>
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
                  <SelectItem key={item.id} value={item.name}>
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

      {films.length === 0 ? (
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
      ) : visible.length === 0 ? (
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
        <ul className="space-y-3" data-testid="roll-list">
          {visible.map((roll) => (
            <li
              key={roll.id}
              className="rounded-lg border border-border bg-card p-3 transition-colors hover:border-muted-foreground/40 sm:p-4"
              data-testid="roll-row"
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
      )}

      <RollWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        cameras={cameras}
        lenses={lenses}
        filmstocks={filmstocks}
      />
      <RollEditSheet
        film={editing}
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        cameras={cameras}
        lenses={lenses}
        filmstocks={filmstocks}
      />
      <DeleteConfirmationDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        onConfirm={confirmDelete}
        title="Delete this roll?"
        description={`“${pendingDelete?.title}” and its ${pluralize(
          pendingDelete?.image_count ?? 0,
          "frame record",
        )} are removed from the archive. The scan files stay on disk.`}
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
