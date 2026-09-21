"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  Contrast,
  Maximize2,
  Trash2,
  ZoomIn,
  ZoomOut,
} from "lucide-react"

import {
  type Film,
  type Image as Frame,
  type PreviewRender,
  errorMessage,
  getImageDownloadUrl,
  getPreviewUrl,
  previewVersion,
  updateImage,
} from "@/lib/api"
import { formatDate, frameLabel } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/hooks/use-toast"

const NO_ROLL = "__none__"
const MIN_ZOOM = 1
const MAX_ZOOM = 6

/**
 * The three ways a scan can be shown, in the order the toggle walks through them
 * (R#94): there has to be a way back to "auto" once you have left it.
 */
const RENDER_CYCLE: PreviewRender[] = ["auto", "raw", "positive"]
const RENDER_LABEL: Record<PreviewRender, string> = {
  auto: "what the archive decides",
  raw: "the scan as stored",
  positive: "the positive preview",
}

/**
 * M8: what the toggle is actually switching between for *this* frame.
 *
 * A frame that came back from NegPy has two real files — the negative the
 * scanner made and the positive NegPy exported from it — and the toggle picks
 * one. Saying "the positive preview" there would be wrong twice over: it is not
 * a preview and it is not this backend's approximation, it is the export.
 */
function renderLabel(render: PreviewRender, hasExport: boolean): string {
  if (!hasExport) return RENDER_LABEL[render]
  if (render === "raw") return "the negative as scanned"
  return render === "auto" ? "NegPy's export" : "NegPy's export (the positive)"
}

/**
 * The frame viewer: previous/next, zoom, download and the metadata panel beside the
 * image. It replaces both the old image detail page and the old image edit page.
 */
export function FrameViewer({
  frames,
  index,
  onIndexChange,
  onClose,
  rolls,
  onChanged,
  onDeleted,
}: {
  frames: Frame[]
  index: number
  onIndexChange: (index: number) => void
  onClose: () => void
  rolls: Film[]
  onChanged?: (frame: Frame) => void
  onDeleted?: (frame: Frame) => void
}) {
  const { toast } = useToast()
  const frame = frames[index]

  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const drag = useRef<{ x: number; y: number } | null>(null)

  // M5: the scan on disk is a negative; this is how it is printed on screen.
  // "auto" follows the archive's setting, and the toggle overrides it for this
  // browser only — it is a way of looking, not a property of the frame.
  const [render, setRender] = useState<PreviewRender>("auto")
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem("negarchive.viewerRender")
      if (stored === "raw" || stored === "positive" || stored === "auto") setRender(stored)
    } catch {
      // a browser with storage switched off still gets the default
    }
  }, [])
  const chooseRender = (value: PreviewRender) => {
    setRender(value)
    try {
      // "auto" is the default, and the way to persist a default is to store nothing:
      // a stored "auto" would outlive a later change to what the archive follows.
      if (value === "auto") window.localStorage.removeItem("negarchive.viewerRender")
      else window.localStorage.setItem("negarchive.viewerRender", value)
    } catch {
      // see above
    }
  }

  const [draft, setDraft] = useState({ frame_number: "", capture_date: "", notes: "", film_roll_id: NO_ROLL })
  const [saving, setSaving] = useState(false)
  const [fieldError, setFieldError] = useState<string | null>(null)

  // A different frame resets both the view and the edit draft.
  useEffect(() => {
    if (!frame) return
    setZoom(1)
    setOffset({ x: 0, y: 0 })
    setFieldError(null)
    setDraft({
      frame_number: frame.frame_number === null ? "" : String(frame.frame_number),
      capture_date: frame.capture_date ?? "",
      notes: frame.notes ?? "",
      film_roll_id: frame.film_roll_id === null ? NO_ROLL : String(frame.film_roll_id),
    })
  }, [frame])

  const step = useCallback(
    (delta: number) => {
      if (frames.length < 2) return
      const next = (index + delta + frames.length) % frames.length
      onIndexChange(next)
    },
    [frames.length, index, onIndexChange],
  )

  // Arrow keys move between frames unless the user is typing in the metadata panel.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      // A contenteditable is typing too, even though its tag name is not an input.
      if (target && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable)) return
      if (event.key === "ArrowLeft") {
        event.preventDefault()
        step(-1)
      } else if (event.key === "ArrowRight") {
        event.preventDefault()
        step(1)
      } else if (event.key === "+" || event.key === "=") {
        event.preventDefault()
        setZoom((z) => Math.min(MAX_ZOOM, z + 0.5))
      } else if (event.key === "-") {
        event.preventDefault()
        setZoom((z) => Math.max(MIN_ZOOM, z - 0.5))
      } else if (event.key === "0") {
        event.preventDefault()
        setZoom(1)
        setOffset({ x: 0, y: 0 })
      }
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [step])

  if (!frame) return null

  const save = async () => {
    const typed = draft.frame_number.trim()
    const number = typed === "" ? null : Number(typed)
    // `Number("12a")` is NaN, and sending it as null would quietly wipe the number
    // the frame already has (R#74). Say so instead, and do not submit.
    if (number !== null && (!Number.isFinite(number) || number < 0)) {
      setFieldError("The frame number has to be a number.")
      return
    }
    setSaving(true)
    setFieldError(null)
    try {
      const updated = await updateImage(frame.id, {
        frame_number: number === null ? null : Math.trunc(number),
        capture_date: draft.capture_date.trim() === "" ? null : draft.capture_date,
        notes: draft.notes.trim() === "" ? null : draft.notes,
        film_roll_id: draft.film_roll_id === NO_ROLL ? null : Number(draft.film_roll_id),
      })
      onChanged?.(updated)
      toast({ title: "Frame saved" })
    } catch (error) {
      setFieldError(errorMessage(error, "Could not save this frame."))
    } finally {
      setSaving(false)
    }
  }

  const roll = rolls.find((r) => r.id === frame.film_roll_id) ?? null
  const nextRender = RENDER_CYCLE[(RENDER_CYCLE.indexOf(render) + 1) % RENDER_CYCLE.length]
  // M8: this frame has a real NegPy export behind it, not just an approximation.
  const hasExport = Boolean(frame?.rendition)

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        showCloseButton
        className="flex h-[100dvh] w-screen max-w-none flex-col gap-0 overflow-hidden rounded-none border-0 p-0 sm:max-w-none"
        data-testid="frame-viewer"
      >
        <DialogTitle className="sr-only">{frameLabel(frame)}</DialogTitle>
        <DialogDescription className="sr-only">
          Use the left and right arrow keys to move between frames, Escape to close.
        </DialogDescription>

        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          {/* Image stage */}
          <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-neutral-950">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              key={`${frame.id}-${render}`}
              src={getPreviewUrl(frame.id, 1600, render, previewVersion(frame, render))}
              alt={frameLabel(frame)}
              data-testid="viewer-image"
              className="max-h-full max-w-full object-contain select-none"
              style={{
                transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
                cursor: zoom > 1 ? "grab" : "default",
                transition: drag.current ? "none" : "transform 120ms ease-out",
              }}
              draggable={false}
              onMouseDown={(event) => {
                if (zoom <= 1) return
                drag.current = { x: event.clientX - offset.x, y: event.clientY - offset.y }
              }}
              onMouseMove={(event) => {
                if (!drag.current) return
                setOffset({ x: event.clientX - drag.current.x, y: event.clientY - drag.current.y })
              }}
              onMouseUp={() => {
                drag.current = null
              }}
              onMouseLeave={() => {
                drag.current = null
              }}
              onDoubleClick={() => {
                setZoom((z) => (z > 1 ? 1 : 2))
                setOffset({ x: 0, y: 0 })
              }}
            />

            {frames.length > 1 ? (
              <>
                <Button
                  variant="secondary"
                  size="icon"
                  aria-label="Previous frame"
                  data-testid="viewer-prev"
                  className="absolute top-1/2 left-2 h-12 w-12 -translate-y-1/2 opacity-90"
                  onClick={() => step(-1)}
                >
                  <ChevronLeft className="h-6 w-6" />
                </Button>
                <Button
                  variant="secondary"
                  size="icon"
                  aria-label="Next frame"
                  data-testid="viewer-next"
                  className="absolute top-1/2 right-2 h-12 w-12 -translate-y-1/2 opacity-90"
                  onClick={() => step(1)}
                >
                  <ChevronRight className="h-6 w-6" />
                </Button>
              </>
            ) : null}

            <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full bg-background/90 px-2 py-1 shadow-sm">
              <Button
                variant="ghost"
                size="icon"
                className="h-10 w-10"
                aria-label="Zoom out"
                onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - 0.5))}
                disabled={zoom <= MIN_ZOOM}
              >
                <ZoomOut className="h-4 w-4" />
              </Button>
              <span className="type-numeric w-12 text-center" data-testid="viewer-zoom">
                {Math.round(zoom * 100)}%
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="h-10 w-10"
                aria-label="Zoom in"
                onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + 0.5))}
                disabled={zoom >= MAX_ZOOM}
              >
                <ZoomIn className="h-4 w-4" />
              </Button>
              {/* M5: print the negative, or show the scan as it was stored. Not
                  offered for a frame that is already a positive (M6.1): there is
                  nothing to print, and the server would show it as is regardless. */}
              {frame.positive !== true || frame.rendition ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-10 w-10"
                  aria-label={`Showing ${renderLabel(render, hasExport)}; switch to ${renderLabel(nextRender, hasExport)}`}
                  title={`Showing ${renderLabel(render, hasExport)}; switch to ${renderLabel(nextRender, hasExport)}`}
                  data-testid="viewer-render-toggle"
                  onClick={() => chooseRender(nextRender)}
                >
                  <Contrast className="h-4 w-4" />
                </Button>
              ) : null}
              <Button
                variant="ghost"
                size="icon"
                className="h-10 w-10"
                aria-label="Fit to screen"
                onClick={() => {
                  setZoom(1)
                  setOffset({ x: 0, y: 0 })
                }}
              >
                <Maximize2 className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* Metadata panel */}
          <aside className="w-full shrink-0 overflow-y-auto border-t border-border bg-background p-4 lg:w-96 lg:border-t-0 lg:border-l">
            <div className="flex items-center gap-2">
              <h2 className="type-section">{frameLabel(frame)}</h2>
              <Badge variant="outline" className="type-numeric">
                {index + 1}/{frames.length}
              </Badge>
            </div>
            <p className="mt-1 type-meta">
              {roll ? roll.title : "Not in a roll"} · added {formatDate(frame.created_at)}
            </p>

            <div className="mt-4 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="viewer-frame-number">Frame number</Label>
                  <Input
                    id="viewer-frame-number"
                    data-testid="viewer-frame-number"
                    inputMode="numeric"
                    value={draft.frame_number}
                    onChange={(event) => setDraft({ ...draft, frame_number: event.target.value })}
                    className="h-11"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="viewer-capture-date">Captured</Label>
                  <Input
                    id="viewer-capture-date"
                    type="date"
                    value={draft.capture_date}
                    onChange={(event) => setDraft({ ...draft, capture_date: event.target.value })}
                    className="h-11"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="viewer-roll">Roll</Label>
                <Select
                  value={draft.film_roll_id}
                  onValueChange={(value) => setDraft({ ...draft, film_roll_id: value })}
                >
                  <SelectTrigger id="viewer-roll" className="h-11 w-full">
                    <SelectValue placeholder="Not in a roll" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_ROLL}>Not in a roll</SelectItem>
                    {rolls.map((item) => (
                      <SelectItem key={item.id} value={String(item.id)}>
                        {item.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="viewer-notes">Notes</Label>
                <Textarea
                  id="viewer-notes"
                  value={draft.notes}
                  onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
                  rows={4}
                  placeholder="What is on this frame?"
                />
              </div>

              {fieldError ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {fieldError}
                </p>
              ) : null}

              <div className="flex flex-wrap gap-2">
                <Button onClick={save} disabled={saving} className="min-h-11" data-testid="viewer-save">
                  {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Save
                </Button>
                <Button variant="outline" asChild className="min-h-11">
                  <a href={getImageDownloadUrl(frame)} download>
                    <Download className="mr-2 h-4 w-4" />
                    Download
                  </a>
                </Button>
                {onDeleted ? (
                  <Button
                    variant="ghost"
                    className="min-h-11 text-destructive hover:text-destructive"
                    onClick={() => onDeleted(frame)}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </Button>
                ) : null}
              </div>

              {/* M6.1: is this file a negative to be printed, or a finished positive
                  (a NegPy export, a scan of a print) to be shown as it is? Saved at
                  once — it is a fact about the file, not part of the draft. */}
              {frame.type === "scan" ? (
                <div className="space-y-1.5 border-t border-border pt-3">
                  <Label htmlFor="viewer-positive">Shown as</Label>
                  <Select
                    value={frame.positive == null ? "auto" : frame.positive ? "positive" : "negative"}
                    onValueChange={async (value) => {
                      try {
                        const updated = await updateImage(frame.id, {
                          positive: value === "auto" ? null : value === "positive",
                        })
                        onChanged?.(updated)
                      } catch (error) {
                        toast({ title: "Could not save", description: errorMessage(error), variant: "destructive" })
                      }
                    }}
                  >
                    <SelectTrigger id="viewer-positive" className="h-11 w-full" data-testid="viewer-positive">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">Decide from the film (print a negative)</SelectItem>
                      <SelectItem value="positive">Already a positive — show as it is</SelectItem>
                      <SelectItem value="negative">A negative — print it</SelectItem>
                    </SelectContent>
                  </Select>
                  {frame.positive === true ? (
                    <p className="type-meta">
                      A finished image — a NegPy export, or a scan of a print. It is never printed a second time.
                    </p>
                  ) : null}
                </div>
              ) : null}

              <dl className="space-y-1 border-t border-border pt-3">
                <div className="flex justify-between gap-4">
                  <dt className="type-meta">Type</dt>
                  <dd className="type-body">{frame.type === "scan" ? "Scan" : "Contact sheet"}</dd>
                </div>
                {/* R#7: the scanner's filename is the link to the physical frame, so
                    it is what the panel leads with; the stored name is a UUID. */}
                <div className="flex justify-between gap-4">
                  <dt className="type-meta">Original file</dt>
                  <dd
                    className="truncate type-numeric"
                    title={frame.original_filename ?? undefined}
                    data-testid="viewer-original-filename"
                  >
                    {frame.original_filename ?? "Not recorded"}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="type-meta">Stored as</dt>
                  <dd className="truncate type-numeric" title={frame.path}>
                    {frame.path.split("/").pop()}
                  </dd>
                </div>
                {frame.storage_mode === "linked" ? (
                  <div className="flex justify-between gap-4">
                    <dt className="type-meta">Storage</dt>
                    <dd className="type-body">Linked — the file is not managed here</dd>
                  </div>
                ) : null}
              </dl>

              {/* M5: what NegPy has done to this scan, and what the file itself
                  said when the archive read it. NegArchive does not interpret the
                  recipe — it reports that there is one, and summarises it. */}
              {frame.negpy_summary || frame.capture_metadata || frame.rendition ? (
                <div className="space-y-2 border-t border-border pt-3" data-testid="viewer-negpy">
                  {/* M8: the frame's two files. The negative is the frame; the
                      export is NegPy's positive of it, kept whole and reachable,
                      but never counted as a frame of its own. */}
                  {frame.rendition ? (
                    <div className="flex flex-wrap items-center gap-2" data-testid="viewer-rendition">
                      <Badge variant="secondary">NegPy export</Badge>
                      <span className="type-meta break-all">
                        {frame.rendition.original_filename ?? "the exported positive"}
                        {frame.rendition.negpy_edited_at
                          ? ` · ${formatDate(frame.rendition.negpy_edited_at)}`
                          : ""}
                      </span>
                      <a
                        href={getImageDownloadUrl({ id: frame.rendition.id } as Frame)}
                        className="type-meta underline"
                        data-testid="viewer-rendition-download"
                      >
                        Download
                      </a>
                    </div>
                  ) : null}
                  {frame.negpy_summary ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary">Edited in NegPy</Badge>
                      <span className="type-meta" data-testid="viewer-negpy-summary">
                        {frame.negpy_summary}
                        {frame.negpy_edited_at ? ` · ${formatDate(frame.negpy_edited_at)}` : ""}
                        {/* Which of the two sources this came from: the sidecar
                            beside the scan, or NegPy's own edits database. */}
                        {frame.negpy_recipe?.source === "edits.db" ? " · from edits.db" : ""}
                      </span>
                    </div>
                  ) : null}
                  {/* What the preview could and could not render. NegArchive
                      approximates NegPy's tone controls; it does not run its
                      pipeline, and the count is how it says so. */}
                  {frame.negpy_render && frame.negpy_render.total > 0 ? (
                    <p className="type-meta" data-testid="viewer-render-report">
                      Preview: {frame.negpy_render.summary}
                      {frame.negpy_render.ignored_count > 0
                        ? ` · not rendered: ${frame.negpy_render.ignored.slice(0, 4).join(", ")}${
                            frame.negpy_render.ignored_count > 4 ? "…" : ""
                          }`
                        : ""}
                    </p>
                  ) : null}
                  {frame.capture_metadata ? (
                    <dl className="space-y-1">
                      <div className="flex justify-between gap-4">
                        <dt className="type-meta">Read from the file</dt>
                        <dd className="type-body" data-testid="viewer-metadata-sources">
                          {frame.capture_metadata.sources.join(", ") || "nothing"}
                        </dd>
                      </div>
                      {([
                        ["Roll", frame.capture_metadata.roll],
                        ["Camera", frame.capture_metadata.camera],
                        ["Lens", frame.capture_metadata.lens],
                        ["Film", frame.capture_metadata.film_stock],
                        ["Developer", frame.capture_metadata.developer],
                      ] as const)
                        .filter(([, value]) => Boolean(value))
                        .map(([label, value]) => (
                          <div key={label} className="flex justify-between gap-4">
                            <dt className="type-meta">{label}</dt>
                            <dd className="truncate type-body" title={value ?? undefined}>
                              {value}
                            </dd>
                          </div>
                        ))}
                    </dl>
                  ) : null}
                </div>
              ) : null}
            </div>
          </aside>
        </div>
      </DialogContent>
    </Dialog>
  )
}
