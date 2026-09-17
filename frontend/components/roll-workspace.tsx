"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { ArrowLeft, Grid2x2, History, Loader2, MapPin, Pencil, Printer, Trash2 } from "lucide-react"

import {
  ACCEPTED_IMAGE_TYPES,
  type Camera,
  type Film,
  type Filmstock,
  type Image as Frame,
  type Lens,
  type Location,
  type RollMove,
  createContactSheet,
  deleteFilm,
  errorMessage,
  getPreviewUrl,
  uploadContactSheetFile,
  uploadRollFile,
} from "@/lib/api"
import { formatDateRange, formatDateTime, formatStorage, pluralize } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { FrameGrid } from "@/components/frame-grid"
import { FrameViewer } from "@/components/frame-viewer"
import { MoveRollDialog } from "@/components/move-roll-dialog"
import { NegpyHandoffButton } from "@/components/negpy-handoff-button"
import { PrintMenu } from "@/components/print-menu"
import { RollEditSheet } from "@/components/roll-edit-sheet"
import { StatusStepper } from "@/components/status-stepper"
import { UploadZone } from "@/components/upload-zone"
import { useToast } from "@/hooks/use-toast"

/**
 * One roll, as a workspace: the contact sheet on top, then the drop zone, then the
 * frames. Everything is edited here; nothing sends you to a separate form page.
 *
 * M4 adds the physical side: the lifecycle stepper, where the negatives are (and a
 * Move action), the strip/position of every frame, and the printouts.
 */
export function RollWorkspace({
  film: initialFilm,
  frames,
  contactSheets,
  rolls,
  cameras,
  lenses,
  filmstocks,
  locations = [],
  moves = [],
  editOnOpen = false,
}: {
  film: Film
  frames: Frame[]
  contactSheets: Frame[]
  rolls: Film[]
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
  locations?: Location[]
  moves?: RollMove[]
  editOnOpen?: boolean
}) {
  const router = useRouter()
  const { toast } = useToast()
  const [film, setFilm] = useState(initialFilm)
  const [editing, setEditing] = useState(editOnOpen)
  const [moving, setMoving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [sheetIndex, setSheetIndex] = useState<number | null>(null)
  const [showMoves, setShowMoves] = useState(false)

  // The server component is the source of truth; the local copy only exists so a
  // status click shows immediately instead of after the refresh round trip.
  useEffect(() => {
    setFilm(initialFilm)
  }, [initialFilm])

  const generate = async () => {
    setGenerating(true)
    try {
      await createContactSheet(film.id, { columns: film.effective_strips[0] ?? 6, thumb_size: 300 })
      toast({ title: "Contact sheet generated" })
      router.refresh()
    } catch (error) {
      toast({
        title: "Could not generate the contact sheet",
        description: errorMessage(error),
        variant: "destructive",
      })
    } finally {
      setGenerating(false)
    }
  }

  const removeRoll = async ({ keepFiles }: { keepFiles: boolean }) => {
    try {
      await deleteFilm(film.id, keepFiles)
      toast({
        title: "Roll deleted",
        description: keepFiles ? "The scan files are still on disk." : undefined,
      })
      router.push("/")
      router.refresh()
    } catch (error) {
      toast({ title: "Could not delete", description: errorMessage(error), variant: "destructive" })
    }
  }

  const capacity = film.effective_strips.reduce((sum, n) => sum + n, 0)

  return (
    <div className="space-y-6">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 min-h-11">
          <Link href="/">
            <ArrowLeft className="mr-2 h-4 w-4" />
            All rolls
          </Link>
        </Button>
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="type-page">{film.title}</h1>
            {film.archive_serial ? (
              <Badge variant="outline" className="type-numeric text-sm" data-testid="roll-serial">
                {film.archive_serial}
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 type-body text-muted-foreground">
            {[film.film_type, film.format, film.camera, film.lens].filter(Boolean).join(" · ") ||
              "No gear recorded"}
          </p>
          <p className="type-meta mt-1">
            {formatDateRange(film.start_date, film.end_date)} · {pluralize(frames.length, "frame")} ·{" "}
            {film.effective_strips.length} strips of {film.effective_strips[0]}
            {film.effective_strips.some((n) => n !== film.effective_strips[0]) ? " (mixed)" : ""} · {capacity} frames on the
            sleeve
          </p>
          {film.notes ? <p className="mt-3 max-w-2xl type-body">{film.notes}</p> : null}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="min-h-11" onClick={() => setEditing(true)} data-testid="edit-roll">
            <Pencil className="mr-2 h-4 w-4" />
            Edit roll
          </Button>
          <PrintMenu rollIds={[film.id]} />
          <Button
            variant="outline"
            className="min-h-11"
            onClick={generate}
            disabled={generating || frames.length < 2}
            title={frames.length < 2 ? "Needs at least two scans" : undefined}
          >
            {generating ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Grid2x2 className="mr-2 h-4 w-4" />
            )}
            Contact sheet
          </Button>
          {/* M5: prepare this roll's folder and preset for NegPy. */}
          <NegpyHandoffButton rollId={film.id} disabled={frames.length === 0} />
          <Button
            variant="ghost"
            className="min-h-11 text-destructive hover:text-destructive"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      {/* ------------------------------------------------------------ M4: paper */}
      <section className="grid gap-3 rounded-lg border border-border bg-card p-3 sm:grid-cols-[1fr_auto] sm:p-4" data-testid="roll-physical">
        <div className="min-w-0 space-y-3">
          <StatusStepper film={film} onChanged={(updated) => { setFilm(updated); router.refresh() }} />
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <MapPin className="h-4 w-4 text-muted-foreground" />
            <span className="type-body" data-testid="roll-location">
              {formatStorage(film)}
            </span>
            {film.location_id ? (
              <Link href={`/locations/${film.location_id}`} className="type-meta underline">
                Open location
              </Link>
            ) : null}
            {film.label_printed_at ? (
              <span className="type-meta">· label printed {formatDateTime(film.label_printed_at)}</span>
            ) : (
              <span className="type-meta">· no label printed yet</span>
            )}
          </div>
          {moves.length > 0 ? (
            <div>
              <button
                type="button"
                className="type-meta flex items-center gap-1 underline"
                onClick={() => setShowMoves((open) => !open)}
                aria-expanded={showMoves}
              >
                <History className="h-3 w-3" />
                {pluralize(moves.length, "move")}
              </button>
              {showMoves ? (
                <ol className="mt-2 space-y-1" data-testid="move-history">
                  {moves.map((move) => (
                    <li key={move.id} className="type-meta">
                      {formatDateTime(move.moved_at)} · {move.from ?? "unfiled"} → {move.to ?? "unfiled"}
                      {move.note ? ` · ${move.note}` : ""}
                    </li>
                  ))}
                </ol>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="flex items-start">
          <Button variant="outline" className="min-h-11" onClick={() => setMoving(true)} data-testid="move-roll">
            <MapPin className="mr-2 h-4 w-4" />
            Move…
          </Button>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="type-section">Contact sheet</h2>
        {contactSheets.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {contactSheets.map((sheet, index) => (
              <button
                key={sheet.id}
                type="button"
                onClick={() => setSheetIndex(index)}
                className="overflow-hidden rounded-lg border border-border bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                aria-label="Open contact sheet"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={getPreviewUrl(sheet.id, 1000)}
                  alt="Contact sheet"
                  loading="lazy"
                  className="max-h-80 w-full object-contain"
                  data-testid="contact-sheet-image"
                />
              </button>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border p-4">
            <p className="type-body text-muted-foreground">
              No contact sheet yet. Generate one from the frames below, print the sleeve cover sheet, or scan the
              paper sheet and drop it here.
            </p>
            <UploadZone
              className="mt-3"
              accept={ACCEPTED_IMAGE_TYPES}
              hint="Drop a scanned contact sheet"
              upload={(file, onProgress) => uploadContactSheetFile(film.id, file, onProgress)}
              onUploaded={() => router.refresh()}
            />
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="type-section">Add scans</h2>
        <UploadZone
          upload={(file, onProgress) => uploadRollFile(film.id, file, onProgress)}
          onUploaded={(images) => {
            toast({ title: `${pluralize(images.length, "frame")} added` })
            router.refresh()
          }}
          hint={`Drop this roll's scans here`}
        />
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="type-section">Frames</h2>
          <p className="type-meta hidden sm:block">
            Arrow keys move · Enter opens · Space selects · Esc clears
          </p>
        </div>
        <FrameGrid
          frames={frames}
          rolls={rolls}
          strips={film.effective_strips}
          emptyTitle="No frames in this roll yet"
          emptyDescription="Drop the scans above; they land here with their frame numbers ready to fill in."
        />
      </section>

      <RollEditSheet
        film={film}
        open={editing}
        onOpenChange={setEditing}
        cameras={cameras}
        lenses={lenses}
        filmstocks={filmstocks}
        locations={locations}
      />

      <MoveRollDialog
        open={moving}
        onOpenChange={setMoving}
        rolls={[film]}
        locations={locations}
        onMoved={() => router.refresh()}
      />

      {sheetIndex !== null ? (
        <FrameViewer
          frames={contactSheets}
          index={sheetIndex}
          onIndexChange={setSheetIndex}
          onClose={() => setSheetIndex(null)}
          rolls={rolls}
          onChanged={() => router.refresh()}
        />
      ) : null}

      <DeleteConfirmationDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        onConfirm={removeRoll}
        offerKeepFiles
        title="Delete this roll?"
        description={`“${film.title}” and its ${pluralize(
          frames.length,
          "frame record",
        )} are removed from the archive, and the scan files are deleted with them.`}
      />
    </div>
  )
}
