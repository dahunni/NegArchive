"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { ArrowLeft, Grid2x2, Loader2, Pencil, Trash2 } from "lucide-react"

import {
  type Camera,
  type Film,
  type Filmstock,
  type Image as Frame,
  type Lens,
  createContactSheet,
  deleteFilm,
  errorMessage,
  getPreviewUrl,
  uploadContactSheetFile,
  uploadRollFile,
} from "@/lib/api"
import { formatDateRange, formatStorage, pluralize } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog"
import { FrameGrid } from "@/components/frame-grid"
import { FrameViewer } from "@/components/frame-viewer"
import { RollEditSheet } from "@/components/roll-edit-sheet"
import { UploadZone } from "@/components/upload-zone"
import { useToast } from "@/hooks/use-toast"

/**
 * One roll, as a workspace: the contact sheet on top, then the drop zone, then the
 * frames. Everything is edited here; nothing sends you to a separate form page.
 */
export function RollWorkspace({
  film,
  frames,
  contactSheets,
  rolls,
  cameras,
  lenses,
  filmstocks,
  editOnOpen = false,
}: {
  film: Film
  frames: Frame[]
  contactSheets: Frame[]
  rolls: Film[]
  cameras: Camera[]
  lenses: Lens[]
  filmstocks: Filmstock[]
  editOnOpen?: boolean
}) {
  const router = useRouter()
  const { toast } = useToast()
  const [editing, setEditing] = useState(editOnOpen)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [sheetIndex, setSheetIndex] = useState<number | null>(null)

  const generate = async () => {
    setGenerating(true)
    try {
      await createContactSheet(film.id, { columns: 6, thumb_size: 300 })
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

  const removeRoll = async () => {
    try {
      await deleteFilm(film.id)
      toast({ title: "Roll deleted" })
      router.push("/")
      router.refresh()
    } catch (error) {
      toast({ title: "Could not delete", description: errorMessage(error), variant: "destructive" })
    }
  }

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
              <Badge variant="outline" className="type-numeric">
                {film.archive_serial}
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 type-body text-muted-foreground">
            {[film.film_type, film.camera, film.lens].filter(Boolean).join(" · ") || "No gear recorded"}
          </p>
          <p className="type-meta mt-1">
            {formatDateRange(film.start_date, film.end_date)} · {formatStorage(film)} ·{" "}
            {pluralize(frames.length, "frame")}
          </p>
          {film.notes ? <p className="mt-3 max-w-2xl type-body">{film.notes}</p> : null}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="min-h-11" onClick={() => setEditing(true)} data-testid="edit-roll">
            <Pencil className="mr-2 h-4 w-4" />
            Edit roll
          </Button>
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
              No contact sheet yet. Generate one from the frames below, or scan the paper sheet and
              drop it here.
            </p>
            <UploadZone
              className="mt-3"
              accept="image/*,.tif,.tiff"
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
        title="Delete this roll?"
        description={`“${film.title}” and its ${pluralize(
          frames.length,
          "frame record",
        )} are removed from the archive. The scan files stay on disk.`}
      />
    </div>
  )
}
